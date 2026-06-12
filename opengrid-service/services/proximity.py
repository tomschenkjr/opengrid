"""
Proximity-based spatial filtering.

Supports queries like "crimes within 1000 feet of schools" by:
1. Fetching reference locations (schools, libraries, gas stations, Starbucks, etc.)
2. Filtering primary Socrata records to those within the specified distance

Reference sources:
  - Known Chicago Socrata datasets (schools, libraries, parks, CTA)
  - OpenStreetMap via Overpass API (gas stations, cafes, hospitals, etc.)
  - Named businesses via OSM name tag (Starbucks, McDonald's, etc.)
"""

import csv
import io
import json
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone
from math import radians, cos, sin, asin, sqrt
from pathlib import Path
import httpx
import yaml

# Chicago bounding box for Overpass API queries
_CHICAGO_BBOX = "(41.6,-87.9,42.1,-87.5)"
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "datasets.yaml"


def _load_datasets() -> list[dict]:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f).get("datasets", [])


def _find_dataset_by_alias(reference: str) -> dict | None:
    """Return the dataset entry whose proximity aliases match the reference string."""
    key = reference.lower().strip()
    for ds in _load_datasets():
        prox = ds.get("proximity") or {}
        aliases = [a.lower() for a in prox.get("aliases", [])]
        if key in aliases or ds["id"].lower() == key:
            return ds
    return None


# OSM-only proximity sources — Socrata sources are now in datasets.yaml
OSM_CONFIGS: dict[str, str] = {
    "libraries":     "amenity=library",
    "parks":         "leisure=park",
    "gas stations":  "amenity=fuel",
    "coffee shops":  "amenity=cafe",
    "cafes":         "amenity=cafe",
    "hospitals":     "amenity=hospital",
    "pharmacies":    "amenity=pharmacy",
    "grocery stores":"shop=supermarket",
    "supermarkets":  "shop=supermarket",
    "bars":          "amenity=bar",
    "restaurants":   "amenity=restaurant",
    "fast food":     "amenity=fast_food",
    "transit stops": "public_transport=stop_position",
}

# Persistent objects already rendered on the map — resolved from live data,
# but no separate reference layer is emitted (they're already visible).
PERSISTENT_PROXIMITY: set[str] = {
    # CTA El (train)
    "cta stations", "cta el stations", "l stations", "el stations",
    "cta train stations", "cta stops", "el stops", "l stops",
    "train stations",
    # CTA bus
    "bus stops", "bus stations", "cta bus stops", "cta bus stations",
}

_BUS_STOP_ALIASES: set[str] = {
    "bus stops", "bus stations", "cta bus stops", "cta bus stations",
}

_METRA_ALIASES: set[str] = {
    "metra stations", "metra stops", "metra train stations",
    "metra", "commuter rail stations", "commuter rail",
}

_FACILITY_ALIASES: dict[str, str] = {
    "libraries": "libraries",
    "library": "libraries",
    "police stations": "police-stations",
    "police station": "police-stations",
    "fire stations": "fire-stations",
    "fire station": "fire-stations",
    "speed cameras": "speed-cameras",
    "speed camera": "speed-cameras",
    "bike racks": "bike-racks",
    "bike rack": "bike-racks",
    "bicycle racks": "bike-racks",
    "bicycle rack": "bike-racks",
    "park facilities": "park-facilities",
    "park facility": "park-facilities",
    "basketball courts": "park-facilities",
    "basketball court": "park-facilities",
    "playgrounds": "park-facilities",
    "playground": "park-facilities",
    "tennis courts": "park-facilities",
    "tennis court": "park-facilities",
    "baseball fields": "park-facilities",
    "baseball field": "park-facilities",
    "sports fields": "park-facilities",
    "park amenities": "park-facilities",
    "park buildings": "park-buildings",
    "park building": "park-buildings",
    "fieldhouses": "park-buildings",
    "fieldhouse": "park-buildings",
    "concession stands": "park-buildings",
    "concession stand": "park-buildings",
    "harbor buildings": "park-buildings",
    "comfort stations": "park-buildings",
    "comfort station": "park-buildings",
    "park art": "park-art",
    "park district art": "park-art",
    "artworks": "park-art",
    "artwork": "park-art",
    "statues": "park-art",
    "statue": "park-art",
    "murals": "park-art",
    "mural": "park-art",
    "monuments": "park-art",
    "sculptures": "park-art",
}

_PARK_ALIASES: set[str] = {
    "parks", "park", "chicago parks", "park district parks",
}

_DIVVY_ALIASES: set[str] = {
    "divvy stations", "divvy station", "divvy bike stations", "bike share stations",
}

_OPEN_AIR_ALIASES: set[str] = {
    "open air sensors", "open air chicago sensors", "air quality sensors", "air sensors",
}

PERSISTENT_PROXIMITY.update(_METRA_ALIASES)
PERSISTENT_PROXIMITY.update(_FACILITY_ALIASES.keys())
PERSISTENT_PROXIMITY.update(_PARK_ALIASES)
PERSISTENT_PROXIMITY.update(_DIVVY_ALIASES)
PERSISTENT_PROXIMITY.update(_OPEN_AIR_ALIASES)

_METRA_GTFS_PROX_URL = os.getenv("METRA_GTFS_URL", "https://schedules.metrarail.com/gtfs/schedule.zip")
_metra_stops_prox_cache: dict = {"data": None, "expires": None}


async def _fetch_metra_station_locations() -> list[dict]:
    """Metra station locations from GTFS stops.txt. Cached 24h."""
    now = datetime.now(timezone.utc)
    if (_metra_stops_prox_cache["data"]
            and _metra_stops_prox_cache["expires"]
            and now < _metra_stops_prox_cache["expires"]):
        return _metra_stops_prox_cache["data"]

    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as http:
        r = await http.get(_METRA_GTFS_PROX_URL, headers={"User-Agent": "opengrid-service/1.0"})
        r.raise_for_status()
        content = r.content

    stops = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        with zf.open("stops.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            # Metra pads header names with a leading space (" stop_lat"), which
            # breaks plain key lookups — strip them like the main GTFS parser does.
            _ = reader.fieldnames
            reader.fieldnames = [n.strip() for n in reader.fieldnames]
            for row in reader:
                try:
                    lat = float(row.get("stop_lat") or 0)
                    lon = float(row.get("stop_lon") or 0)
                except (ValueError, TypeError):
                    continue
                if lat and lon:
                    stops.append({
                        "lat":  lat,
                        "lon":  lon,
                        "name": (row.get("stop_name") or "").strip(),
                    })

    _metra_stops_prox_cache["data"]    = stops
    _metra_stops_prox_cache["expires"] = now + timedelta(hours=24)
    return stops

_CTA_STOPS_PROXIMITY_URL = "https://data.cityofchicago.org/resource/8pix-ypme.json"


async def _fetch_cta_station_locations() -> list[dict]:
    """CTA El stations deduplicated by parent station (map_id) for proximity filtering."""
    app_token = os.getenv("SOCRATA_APP_TOKEN", "").strip() or None
    headers = {"User-Agent": "opengrid-service/1.0"}
    if app_token:
        headers["X-App-Token"] = app_token

    async with httpx.AsyncClient(headers=headers, timeout=20) as http:
        r = await http.get(
            _CTA_STOPS_PROXIMITY_URL,
            # This dataset has no stop_lat/stop_lon columns — coordinates live in
            # the `location` Point field only.
            params={"$limit": 2000, "$select": "map_id,station_name,location"},
        )
        r.raise_for_status()
        rows = r.json()

    seen: dict = {}
    for row in rows:
        map_id = row.get("map_id")
        if not map_id or map_id in seen:
            continue
        lat = lon = None
        loc = row.get("location") or {}
        if isinstance(loc, dict):
            if loc.get("type") == "Point":
                try:
                    coords = loc["coordinates"]
                    lon, lat = float(coords[0]), float(coords[1])
                except (KeyError, IndexError, TypeError, ValueError):
                    pass
            elif "latitude" in loc:
                try:
                    lat, lon = float(loc["latitude"]), float(loc["longitude"])
                except (KeyError, TypeError, ValueError):
                    pass
        if lat and lon:
            seen[map_id] = {"lat": lat, "lon": lon, "name": row.get("station_name", "")}

    return list(seen.values())


async def _fetch_bus_stop_locations(bounds: dict | None = None) -> list[dict]:
    """
    CTA bus stops via OSM, scoped to the viewport when bounds are provided.
    Capped at 500 to keep proximity filtering fast.
    """
    if bounds:
        bbox = f"({bounds['minLat']},{bounds['minLon']},{bounds['maxLat']},{bounds['maxLon']})"
    else:
        bbox = _CHICAGO_BBOX
    locs = await _fetch_osm_amenity("highway=bus_stop", bbox=bbox)
    return locs[:500]


async def _fetch_facility_locations(kind: str) -> list[dict]:
    from routers import stations as station_data

    rows = await station_data._fetch_facilities(kind)
    return [
        {"lat": row["lat"], "lon": row["lon"], "name": row.get("title") or row.get("name")}
        for row in rows
        if row.get("lat") and row.get("lon")
    ]


async def _fetch_park_locations() -> list[dict]:
    from routers import stations as station_data

    rows = await station_data._fetch_parks()
    return [
        {"lat": row["lat"], "lon": row["lon"], "name": row.get("title") or row.get("park")}
        for row in rows
        if row.get("lat") and row.get("lon")
    ]


async def _fetch_divvy_station_locations() -> list[dict]:
    from routers import stations as station_data

    rows = await station_data._fetch_divvy_stations()
    return [
        {"lat": row["lat"], "lon": row["lon"], "name": row.get("name")}
        for row in rows
        if row.get("lat") and row.get("lon")
    ]


async def _fetch_open_air_sensor_locations() -> list[dict]:
    from routers import stations as station_data

    rows = await station_data._fetch_open_air_latest()
    return [
        {"lat": row["lat"], "lon": row["lon"], "name": row.get("sensor_name")}
        for row in rows
        if row.get("lat") and row.get("lon")
    ]


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in meters between two lat/lon points."""
    R = 6371000.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


async def _fetch_socrata_locations(config: dict) -> list[dict]:
    """Fetch location dicts from a Chicago Socrata dataset."""
    app_token = os.getenv("SOCRATA_APP_TOKEN", "").strip() or None
    headers = {"User-Agent": "opengrid-service/1.0"}
    if app_token:
        headers["X-App-Token"] = app_token

    lat_field = config["lat"]
    lon_field = config["lon"]
    name_field = config.get("name")
    limit = config.get("limit", 500)

    select = f"{lat_field},{lon_field}"
    if name_field:
        select += f",{name_field}"

    async with httpx.AsyncClient(headers=headers, timeout=20) as http:
        r = await http.get(
            f"https://data.cityofchicago.org/resource/{config['dataset_id']}.json",
            params={"$limit": limit, "$select": select},
        )
        r.raise_for_status()
        rows = r.json()

    locs = []
    for row in rows:
        try:
            lat = float(row.get(lat_field, 0) or 0)
            lon = float(row.get(lon_field, 0) or 0)
            if lat and lon:
                entry: dict = {"lat": lat, "lon": lon}
                if name_field and row.get(name_field):
                    entry["name"] = row[name_field]
                locs.append(entry)
        except (ValueError, TypeError):
            continue
    return locs


async def _fetch_dataset_locations(ds: dict) -> list[dict]:
    """Fetch location dicts from a datasets.yaml entry."""
    prox = ds.get("proximity") or {}
    config = {
        "dataset_id": ds["socrata_dataset_id"],
        "lat": ds.get("lat_field", "latitude"),
        "lon": ds.get("lon_field", "longitude"),
        "limit": prox.get("limit", 1000),
    }
    name_field = prox.get("name_field")
    if name_field:
        config["name"] = name_field
    return await _fetch_socrata_locations(config)


async def _fetch_osm_amenity(tag: str, bbox: str | None = None) -> list[dict]:
    """Fetch locations from OpenStreetMap via Overpass API using a tag query."""
    key, _, value = tag.partition("=")
    bbox = bbox or _CHICAGO_BBOX
    query = (
        f"[out:json][timeout:15];"
        f"(node[{key}={value}]{bbox};"
        f"way[{key}={value}]{bbox};);"
        f"out center tags;"
    )
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.post(_OVERPASS_URL, data={"data": query})
        r.raise_for_status()
        data = r.json()

    locs = []
    for el in data.get("elements", []):
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat and lon:
            entry: dict = {"lat": float(lat), "lon": float(lon)}
            name = (el.get("tags") or {}).get("name")
            if name:
                entry["name"] = name
            locs.append(entry)
    return locs


async def _fetch_osm_by_name(name: str) -> list[dict]:
    """Fetch locations of a named business/entity from OSM."""
    safe_name = name.replace('"', '\\"')
    query = (
        f'[out:json][timeout:15];'
        f'(node["name"="{safe_name}"]{_CHICAGO_BBOX};'
        f'way["name"="{safe_name}"]{_CHICAGO_BBOX};);'
        f'out center tags;'
    )
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.post(_OVERPASS_URL, data={"data": query})
        if r.status_code != 200:
            return []
        data = r.json()

    locs = []
    for el in data.get("elements", []):
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat and lon:
            entry: dict = {"lat": float(lat), "lon": float(lon)}
            osm_name = (el.get("tags") or {}).get("name")
            if osm_name:
                entry["name"] = osm_name
            locs.append(entry)
    return locs


_ARCGIS_CANDIDATES_URL = (
    "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
)
_GEOCODE_MIN_SCORE = 75


def _looks_like_address(reference: str) -> bool:
    """True if the reference starts with a street number, e.g. '900 W Washington Blvd'."""
    return bool(re.match(r"^\d+\s", reference.strip()))


async def _geocode_address(address: str) -> list[dict]:
    """Geocode a street address within Chicago via ArcGIS findAddressCandidates."""
    params = {
        "SingleLine": f"{address}, Chicago, IL",
        "f": "json",
        "maxLocations": 1,
        "outFields": "Match_addr",
    }
    async with httpx.AsyncClient(timeout=10) as http:
        r = await http.get(_ARCGIS_CANDIDATES_URL, params=params)
        r.raise_for_status()
        data = r.json()

    locs = []
    for candidate in data.get("candidates", []):
        if candidate.get("score", 0) < _GEOCODE_MIN_SCORE:
            continue
        loc = candidate.get("location", {})
        lon, lat = loc.get("x"), loc.get("y")
        if lon is not None and lat is not None:
            name = candidate.get("attributes", {}).get("Match_addr") or address
            locs.append({"lat": float(lat), "lon": float(lon), "name": name})
    print(f"[_geocode_address] '{address}' → {locs}")
    return locs


async def fetch_reference_locations(reference: str, bounds: dict | None = None) -> list[dict]:
    """
    Return location dicts {lat, lon, name?} for a named reference type.
    Resolution order:
      1. Persistent map objects (CTA stations, bus stops) — no reference layer emitted
      2. datasets.yaml proximity aliases (Socrata)
      3. OSM_CONFIGS (known OSM amenity tags)
      4. Street addresses → ArcGIS geocoder
      5. Named businesses / landmarks → OSM name search
    """
    key = reference.lower().strip()

    try:
        if key in PERSISTENT_PROXIMITY:
            if key in _BUS_STOP_ALIASES:
                return await _fetch_bus_stop_locations(bounds)
            if key in _METRA_ALIASES:
                return await _fetch_metra_station_locations()
            if key in _FACILITY_ALIASES:
                return await _fetch_facility_locations(_FACILITY_ALIASES[key])
            if key in _PARK_ALIASES:
                return await _fetch_park_locations()
            if key in _DIVVY_ALIASES:
                return await _fetch_divvy_station_locations()
            if key in _OPEN_AIR_ALIASES:
                return await _fetch_open_air_sensor_locations()
            return await _fetch_cta_station_locations()

        ds = _find_dataset_by_alias(reference)
        if ds:
            return await _fetch_dataset_locations(ds)

        osm_tag = OSM_CONFIGS.get(key)
        if osm_tag:
            return await _fetch_osm_amenity(osm_tag)

        if _looks_like_address(reference):
            return await _geocode_address(reference)

        return await _fetch_osm_by_name(reference)
    except Exception as e:
        print(f"Proximity: failed to fetch locations for '{reference}': {e}")
        return []


def filter_by_proximity(
    records: list[dict],
    lat_field: str,
    lon_field: str,
    reference_locs: list[dict],
    distance_meters: float,
) -> list[dict]:
    """
    Return only records within distance_meters of at least one reference location.
    Uses Haversine distance. O(n×m) — fast enough for n,m < 10,000.
    """
    if not reference_locs:
        return records

    result = []
    for record in records:
        try:
            lat, lon = _record_lat_lon(record, lat_field, lon_field)
            lat = float(lat or 0)
            lon = float(lon or 0)
            if not lat or not lon:
                continue
        except (ValueError, TypeError):
            continue

        for ref in reference_locs:
            if haversine(lat, lon, ref["lat"], ref["lon"]) <= distance_meters:
                result.append(record)
                break

    return result


def _record_lat_lon(record: dict, lat_field: str, lon_field: str) -> tuple[object | None, object | None]:
    lat = record.get(lat_field)
    lon = record.get(lon_field)
    if (lat is not None and lon is not None) or "location" not in record:
        return lat, lon

    loc = record.get("location")
    if isinstance(loc, str):
        try:
            loc = json.loads(loc)
        except (json.JSONDecodeError, AttributeError):
            loc = None
    if isinstance(loc, dict):
        lat = loc.get("latitude") or loc.get("lat")
        lon = loc.get("longitude") or loc.get("lon")
        coords = loc.get("coordinates")
        if (lat is None or lon is None) and isinstance(coords, list) and len(coords) >= 2:
            lon = coords[0]
            lat = coords[1]
    return lat, lon
