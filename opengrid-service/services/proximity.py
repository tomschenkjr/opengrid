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

import os
import re
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
    "bus stops":     "highway=bus_stop",
    "train stations":"railway=station",
}


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


async def _fetch_osm_amenity(tag: str) -> list[dict]:
    """Fetch locations from OpenStreetMap via Overpass API using a tag query."""
    key, _, value = tag.partition("=")
    query = (
        f"[out:json][timeout:15];"
        f"(node[{key}={value}]{_CHICAGO_BBOX};"
        f"way[{key}={value}]{_CHICAGO_BBOX};);"
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


async def fetch_reference_locations(reference: str) -> list[dict]:
    """
    Return location dicts {lat, lon, name?} for a named reference type.
    Resolution order:
      1. datasets.yaml proximity aliases (Socrata)
      2. OSM_CONFIGS (known OSM amenity tags)
      3. Street addresses → ArcGIS geocoder
      4. Named businesses / landmarks → OSM name search
    """
    key = reference.lower().strip()

    try:
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
            lat = float(record.get(lat_field) or 0)
            lon = float(record.get(lon_field) or 0)
            if not lat or not lon:
                continue
        except (ValueError, TypeError):
            continue

        for ref in reference_locs:
            if haversine(lat, lon, ref["lat"], ref["lon"]) <= distance_meters:
                result.append(record)
                break

    return result
