"""
AI-powered natural language search for Chicago open data.

Single Claude Haiku call with full schema context injected — no MCP agentic loop.
Haiku classifies the query AND generates the SOQL WHERE clause in one shot:
  1 Haiku call (~1-2s) + 1 Socrata query (~1-2s) = well under the 60s timeout.

Falls back to ArcGIS geocoder for place/address/landmark queries.
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
import yaml
from anthropic import Anthropic

from services.geojson_converter import rows_to_geojson
from services.socrata import query_dataset
from services import geography, proximity

client = Anthropic()

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "datasets.yaml"
_datasets: list[dict] = []
_crime_types: list[str] = []

# Stable enum values hardcoded — these don't change in the source data
_FOOD_RESULTS = "Pass | Pass w/ Conditions | Fail | No Entry | Out of Business"
_FOOD_RISK = "Risk 1 (High) | Risk 2 (Medium) | Risk 3 (Low)"
_311_STATUS = "Open | Closed | Open - Dup | Closed - Dup"


def _load_datasets() -> list[dict]:
    global _datasets
    if not _datasets:
        with open(_CONFIG_PATH) as f:
            _datasets = yaml.safe_load(f).get("datasets", [])
    return _datasets


def _find_dataset(dataset_id: str) -> dict | None:
    return next((d for d in _load_datasets() if d["id"] == dataset_id), None)


async def _fetch_crime_types() -> list[str]:
    """Fetch distinct primary_type values from Crimes at startup."""
    try:
        app_token = os.getenv("SOCRATA_APP_TOKEN", "").strip() or None
        headers = {"User-Agent": "opengrid-service/1.0"}
        if app_token:
            headers["X-App-Token"] = app_token
        params = {"$select": "primary_type", "$group": "primary_type", "$limit": 50}
        async with httpx.AsyncClient(headers=headers, timeout=15) as http:
            r = await http.get(
                "https://data.cityofchicago.org/resource/ijzp-q8t2.json",
                params=params,
            )
            r.raise_for_status()
            return sorted({row["primary_type"] for row in r.json() if "primary_type" in row})
    except Exception:
        return [
            "THEFT", "BATTERY", "CRIMINAL DAMAGE", "ASSAULT", "DECEPTIVE PRACTICE",
            "ROBBERY", "OTHER OFFENSE", "NARCOTICS", "BURGLARY", "MOTOR VEHICLE THEFT",
            "WEAPONS VIOLATION", "CRIMINAL TRESPASS", "HOMICIDE", "ARSON",
            "KIDNAPPING", "STALKING", "HUMAN TRAFFICKING",
        ]


def _date_context() -> dict:
    now = datetime.now(timezone.utc)
    first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if first_this.month == 1:
        first_last = first_this.replace(year=first_this.year - 1, month=12)
    else:
        first_last = first_this.replace(month=first_this.month - 1)
    fmt = "%Y-%m-%dT00:00:00"
    return {
        "today": now.strftime("%Y-%m-%d"),
        "first_this_month": first_this.strftime(fmt),
        "first_last_month": first_last.strftime(fmt),
        "this_year": f"{now.year}-01-01T00:00:00",
        "seven_days_ago": (now - timedelta(days=7)).strftime(fmt),
        "thirty_days_ago": (now - timedelta(days=30)).strftime(fmt),
    }


def _build_system_prompt() -> str:
    dates = _date_context()
    datasets = _load_datasets()

    # Only queryable datasets go into the DATASET blocks shown to Haiku
    queryable = [ds for ds in datasets if not ds.get("proximity_only")]

    blocks = []
    for ds in queryable:
        cols = ds.get("columns", [])
        date_field = next((c["id"] for c in cols if c.get("dataType") == "date"), None)

        col_lines = []
        for col in cols:
            line = f"  - {col['id']} ({col['dataType']}): {col['displayName']}"
            if ds["id"] == "crimes" and col["id"] == "primary_type" and _crime_types:
                line += f"\n    Known values: {', '.join(_crime_types)}"
            elif ds["id"] == "food-inspections" and col["id"] == "results":
                line += f"\n    Values: {_FOOD_RESULTS}"
            elif ds["id"] == "food-inspections" and col["id"] == "risk":
                line += f"\n    Values: {_FOOD_RISK}"
            elif ds["id"] == "311-service-requests" and col["id"] == "status":
                line += f"\n    Values: {_311_STATUS}"
            col_lines.append(line)

        blocks.append(
            f'DATASET: {ds["displayName"]} (id: "{ds["id"]}")\n'
            f"Date field: {date_field or 'none'}\n"
            f"Columns:\n" + "\n".join(col_lines)
        )

    # Build proximity reference list from all datasets (including proximity_only)
    dataset_aliases = []
    for ds in datasets:
        prox = ds.get("proximity") or {}
        dataset_aliases.extend(prox.get("aliases", []))

    osm_refs = (
        "libraries, parks, gas stations, coffee shops, cafes, hospitals, "
        "pharmacies, grocery stores, bars, restaurants, fast food, "
        "transit stops, bus stops, train stations"
    )

    geo_section = geography.community_area_list_for_prompt()

    return f"""You are a Chicago open data query translator. Convert natural language questions into SOQL WHERE clauses.

Today: {dates['today']}

{chr(10).join(chr(10) + b for b in blocks)}

Date substitution table (use exact strings below):
  "last month"   → date_field >= '{dates['first_last_month']}' AND date_field < '{dates['first_this_month']}'
  "this year"    → date_field >= '{dates['this_year']}'
  "last week"    → date_field >= '{dates['seven_days_ago']}'
  "last 30 days" → date_field >= '{dates['thirty_days_ago']}'
Replace "date_field" with the actual date column name for the chosen dataset.

Chicago community areas (name=number):
{geo_section}

Rules:
- Match colloquial terms to exact field values (e.g. "robbed" → primary_type = 'ROBBERY')
- String comparisons are case-sensitive; crime primary_type values are ALL CAPS
- For partial name matches: dba_name LIKE '%STARBUCKS%'
- Omit soql_where if no meaningful filter can be constructed
- For geographic areas (neighborhoods, wards, community areas, ZIP codes), add a "geography" field

For proximity queries ("within X of Y", "near Y", "close to Y", "around Y"):
Add a "proximity" field with the reference type and distance in meters.
  {{"reference": "schools", "distance_meters": 305}}
  {{"reference": "food inspections", "distance_meters": 400}}
  {{"reference": "gas stations", "distance_meters": 100}}
  {{"reference": "900 W Washington Blvd", "distance_meters": 400}}
  {{"reference": "Starbucks", "distance_meters": 200}}

Distance conversions:
  1 foot = 0.3048 meters | 1 block ≈ 100 meters | 1/4 mile = 402m | 1 mile = 1609m
  "nearby" / "near" / "close to" / "around" → use 400 meters as default

Reference types — use the exact string shown:
  Dataset references: {', '.join(dataset_aliases)}
  OSM references: {osm_refs}
  User's current location: use "current location" exactly when the user says "near me", "around me", "nearby", "near here", "at my house", "at my home", "where I live", "my location", "in my neighborhood", or any phrase meaning the user's own position
  Street addresses: use the address exactly as given (e.g. "900 W Washington Blvd")
  Named businesses/landmarks: use the exact name (e.g. "Starbucks", "United Center")

Respond with JSON only — no explanation or markdown.

Single dataset:
  {{"dataset_id": "crimes", "soql_where": "primary_type = 'ROBBERY' AND date >= '2026-05-01T00:00:00'", "order_by": "date DESC"}}
  {{"dataset_id": "crimes", "soql_where": "date >= '2026-05-01T00:00:00'", "geography": {{"type": "community_area", "name": "Logan Square", "number": 22}}}}
  {{"dataset_id": "crimes", "soql_where": "primary_type = 'ROBBERY'", "proximity": {{"reference": "schools", "distance_meters": 305}}}}
  {{"dataset_id": "311-service-requests", "soql_where": "sr_type LIKE '%Graffiti%'", "geography": {{"type": "ward", "number": 35}}}}
  {{"dataset_id": "crimes", "soql_where": null, "proximity": {{"reference": "current location", "distance_meters": 400}}}}

Multiple datasets — when the query clearly asks to show more than one dataset at once, respond with a JSON array (max 2 items):
  [{{"dataset_id": "crimes", "soql_where": null}}, {{"dataset_id": "food-inspections", "soql_where": "results = 'Fail'"}}]
  [{{"dataset_id": "crimes", "soql_where": "primary_type = 'ROBBERY'"}}, {{"dataset_id": "building-permits", "soql_where": null}}]

If the query names only a Chicago neighborhood, community area, or ward with no data intent (e.g. "Logan Square", "the Loop", "Ward 35"), include its geography so the boundary can be shown:
  {{"dataset_id": null, "geography": {{"type": "community_area", "name": "Logan Square", "number": 22}}}}
  {{"dataset_id": null, "geography": {{"type": "ward", "number": 35}}}}

If the query is about a specific place, address, business, or landmark (not a Chicago neighborhood), respond:
  {{"dataset_id": null}}"""


async def initialize():
    """Called at service startup: fetch dynamic values and warm the prompt."""
    global _crime_types
    _crime_types = await _fetch_crime_types()


async def nl_to_soql(query: str) -> dict:
    """Single Haiku call → {dataset_id, soql_where, order_by} or {dataset_id: None}."""
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": query}],
    )
    text = resp.content[0].text.strip()

    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if m:
            text = m.group(1)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        return parsed if isinstance(parsed, dict) else {"dataset_id": None}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]+\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {"dataset_id": None}


async def geocode_poi(query: str) -> dict:
    """ArcGIS geocoder → OpenGrid GeoJSON FeatureCollection."""
    params = {
        "text": f"{query}, Chicago, IL",
        "bbox": "-88.02864,41.56614,-87.30011,42.06663",
        "f": "json",
        "maxLocations": 10,
    }
    async with httpx.AsyncClient(timeout=10) as http:
        r = await http.get(
            "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/find",
            params=params,
        )
        r.raise_for_status()
        data = r.json()

    features = []
    for loc in data.get("locations", []):
        geom = loc.get("feature", {}).get("geometry", {})
        lon, lat = geom.get("x"), geom.get("y")
        if lon is None or lat is None:
            continue
        features.append({
            "type": "Feature",
            "id": loc.get("name"),
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"name": loc.get("name"), "score": loc.get("score")},
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "view": {
                "id": "places",
                "displayName": "Places",
                "options": {
                    "rendition": {"icon": "default", "color": "#006600",
                                  "fillColor": "#66AA66", "opacity": 85, "size": 8}
                },
                "columns": [
                    {"id": "name", "displayName": "Name", "dataType": "string", "popup": True, "list": True},
                    {"id": "score", "displayName": "Match Score", "dataType": "number", "popup": True, "list": True},
                ],
            }
        },
    }


def _build_geo_clause(geo: dict, ds: dict) -> str | None:
    """
    Convert a geography intent from Haiku into a SOQL clause.
    Uses a column filter when the dataset has the right column,
    falls back to within_box() using the boundary bounding box to keep URLs short.
    """
    if not geo:
        return None

    geo_type = geo.get("type")
    geo_cols = ds.get("geographic_columns", {})

    if geo_type == "community_area":
        number = geo.get("number")
        name = geo.get("name", "")
        if not number and name:
            number, _ = geography.resolve_community_area(name)
        if not number:
            return None
        col = geo_cols.get("community_area")
        if col:
            return f"{col} = '{number}'"
        bbox = geography.get_community_area_bbox(number)
        if bbox:
            return (f"within_box(location, {bbox['minLat']}, {bbox['minLon']},"
                    f" {bbox['maxLat']}, {bbox['maxLon']})")
        return None

    if geo_type == "ward":
        number = geo.get("number")
        if not number:
            return None
        col = geo_cols.get("ward")
        if col:
            return f"{col} = {number}"
        bbox = geography.get_ward_bbox(number)
        if bbox:
            return (f"within_box(location, {bbox['minLat']}, {bbox['minLon']},"
                    f" {bbox['maxLat']}, {bbox['maxLon']})")
        return None

    if geo_type == "zip":
        code = geo.get("code")
        if not code:
            return None
        zip_col = geo_cols.get("zip")
        if zip_col:
            return f"{zip_col} = {code}"
        return None  # no ZIP polygon boundary data available

    if geo_type == "police_district":
        number = geo.get("number")
        if not number:
            return None
        col = geo_cols.get("police_district")
        if col:
            return f"{col} = {number}"
        return None

    return None


def _format_distance(meters: float) -> str:
    miles = meters / 1609.34
    if miles >= 1.0:
        n = round(miles, 1)
        return f"{n:g} mile{'s' if n != 1.0 else ''}"
    if 350 <= meters <= 450:
        return "¼ mile"
    if 750 <= meters <= 850:
        return "½ mile"
    if 1150 <= meters <= 1300:
        return "¾ mile"
    feet = meters * 3.28084
    return f"{feet:,.0f} ft"


def _build_reference_layer(locs: list[dict], reference: str) -> dict:
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [loc["lon"], loc["lat"]]},
            "properties": {"name": loc.get("name", reference)},
        }
        for loc in locs
    ]
    label = reference.title()
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "view": {
                "id": f"proximity-{reference.lower().replace(' ', '-')}",
                "displayName": f"{label} (search anchor)",
                "options": {
                    "rendition": {
                        "icon": "default",
                        "color": "#006600",
                        "fillColor": "#66AA66",
                        "opacity": 70,
                        "size": 5,
                    }
                },
                "columns": [
                    {"id": "name", "displayName": "Name", "dataType": "string",
                     "popup": True, "list": True},
                ],
            }
        },
    }


def _build_boundary_layer(geo: dict) -> dict | None:
    """
    Build a GeoJSON FeatureCollection for a community-area or ward boundary polygon.
    Returns None if the geometry isn't cached yet.
    """
    geo_type = geo.get("type")
    geom = None
    display_name = ""
    boundary_id = ""

    if geo_type == "community_area":
        number = geo.get("number")
        name = geo.get("name", "")
        if not number:
            return None
        geom = geography.get_community_area_geojson(number)
        display_name = name.title() if name else f"Community Area {number}"
        boundary_id = f"boundary-community-{number}"

    elif geo_type == "ward":
        number = geo.get("number")
        if not number:
            return None
        geom = geography.get_ward_geojson(number)
        display_name = f"Ward {number}"
        boundary_id = f"boundary-ward-{number}"

    if not geom:
        return None

    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": geom,
            "properties": {"name": display_name},
        }],
        "meta": {
            "view": {
                "id": boundary_id,
                "displayName": display_name,
                "options": {
                    "rendition": {
                        "icon": "boundary",
                        "color": "#0066CC",
                        "fillColor": "#0066CC",
                        "opacity": 90,
                        "size": 8,
                        "borderWidth": 3,
                    }
                },
                "columns": [
                    {"id": "name", "displayName": "Name", "dataType": "string",
                     "popup": True, "list": True},
                ],
            }
        },
    }


async def _process_single_result(result: dict, bounds: dict | None, current_location: dict | None = None) -> dict | None:
    """Process one Haiku result dict → GeoJSON FeatureCollection, or None on no match."""
    dataset_id = result.get("dataset_id")
    if not dataset_id:
        return None

    ds = _find_dataset(dataset_id)
    if not ds:
        return None

    soql_where = result.get("soql_where") or ""

    geo_clause = _build_geo_clause(result.get("geography"), ds)
    if geo_clause:
        soql_where = f"({soql_where}) AND {geo_clause}" if soql_where else geo_clause

    prox = result.get("proximity")

    # If the caller supplied GPS coordinates but Haiku omitted a proximity field,
    # default to filtering within 400 m of the user's position rather than falling
    # back to the broad viewport filter.
    if current_location and not prox:
        prox = {"reference": "current location", "distance_meters": 400}

    # For "current location" proximity, push the spatial filter into SoQL via
    # within_circle() so Socrata does the work — no row-count cap, no Python loop.
    _using_circle = False
    if current_location and prox and prox.get("reference", "").lower().strip() == "current location":
        radius_m = float(prox.get("distance_meters", 400))
        circle_clause = (
            f"within_circle(location, {current_location['lat']}, "
            f"{current_location['lon']}, {radius_m})"
        )
        soql_where = f"({soql_where}) AND {circle_clause}" if soql_where else circle_clause
        _using_circle = True

    limit = 500 if _using_circle else (1000 if prox else 500)

    has_geo_context = bool(result.get("geography") or prox)
    if bounds and not has_geo_context:
        b = bounds
        viewport_clause = (
            f"within_box(location, {b['minLat']}, {b['minLon']}, {b['maxLat']}, {b['maxLon']})"
        )
        soql_where = f"({soql_where}) AND {viewport_clause}" if soql_where else viewport_clause

    if prox and not soql_where:
        cols = ds.get("columns", [])
        date_field = next((c["id"] for c in cols if c.get("dataType") == "date"), None)
        if date_field:
            ninety_days_ago = (
                datetime.now(timezone.utc) - timedelta(days=90)
            ).strftime("%Y-%m-%dT00:00:00")
            soql_where = f"{date_field} >= '{ninety_days_ago}'"

    rows = query_dataset(
        domain=ds["socrata_domain"],
        dataset_id=ds["socrata_dataset_id"],
        where=soql_where or None,
        limit=limit,
        order=result.get("order_by"),
    )

    proximity_meta = None
    if prox and rows:
        print(f"[smart_search] proximity reference={prox['reference']!r} distance={prox.get('distance_meters')}m")
        if prox["reference"].lower().strip() == "current location":
            if current_location:
                ref_locs = [{"lat": current_location["lat"], "lon": current_location["lon"], "name": "Your location"}]
            else:
                ref_locs = []
        else:
            ref_locs = await proximity.fetch_reference_locations(prox["reference"])
        print(f"[smart_search] ref_locs count={len(ref_locs)}")
        if ref_locs:
            distance_m = float(prox.get("distance_meters", 400))
            rows = proximity.filter_by_proximity(
                rows,
                lat_field=ds.get("lat_field", "latitude"),
                lon_field=ds.get("lon_field", "longitude"),
                reference_locs=ref_locs,
                distance_meters=distance_m,
            )
            label = f"within {_format_distance(distance_m)} of {prox['reference']}"
            if not result.get("soql_where"):
                cols = ds.get("columns", [])
                if next((c for c in cols if c.get("dataType") == "date"), None):
                    label += " (last 90 days)"
            proximity_meta = {
                "label": label,
                "distance_meters": distance_m,
                "layer": _build_reference_layer(ref_locs, prox["reference"]),
            }

    geojson = rows_to_geojson(
        rows,
        ds,
        lat_field=ds.get("lat_field", "latitude"),
        lon_field=ds.get("lon_field", "longitude"),
    )
    if proximity_meta:
        geojson["meta"]["proximity"] = proximity_meta

    # Attach a boundary polygon layer when the query targeted a specific geography
    geo = result.get("geography")
    if geo:
        boundary = _build_boundary_layer(geo)
        if boundary:
            geojson["meta"]["geography_boundary"] = boundary

    return geojson


async def smart_search(query: str, bounds: dict | None = None, current_location: dict | None = None) -> dict:
    """Translate natural language → SOQL → GeoJSON(s), or fall back to POI geocoding."""
    import asyncio as _asyncio
    result = await nl_to_soql(query)
    print(f"[smart_search] query={query!r} haiku={result}")

    # Multi-dataset: Haiku returned a list — process each in parallel
    if isinstance(result, list):
        layers = list(await _asyncio.gather(
            *[_process_single_result(r, bounds, current_location) for r in result if isinstance(r, dict)]
        ))
        layers = [l for l in layers if l is not None]
        if layers:
            return {"layers": layers}
        return await geocode_poi(query)

    # Single dataset
    dataset_id = result.get("dataset_id")
    if not dataset_id:
        # Haiku identified a named geography with no data intent — return its boundary
        geo = result.get("geography")
        if geo:
            boundary = _build_boundary_layer(geo)
            if boundary:
                return boundary
        return await geocode_poi(query)

    layer = await _process_single_result(result, bounds, current_location)
    if layer is None:
        return await geocode_poi(query)
    return layer
