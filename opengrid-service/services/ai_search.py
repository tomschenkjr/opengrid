"""
AI-powered natural language search for Chicago open data and MCP providers.

Single Claude Haiku call with full schema context injected — no MCP agentic loop.
Haiku classifies the query AND generates either:
  - A SOQL WHERE clause for Socrata datasets  (fast path: ~1-2s + ~1-2s)
  - A provider/tool call for MCP services     (zone polygon path: ~0.5s + ~2-5s)

Falls back to ArcGIS geocoder for specific place/address/landmark queries.
"""

import asyncio
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx
import yaml
from anthropic import Anthropic

from services.geojson_converter import rows_to_geojson
from services.socrata import query_dataset, count_by, count_rows
from services import geography, proximity, provider_registry, zone_resolver

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


def _build_provider_section() -> str:
    """Build the external providers block for the system prompt, if any are registered."""
    descriptions = provider_registry.describe_all()
    if not descriptions:
        return ""
    return f"""
External providers (for weather, marine, and non-Chicago-data queries):

{descriptions}

ROUTING RULES — use a provider when the query matches these phrases or topics:

Marine/lake queries → noaa-marine
  Triggers: "marine forecast", "lake forecast", "lake conditions", "lake michigan conditions",
  "boating conditions", "sailing conditions", "is it safe to sail", "is it safe to boat",
  "water advisories", "marine advisories", "small craft advisories", "wave advisories",
  "wave height", "waves on the lake", "lake michigan weather", "wind on the lake",
  "waterfront conditions", "nautical conditions", "chicago harbor conditions",
  "going out on the water", "conditions on the water", "buoy readings", "water temperature",
  "lake michigan forecast", "what's the lake like", "how are conditions on the lake",
  "is the lake rough", "lake surf", "lake chop"
  Response (general conditions) — always pass zone_id in args:
    {{"provider_id": "noaa-marine", "tool": "get_nearshore_forecast", "args": {{"zone_id": "LMZ742"}}, "zone_id": "LMZ742", "intent": "analytical"}}
  Response (advisories/alerts specifically):
    {{"provider_id": "noaa-marine", "tool": "get_marine_alerts", "args": {{"zone_id": "LMZ742"}}, "zone_id": "LMZ742", "intent": "analytical"}}

Land weather queries → noaa-weather
  Triggers: "weather forecast", "temperature", "rain forecast", "snow forecast",
  "wind speed", "weather today", "weather this week", "NWS alerts", "weather alerts"
  Response:
    {{"provider_id": "noaa-weather", "tool": "get_forecast", "args": {{"latitude": 41.8781, "longitude": -87.6298}}, "zone_id": "ILZ104", "intent": "analytical"}}

The zone_id determines which NWS zone polygon appears on the map.
For tools requiring lat/lon, default to Chicago center (41.8781, -87.6298).
Mixed Socrata + provider results use a JSON array:
  [{{"dataset_id": "crimes", "soql_where": null, "intent": "display"}}, {{"provider_id": "noaa-marine", "tool": "get_nearshore_forecast", "args": {{}}, "zone_id": "LMZ742", "intent": "analytical"}}]"""


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

    provider_section = _build_provider_section()

    return f"""You are a Chicago open data query translator. Convert natural language questions into SOQL WHERE clauses or external provider calls.

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
  {{"dataset_id": null}}

Classify query intent — include "intent" in every response:
  "analytical" — query seeks an answer, trend, comparison, or insight.
    Signals: question words (where, who, what, when, which, how many, how often), superlatives (most, least, top, worst, best, highest, lowest, fewest).
    Examples: "where do most crimes occur?", "who had the most recent failed food inspection?", "what time do most burglaries happen?", "which ward has the most 311 complaints?", "how many building permits were issued this year?"
  "display" — query asks to show or find data at a location; no specific question to answer.
    Signals: imperatives (show me, find, list, get), location-first phrasing, filter-only queries.
    Examples: "show me crimes", "food inspections near me", "building permits in Logan Square", "crimes in Ward 35 last month"

Add "intent" to every response — single, array, and null dataset:
  {{"dataset_id": "crimes", "soql_where": "primary_type = 'ROBBERY'", "intent": "display"}}
  {{"dataset_id": "crimes", "soql_where": null, "order_by": "date DESC", "intent": "analytical"}}
  [{{"dataset_id": "crimes", "soql_where": null, "intent": "display"}}, {{"dataset_id": "food-inspections", "soql_where": null, "intent": "display"}}]
{provider_section}"""


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


_MARINE_HIGH_ALERTS = frozenset({
    "Special Marine Warning",
    "Gale Warning",
    "Storm Warning",
    "Hurricane Force Wind Warning",
})
_MARINE_MEDIUM_ALERTS = frozenset({"Small Craft Advisory"})


async def _marine_alert_colors(provider: Any, zone_ids: list[str]) -> dict:
    """
    Color overrides from active NWS marine alerts across the given zones. The
    combined shape is colored if a warning/advisory is active in ANY of them.
    Rules unchanged: red for warnings, yellow for Small Craft Advisory.
    """
    events: set[str] = set()
    try:
        raws = await asyncio.gather(
            *[provider.call_tool("get_marine_alerts", {"zone_id": z}) for z in zone_ids],
            return_exceptions=True,
        )
        for raw in raws:
            if isinstance(raw, Exception):
                continue
            data = json.loads(_extract_mcp_text(raw))
            for a in data.get("alerts", []):
                events.add(a.get("event", ""))
        if events & _MARINE_HIGH_ALERTS:
            return {"color": "#AA0000", "fillColor": "#FF4444"}
        if events & _MARINE_MEDIUM_ALERTS:
            return {"color": "#CC8800", "fillColor": "#FFD700"}
    except Exception as e:
        print(f"[smart_search] marine alert check failed for {zone_ids}: {e}")
    return {}


def _extract_mcp_text(mcp_result: Any) -> str:
    """Flatten MCP tool result content into a plain text string."""
    if isinstance(mcp_result, str):
        return mcp_result
    if isinstance(mcp_result, list):
        parts = [item.get("text", "") for item in mcp_result if isinstance(item, dict) and item.get("type") == "text"]
        return "\n".join(parts) if parts else str(mcp_result)
    if isinstance(mcp_result, dict):
        content = mcp_result.get("content", [])
        if isinstance(content, list):
            parts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
            return "\n".join(parts) if parts else str(mcp_result)
    return str(mcp_result)


async def _process_mcp_result(result: dict) -> dict | None:
    """Process a Haiku MCP result → GeoJSON FeatureCollection with NWS zone polygon."""
    provider_id = result.get("provider_id")
    tool_name = result.get("tool")
    args = result.get("args", {})
    zone_id = result.get("zone_id", "")

    provider = provider_registry.get(provider_id)
    if not provider:
        print(f"[smart_search] Unknown provider: {provider_id!r}")
        return None

    # For marine providers the geometry is the COMBINED Chicago shoreline zones
    # (LMZ740/741/742). Alert coloring spans all of them.
    if provider_id == "noaa-marine":
        async def _none():
            return None

        geo_cfg = provider._config.get("geometry", {})
        zones = geo_cfg.get("zones") or ([zone_id] if zone_id else [])

        results = await asyncio.gather(
            provider.call_tool(tool_name, args),
            zone_resolver.get_combined_zone_geojson(zones) if zones else _none(),
            _marine_alert_colors(provider, zones),
            return_exceptions=True,
        )
        mcp_result, zone_geom, alert_display = results
        if isinstance(mcp_result, Exception):
            print(f"[smart_search] MCP call {provider_id}.{tool_name} failed: {mcp_result}")
            return None
        if isinstance(zone_geom, Exception):
            zone_geom = None
        if isinstance(alert_display, Exception):
            alert_display = {}
        zone_label = "+".join(z.upper() for z in zones) if zones else zone_id.upper()
    else:
        try:
            mcp_result = await provider.call_tool(tool_name, args)
        except Exception as e:
            print(f"[smart_search] MCP call {provider_id}.{tool_name} failed: {e}")
            return None
        zone_geom = await zone_resolver.get_zone_geojson(zone_id) if zone_id else None
        alert_display = {}
        zone_label = zone_id.upper()

    if zone_geom is None:
        print(f"[smart_search] No zone geometry for {zone_label!r}, skipping MCP result")
        return None

    content_str = _extract_mcp_text(mcp_result)
    cfg = provider._config
    display = {**cfg.get("display", {}), **alert_display}
    feature_id = f"{provider_id}-{zone_label}"
    display_name = cfg.get("description", provider_id)

    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "id": feature_id,
            "geometry": zone_geom,
            "properties": {
                "zone_id": zone_label,
                "conditions": content_str,
            },
        }],
        "meta": {
            "view": {
                "id": feature_id,
                "displayName": display_name,
                "options": {
                    "rendition": {
                        "icon": "boundary",
                        "color": display.get("color", "#5588CC"),
                        "fillColor": display.get("fillColor", "#AACCEE"),
                        "opacity": display.get("opacity", 50),
                        "size": 8,
                        "borderWidth": 2,
                    }
                },
                "columns": [
                    {"id": "zone_id", "displayName": "Zone", "dataType": "string", "popup": True, "list": True},
                    {"id": "conditions", "displayName": "Conditions", "dataType": "string", "popup": True, "list": False},
                ],
            }
        },
    }


async def _dispatch_result(result: dict, bounds: dict | None, current_location: dict | None) -> dict | None:
    """Route a single Haiku result dict to the Socrata or MCP processor."""
    if result.get("provider_id"):
        return await _process_mcp_result(result)

    dataset_id = result.get("dataset_id")
    if not dataset_id:
        geo = result.get("geography")
        if geo:
            return _build_boundary_layer(geo)
        return None

    return await _process_single_result(result, bounds, current_location)


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

    # Resolved filter state so the frontend filter chiclets can pre-populate.
    # Pass the NL data predicate (not geo/bbox clauses) so a choropleth can match.
    geojson["meta"]["filters"] = _build_filters_meta(ds, geo, "all", result.get("soql_where"))

    return geojson


def _community_area_name(number: int) -> str | None:
    """Reverse lookup: community area number → official name."""
    for name, num in geography.COMMUNITY_AREAS.items():
        if num == number:
            return name
    return None


def _build_filters_meta(ds: dict, geo: dict | None, timeframe: str, soql_where: str | None = None) -> dict:
    """Resolved filter state attached to a layer's meta for the frontend chiclets."""
    ca = None
    if geo and geo.get("type") == "community_area" and geo.get("number"):
        num = geo["number"]
        name = geo.get("name") or _community_area_name(num) or ""
        ca = {"number": num, "name": name.title()}
    return {
        "dataset_id": ds["id"],
        "dataset_name": ds.get("displayName", ds["id"]),
        "community_area": ca,
        "timeframe": timeframe or "all",
        "soql_where": soql_where or None,
        # choropleth is only possible for datasets that carry a community_area column
        "aggregatable": bool((ds.get("geographic_columns") or {}).get("community_area")),
    }


def _timeframe_clause(ds: dict, timeframe: str) -> str | None:
    """Build a SOQL date clause for a timeframe key, or None for 'all'/no date field."""
    if not timeframe or timeframe == "all":
        return None
    date_field = next((c["id"] for c in ds.get("columns", []) if c.get("dataType") == "date"), None)
    if not date_field:
        return None
    now = datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT00:00:00"
    if timeframe == "this-year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return f"{date_field} >= '{start.strftime(fmt)}'"
    if timeframe == "last-year":
        start = now.replace(year=now.year - 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return f"{date_field} >= '{start.strftime(fmt)}' AND {date_field} < '{end.strftime(fmt)}'"
    days = {"last-90-days": 90, "last-60-days": 60, "last-7-days": 7}.get(timeframe)
    if days:
        start = now - timedelta(days=days)
        return f"{date_field} >= '{start.strftime(fmt)}'"
    return None


async def _filtered_one(dataset_id: str, timeframe: str, community_area: int | None,
                        bounds: dict | None) -> dict | None:
    """Build one GeoJSON layer from explicit filter values (no NL parsing)."""
    ds = _find_dataset(dataset_id)
    if not ds:
        return None

    clauses = []
    tf = _timeframe_clause(ds, timeframe)
    if tf:
        clauses.append(tf)

    geo = None
    if community_area:
        geo = {"type": "community_area", "number": community_area,
               "name": _community_area_name(community_area)}
        gc = _build_geo_clause(geo, ds)
        if gc:
            clauses.append(gc)
    elif bounds:
        b = bounds
        clauses.append(
            f"within_box(location, {b['minLat']}, {b['minLon']}, {b['maxLat']}, {b['maxLon']})"
        )

    soql_where = " AND ".join(clauses) if clauses else None
    date_field = next((c["id"] for c in ds.get("columns", []) if c.get("dataType") == "date"), None)

    rows = query_dataset(
        domain=ds["socrata_domain"],
        dataset_id=ds["socrata_dataset_id"],
        where=soql_where,
        limit=500,
        order=f"{date_field} DESC" if date_field else None,
    )

    geojson = rows_to_geojson(
        rows, ds,
        lat_field=ds.get("lat_field", "latitude"),
        lon_field=ds.get("lon_field", "longitude"),
    )

    if geo:
        boundary = _build_boundary_layer(geo)
        if boundary:
            geojson["meta"]["geography_boundary"] = boundary

    geojson["meta"]["filters"] = _build_filters_meta(ds, geo, timeframe or "all")
    return geojson


async def filtered_search(datasets: list[str], timeframe: str = "all",
                          community_area: int | None = None,
                          bounds: dict | None = None) -> dict:
    """Structured (non-NL) search driven by the filter chiclets."""
    import asyncio as _asyncio
    ds_ids = [d for d in (datasets or []) if d]
    if not ds_ids:
        return {"type": "FeatureCollection", "features": [],
                "meta": {"view": {"id": "empty", "displayName": "No data", "columns": []}}}

    layers = list(await _asyncio.gather(
        *[_filtered_one(d, timeframe, community_area, bounds) for d in ds_ids]
    ))
    layers = [l for l in layers if l is not None]
    if not layers:
        return {"type": "FeatureCollection", "features": [],
                "meta": {"view": {"id": "empty", "displayName": "No data", "columns": []}}}
    if len(layers) == 1:
        return layers[0]
    return {"layers": layers}


def _empty_choropleth() -> dict:
    return {"type": "FeatureCollection", "features": [],
            "meta": {"mode": "choropleth",
                     "view": {"id": "choropleth-empty", "displayName": "No data", "columns": []}}}


def _view_where(ds: dict, soql_where: str | None, timeframe: str,
                community_area: int | None, bbox: dict | None) -> str | None:
    """Combined WHERE for a viewport query: data predicate + timeframe + area + bbox."""
    clauses = []
    if soql_where:
        clauses.append(f"({soql_where})")
    tf = _timeframe_clause(ds, timeframe)
    if tf:
        clauses.append(tf)
    if community_area:
        col = (ds.get("geographic_columns") or {}).get("community_area")
        if col:
            clauses.append(f"{col} = '{community_area}'")
    if bbox:
        b = bbox
        clauses.append(
            f"within_box(location, {b['minLat']}, {b['minLon']}, {b['maxLat']}, {b['maxLon']})"
        )
    return " AND ".join(clauses) if clauses else None


def _choropleth_fc(ds: dict, features: list, geo_label: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "mode": "choropleth",
            "view": {
                "id": f"choropleth-{ds['id']}-{geo_label.replace(' ', '-')}",
                "displayName": ds.get("displayName", ds["id"]) + f" by {geo_label}",
                "columns": [
                    {"id": "name", "displayName": geo_label.title(), "dataType": "string", "popup": True, "list": True},
                    {"id": "count", "displayName": "Count", "dataType": "number", "popup": True, "list": True},
                ],
            },
        },
    }


def _ca_features(ds: dict, where: str | None) -> list:
    col = (ds.get("geographic_columns") or {}).get("community_area")
    if not col:
        return []
    geoms = geography.all_community_area_geojson()
    feats = []
    for r in count_by(ds["socrata_domain"], ds["socrata_dataset_id"], col, where):
        try:
            num, cnt = int(float(r["k"])), int(r["n"])
        except (TypeError, ValueError, KeyError):
            continue
        geom = geoms.get(num)
        if not geom:
            continue
        name = (geography.community_area_name(num) or f"Area {num}").title()
        feats.append({"type": "Feature", "id": f"ca-{num}", "geometry": geom,
                      "properties": {"name": name, "count": cnt}})
    return feats


def _tract_features(ds: dict, where: str | None) -> list:
    col = (ds.get("geographic_columns") or {}).get("census_tract")
    if not col:
        return []
    geoms = geography.all_tract_geojson()
    feats = []
    for r in count_by(ds["socrata_domain"], ds["socrata_dataset_id"], col, where):
        k = r.get("k")
        if k is None:
            continue
        key = str(k).strip()
        if not key.strip("0"):
            continue
        key6 = key.zfill(6)
        try:
            cnt = int(r["n"])
        except (TypeError, ValueError, KeyError):
            continue
        geom = geoms.get(key6)
        if not geom:
            continue
        feats.append({"type": "Feature", "id": f"tract-{key6}", "geometry": geom,
                      "properties": {"name": f"Tract {key6}", "count": cnt}})
    return feats


def _points_fc(ds: dict, where: str | None, limit: int = 500) -> dict:
    """Standard point GeoJSON for the current viewport (for points mode)."""
    date_field = next((c["id"] for c in ds.get("columns", []) if c.get("dataType") == "date"), None)
    rows = query_dataset(ds["socrata_domain"], ds["socrata_dataset_id"],
                         where=where, limit=limit,
                         order=f"{date_field} DESC" if date_field else None)
    return rows_to_geojson(rows, ds,
                           lat_field=ds.get("lat_field", "latitude"),
                           lon_field=ds.get("lon_field", "longitude"))


def heat_points(ds: dict, where: str | None, limit: int = 5000) -> list:
    """Lightweight [lat, lon] list for a heatmap layer."""
    rows = query_dataset(ds["socrata_domain"], ds["socrata_dataset_id"], where=where, limit=limit)
    lat_f = ds.get("lat_field", "latitude")
    lon_f = ds.get("lon_field", "longitude")
    pts = []
    for r in rows:
        try:
            pts.append([float(r[lat_f]), float(r[lon_f])])
        except (KeyError, TypeError, ValueError):
            continue
    return pts


async def search_records(dataset: str, timeframe: str = "all", community_area: int | None = None,
                         soql_where: str | None = None, offset: int = 0, limit: int = 200,
                         order: str = "newest") -> dict:
    """
    Paged record list for the results pane (query-wide, not viewport-scoped).
    Returns {total, columns, records} — records are raw property dicts.
    """
    ds = _find_dataset(dataset)
    if not ds:
        return {"total": 0, "columns": [], "records": []}
    where = _view_where(ds, soql_where, timeframe, community_area, None)
    total = count_rows(ds["socrata_domain"], ds["socrata_dataset_id"], where)
    date_field = next((c["id"] for c in ds.get("columns", []) if c.get("dataType") == "date"), None)
    order_clause = None
    if date_field:
        order_clause = f"{date_field} {'ASC' if order == 'oldest' else 'DESC'}"
    rows = query_dataset(
        ds["socrata_domain"], ds["socrata_dataset_id"],
        where=where, limit=min(limit, 200),
        order=order_clause,
        offset=max(offset, 0),
    )
    return {"total": total, "columns": ds.get("columns", []), "records": rows}


async def aggregate_search(dataset_id: str, timeframe: str = "all",
                           community_area: int | None = None,
                           soql_where: str | None = None) -> dict:
    """Community-area choropleth (kept for /map/aggregate; also used by decide_view)."""
    ds = _find_dataset(dataset_id)
    if not ds or not (ds.get("geographic_columns") or {}).get("community_area"):
        return _empty_choropleth()
    where = _view_where(ds, soql_where, timeframe, community_area, None)
    return _choropleth_fc(ds, _ca_features(ds, where), "community area")


async def decide_view(dataset: str, timeframe: str = "all", community_area: int | None = None,
                      soql_where: str | None = None, bbox: dict | None = None,
                      zoom: float = 11) -> dict:
    """
    Pick the map representation for the current viewport:
      count ≤ 500            → points (client keeps the search's markers)
      > 500 and zoom < 12    → community-area choropleth (citywide)
      > 500 and has tract    → census-tract choropleth (viewport)
      else                   → heatmap (viewport, ≤ 5000 points)
    """
    ds = _find_dataset(dataset)
    if not ds:
        return {"mode": "points", "total": 0}

    where_view = _view_where(ds, soql_where, timeframe, community_area, bbox)
    total = count_rows(ds["socrata_domain"], ds["socrata_dataset_id"], where_view)
    if total <= 500:
        return {"mode": "points", "total": total, "data": _points_fc(ds, where_view, 500)}

    gc = ds.get("geographic_columns") or {}
    if zoom < 12 and gc.get("community_area"):
        where_city = _view_where(ds, soql_where, timeframe, community_area, None)
        return {"mode": "choropleth", "geo": "community_area", "total": total,
                "data": _choropleth_fc(ds, _ca_features(ds, where_city), "community area")}

    if gc.get("census_tract"):
        feats = _tract_features(ds, where_view)
        if feats:
            return {"mode": "choropleth", "geo": "tract", "total": total,
                    "data": _choropleth_fc(ds, feats, "census tract")}

    return {"mode": "heatmap", "total": total,
            "points": heat_points(ds, where_view, 5000)}


async def smart_search(query: str, bounds: dict | None = None, current_location: dict | None = None) -> dict:
    """Translate natural language → SOQL or MCP call → GeoJSON(s), or fall back to POI geocoding."""
    import asyncio as _asyncio
    result = await nl_to_soql(query)
    print(f"[smart_search] query={query!r} haiku={result}")

    # Multi-result: Haiku returned a list (datasets and/or providers)
    if isinstance(result, list):
        intent = "analytical" if any(
            r.get("intent") == "analytical" for r in result if isinstance(r, dict)
        ) else "display"
        layers = list(await _asyncio.gather(
            *[_dispatch_result(r, bounds, current_location) for r in result if isinstance(r, dict)]
        ))
        layers = [l for l in layers if l is not None]
        if layers:
            return {"layers": layers, "intent": intent}
        return await geocode_poi(query)

    # Single result — Socrata dataset, MCP provider, geography boundary, or POI
    intent = result.get("intent", "display") if isinstance(result, dict) else "display"
    layer = await _dispatch_result(result, bounds, current_location)
    if layer is not None:
        layer["intent"] = intent
        return layer
    return await geocode_poi(query)
