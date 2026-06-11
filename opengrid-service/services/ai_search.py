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
from zoneinfo import ZoneInfo

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
_MARINE_PROVIDER_ID = "chicago-marine-knowledge"
_LEGACY_MARINE_PROVIDER_ID = "noaa-marine"
_CHICAGO_TZ = ZoneInfo("America/Chicago")

# Stable enum values hardcoded — these don't change in the source data
_FOOD_RESULTS = "Pass | Pass w/ Conditions | Fail | No Entry | Out of Business"
_FOOD_RISK = "Risk 1 (High) | Risk 2 (Medium) | Risk 3 (Low)"
_311_STATUS = "Open | Closed | Open - Dup | Closed - Dup"
_SCHOOL_PRIMARY_CATEGORY_LABELS = {
    "ES": "Elementary School",
    "HS": "High School",
    "MS": "Middle School",
}


def _load_datasets() -> list[dict]:
    global _datasets
    if not _datasets:
        with open(_CONFIG_PATH) as f:
            _datasets = yaml.safe_load(f).get("datasets", [])
    return _datasets


def _find_dataset(dataset_id: str) -> dict | None:
    return next((d for d in _load_datasets() if d["id"] == dataset_id), None)


def _dataset_is_spatial(ds: dict) -> bool:
    return ds.get("spatial", True) is not False


_DATA_QUERY_TERMS = re.compile(
    r"\b(crime|crimes|311|service requests?|permits?|licenses?|inspections?|"
    r"violations?|arrests?|towed vehicles?|traffic crashes?|crashes?)\b",
    re.I,
)

_PERSISTENT_SEARCH: list[dict] = [
    {
        "id": "schools",
        "display": "CPS Schools",
        "color": "#4D7C0F",
        "aliases": ["schools", "school", "cps schools", "public schools", "elementary schools", "high schools"],
    },
    {
        "id": "libraries",
        "display": "Libraries",
        "color": "#0f766e",
        "aliases": ["libraries", "library", "chicago public libraries"],
    },
    {
        "id": "police-stations",
        "display": "Police Stations",
        "color": "#1d4ed8",
        "aliases": ["police stations", "police station", "police districts", "police headquarters"],
    },
    {
        "id": "fire-stations",
        "display": "Fire Stations",
        "color": "#dc2626",
        "aliases": ["fire stations", "fire station", "firehouses", "fire houses"],
    },
    {
        "id": "speed-cameras",
        "display": "Speed Cameras",
        "color": "#b45309",
        "aliases": ["speed cameras", "speed camera", "speed camera locations"],
    },
    {
        "id": "bike-racks",
        "display": "Bike Racks",
        "color": "#16a34a",
        "aliases": ["bike racks", "bike rack", "bicycle racks", "bicycle rack"],
    },
    {
        "id": "bus-stops",
        "display": "CTA Bus Stops",
        "color": "#1e88e5",
        "aliases": ["bus stops", "bus stop", "cta bus stops", "cta bus stop", "bus stations"],
    },
    {
        "id": "cta-stations",
        "display": "CTA Stations",
        "color": "#0f6fbf",
        "aliases": ["cta stations", "cta station", "cta train stations", "l stations", "el stations", "train stations"],
    },
    {
        "id": "metra-stations",
        "display": "Metra Stations",
        "color": "#7b2433",
        "aliases": ["metra stations", "metra station", "metra stops", "commuter rail stations"],
    },
    {
        "id": "divvy-stations",
        "display": "Divvy Stations",
        "color": "#40b4e5",
        "aliases": ["divvy stations", "divvy station", "divvy bike stations", "bike share stations"],
    },
    {
        "id": "open-air-sensors",
        "display": "Open Air Chicago Sensors",
        "color": "#22c55e",
        "aliases": ["open air sensors", "open air chicago sensors", "air quality sensors", "air sensors"],
    },
    {
        "id": "beach-water-quality",
        "display": "Beach Water Quality Tests",
        "color": "#2e7d32",
        "aliases": ["beach water quality", "beach dna", "beach water tests", "beaches"],
    },
    {
        "id": "beach-weather",
        "display": "Beach Weather Stations",
        "color": "#1565C0",
        "aliases": ["beach weather stations", "beach weather sensors"],
    },
    {
        "id": "dever-crib",
        "display": "Dever Crib Weather Station",
        "color": "#1565C0",
        "aliases": ["dever crib", "dever crib weather station", "crib weather station", "william e dever crib"],
    },
]


def _alias_in_query(query: str, alias: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", query, re.I) is not None


def _persistent_spec_for_query(query: str) -> dict | None:
    q = query.lower().strip()
    for spec in _PERSISTENT_SEARCH:
        for alias in sorted(spec["aliases"], key=len, reverse=True):
            if not _alias_in_query(q, alias):
                continue
            # Let normal dataset/proximity searches handle "crimes near bus stops"
            # and similar mixed data queries.
            if _DATA_QUERY_TERMS.search(q) and not q.startswith(("show", "find", "list", "get")):
                return None
            if _DATA_QUERY_TERMS.search(q) and " near " in q:
                return None
            return spec
    return None


def _bbox_filter(items: list[dict], bounds: dict | None) -> list[dict]:
    if not bounds:
        return items
    return [
        item for item in items
        if bounds["minLat"] <= item["lat"] <= bounds["maxLat"]
        and bounds["minLon"] <= item["lon"] <= bounds["maxLon"]
    ]


def _near_filter(items: list[dict], current_location: dict | None, query: str) -> list[dict]:
    if not current_location or not re.search(r"\b(near me|nearby|around me|close to me|my location|current location)\b", query, re.I):
        return items
    return [
        item for item in items
        if proximity.haversine(
            float(current_location["lat"]), float(current_location["lon"]),
            float(item["lat"]), float(item["lon"]),
        ) <= 400
    ]


def _detail_text(details) -> str:
    if not details:
        return ""
    if isinstance(details, list):
        parts = []
        for item in details:
            label = item.get("label")
            value = item.get("value")
            if label and value not in (None, ""):
                parts.append(f"{label}: {value}")
        return " | ".join(parts)
    return str(details)


def _persistent_feature(item: dict, spec: dict) -> dict:
    name = (
        item.get("title") or item.get("long_name") or item.get("station_name")
        or item.get("stop_name") or item.get("name") or item.get("beach")
        or item.get("sensor_name") or spec["display"]
    )
    subtitle = item.get("subtitle") or item.get("address") or item.get("short_name") or ""
    details = item.get("details")
    if details is None:
        details = []
        for key, label in [
            ("primary_category", "Category"),
            ("school_type", "School Type"),
            ("lines", "Lines"),
            ("ada", "Accessible"),
            ("capacity", "Capacity"),
            ("vehicle_types_available_label", "Available Vehicles"),
            ("num_docks_available", "Docks Available"),
            ("time_label", "Reading Time"),
            ("dna_reading_mean", "DNA Reading Mean"),
            ("timestamp", "Timestamp"),
            ("station_name", "Station"),
            ("observed", "Observed"),
            ("air_temp_f", "Air Temp F"),
            ("wind_avg_ms", "Wind Avg m/s"),
        ]:
            if key in item and item.get(key) not in (None, ""):
                details.append({"label": label, "value": item.get(key)})
    return {
        "type": "Feature",
        "id": item.get("id") or item.get("school_id") or item.get("stop_id") or item.get("station_id") or name,
        "geometry": {"type": "Point", "coordinates": [float(item["lon"]), float(item["lat"])]},
        "properties": {
            "name": name,
            "type": item.get("kind_label") or spec["display"],
            "subtitle": subtitle,
            "details": _detail_text(details),
        },
    }


def _persistent_fc(items: list[dict], spec: dict) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [_persistent_feature(item, spec) for item in items],
        "meta": {
            "view": {
                "id": f"persistent-{spec['id']}",
                "displayName": spec["display"],
                "options": {
                    "rendition": {
                        "icon": "default",
                        "color": spec["color"],
                        "fillColor": spec["color"],
                        "opacity": 85,
                        "size": 6,
                    }
                },
                "columns": [
                    {"id": "name", "displayName": "Name", "dataType": "string", "popup": True, "list": True},
                    {"id": "type", "displayName": "Type", "dataType": "string", "popup": True, "list": True},
                    {"id": "subtitle", "displayName": "Location", "dataType": "string", "popup": True, "list": True},
                    {"id": "details", "displayName": "Details", "dataType": "string", "popup": True, "list": True},
                ],
            }
        },
    }


async def _persistent_items(spec: dict, bounds: dict | None) -> list[dict]:
    from routers import stations as station_data

    sid = spec["id"]
    if sid == "schools":
        items = await station_data._fetch_schools()
    elif sid in {"libraries", "police-stations", "fire-stations", "speed-cameras", "bike-racks"}:
        items = await station_data._fetch_facilities(sid)
    elif sid == "bus-stops":
        items = await station_data._fetch_bus_stops()
    elif sid == "cta-stations":
        items = await station_data.cta_trains()
    elif sid == "metra-stations":
        data = await station_data._parse_metra_data()
        items = data.get("stops", [])
    elif sid == "divvy-stations":
        items = await station_data._fetch_divvy_stations()
    elif sid == "open-air-sensors":
        items = await station_data._fetch_open_air_latest()
        items = [
            {**item, "title": f"{item.get('sensor_name') or 'Open Air'} Open Air Chicago Sensor"}
            for item in items
        ]
    elif sid == "beach-water-quality":
        raw = await station_data.beach_dna()
        items = [
            {
                **item,
                "lat": item.get("latitude"),
                "lon": item.get("longitude"),
                "title": f"{item.get('beach', 'Beach')} Water Quality Tests",
            }
            for item in raw
        ]
    elif sid == "beach-weather":
        raw = await station_data.beach_weather()
        items = [
            {
                **item,
                "lat": item.get("latitude"),
                "lon": item.get("longitude"),
                "title": f"{item.get('station_name', 'Beach')} Weather Station",
            }
            for item in raw
        ]
    elif sid == "dever-crib":
        try:
            obs = await station_data.dever_crib_conditions()
        except Exception:
            obs = {}
        items = [{
            **obs,
            "id": "dever-crib",
            "title": "Dever Crib Weather Station",
            "subtitle": "NOAA GLERL Chicago Station",
            "lat": 41.916389,
            "lon": -87.573056,
        }]
    else:
        items = []

    valid = []
    for item in items:
        try:
            lat = float(item.get("lat"))
            lon = float(item.get("lon"))
        except (TypeError, ValueError):
            continue
        if lat and lon:
            valid.append({**item, "lat": lat, "lon": lon})
    return _bbox_filter(valid, bounds)


async def _persistent_object_search(query: str, bounds: dict | None, current_location: dict | None) -> dict | None:
    spec = _persistent_spec_for_query(query)
    if not spec:
        return None
    try:
        items = await _persistent_items(spec, bounds)
        items = _near_filter(items, current_location, query)
        return _persistent_fc(items, spec)
    except Exception as e:
        print(f"[persistent_search] {spec['id']} unavailable: {e}")
        return None


def _normalize_rows_for_dataset(rows: list[dict], ds: dict) -> list[dict]:
    if ds.get("id") != "schools":
        return rows
    normalized = []
    for row in rows:
        copy = dict(row)
        cat = str(copy.get("primary_category") or "").strip().upper()
        if cat in _SCHOOL_PRIMARY_CATEGORY_LABELS:
            copy["primary_category"] = _SCHOOL_PRIMARY_CATEGORY_LABELS[cat]
        normalized.append(copy)
    return normalized


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

Marine/lake queries → chicago-marine-knowledge
  Triggers: "marine forecast", "lake forecast", "lake conditions", "lake michigan conditions",
  "boating conditions", "sailing conditions", "is it safe to sail", "is it safe to boat",
  "water advisories", "marine advisories", "small craft advisories", "wave advisories",
  "wave height", "waves on the lake", "lake michigan weather", "wind on the lake",
  "waterfront conditions", "nautical conditions", "chicago harbor conditions",
  "going out on the water", "conditions on the water", "buoy readings", "water temperature",
  "lake michigan forecast", "what's the lake like", "how are conditions on the lake",
  "is the lake rough", "lake surf", "lake chop"
  Response (general lake/sailing conditions, including advisories — use Chicago Marine Knowledge, which folds NOAA marine alerts into its response):
    {{"provider_id": "chicago-marine-knowledge", "tool": "get_sailing_conditions", "args": {{"area_id": "chicago_lakefront", "response_profile": "compact_llm"}}, "zone_id": "LMZ742", "intent": "analytical"}}
  Response (conditions at a specific lakefront place — harbor or beach):
    {{"provider_id": "chicago-marine-knowledge", "tool": "get_marine_conditions", "args": {{"place_id": "monroe_harbor", "response_profile": "compact_llm"}}, "zone_id": "LMZ742", "intent": "analytical"}}
  Marine args use area_id ("chicago_lakefront") or place_id (monroe_harbor, oak_street_beach, foster_beach, 63rd_street_beach) — never zone_id.
  Always include "response_profile": "compact_llm" in marine args.
  zone_id stays at the top level only (it selects the map polygon).

Land weather queries → noaa-weather
  Triggers: "weather forecast", "temperature", "rain forecast", "snow forecast",
  "wind speed", "weather today", "weather this week", "NWS alerts", "weather alerts"
  Response:
    {{"provider_id": "noaa-weather", "tool": "get_forecast", "args": {{"latitude": 41.8781, "longitude": -87.6298}}, "zone_id": "ILZ104", "intent": "analytical"}}

The zone_id determines which NWS zone polygon appears on the map.
For tools requiring lat/lon, default to Chicago center (41.8781, -87.6298).
Mixed Socrata + provider results use a JSON array:
  [{{"dataset_id": "crimes", "soql_where": null, "intent": "display"}}, {{"provider_id": "chicago-marine-knowledge", "tool": "get_sailing_conditions", "args": {{"area_id": "chicago_lakefront", "response_profile": "compact_llm"}}, "zone_id": "LMZ742", "intent": "analytical"}}]"""


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
            elif ds["id"] == "schools" and col["id"] == "primary_category":
                line += "\n    Values: ES = Elementary School, HS = High School, MS = Middle School. Use ES/HS/MS in SOQL, but display the long label to users."
            elif ds["id"] == "schools" and col["id"] == "culture_climate_rating":
                line += "\n    Values include: Well Organized | Organized | Moderately Organized | Partially Organized | Not Yet Organized | Not Enough Data. For a quoted value like \"organized\", use culture_climate_rating = 'Organized'."
            elif ds["id"] == "schools" and col["id"] in {"student_growth_rating", "student_attainment_rating"}:
                line += "\n    Values include: FAR ABOVE EXPECTATIONS | ABOVE EXPECTATIONS | MET EXPECTATIONS | BELOW EXPECTATIONS | FAR BELOW EXPECTATIONS | NO DATA AVAILABLE."
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
        "parks, gas stations, coffee shops, cafes, hospitals, "
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
  Persistent map objects (always on map — use exact phrase): CTA stations, L stations, el stations, train stations, bus stops, bus stations, CTA bus stops, metra stations, metra stops, commuter rail stations, schools, libraries, police stations, fire stations, speed cameras, bike racks, Divvy stations, Open Air sensors
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


def _marine_alert_event(alert: dict) -> str:
    text = " ".join(
        _clean_marine_text(alert.get(key))
        for key in ("event", "headline", "name", "title")
        if alert.get(key)
    )
    low = text.lower()
    for event in _MARINE_HIGH_ALERTS | _MARINE_MEDIUM_ALERTS:
        if event.lower() in low:
            return event
    return _clean_marine_text(alert.get("event"))


def _marine_alert_display_from_payload(content_str: str) -> dict:
    """
    Style the combined Chicago lake-zone polygon from Chicago Marine Knowledge
    alerts embedded in the MCP response.
    """
    try:
        data = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        return {}
    alerts = ((data.get("alerts_first") or {}).get("alerts") or []) if isinstance(data, dict) else []
    events = {
        _marine_alert_event(alert)
        for alert in alerts
        if isinstance(alert, dict)
    }
    if events & _MARINE_HIGH_ALERTS:
        return {"color": "#B91C1C", "fillColor": "#EF4444", "opacity": 70, "fill": True}
    if events & _MARINE_MEDIUM_ALERTS:
        return {"color": "#B7791F", "fillColor": "#FDE047", "opacity": 70, "fill": True}
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


def _marine_is_recent(ts: str, hours: int = 36) -> bool:
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= datetime.now(timezone.utc) - timedelta(hours=hours)
    except (ValueError, TypeError):
        return False


def _normalize_provider_id(provider_id: str | None) -> str:
    if provider_id == _LEGACY_MARINE_PROVIDER_ID:
        return _MARINE_PROVIDER_ID
    return provider_id or ""


def _clean_marine_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(_clean_marine_text(v) for v in value if _clean_marine_text(v))
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text


def _format_marine_timestamp(value: Any) -> str:
    text = _clean_marine_text(value)
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.strftime("%b %-d, %-I:%M %p")
        return dt.astimezone(_CHICAGO_TZ).strftime("%b %-d, %-I:%M %p %Z")
    except (ValueError, TypeError):
        return text


def _first_marine_value(alert: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _clean_marine_text(alert.get(key))
        if value:
            return value
    return ""


def _format_marine_alert(alert: dict) -> str:
    event = _first_marine_value(alert, ("event", "event_name", "name", "title"))
    headline = _first_marine_value(alert, ("headline", "summary"))
    severity = _first_marine_value(alert, ("severity", "urgency", "certainty"))
    area = _first_marine_value(alert, ("areaDesc", "area_desc", "area", "zones"))
    effective = _format_marine_timestamp(
        alert.get("effective") or alert.get("onset") or alert.get("starts")
    )
    expires = _format_marine_timestamp(
        alert.get("expires") or alert.get("ends") or alert.get("end")
    )
    description = _first_marine_value(alert, ("description", "desc"))
    instruction = _first_marine_value(alert, ("instruction", "instructions"))

    pieces = []
    if event and headline and event not in headline:
        pieces.append(f"{event}: {headline}")
    else:
        pieces.append(headline or event or "Marine alert")

    context = []
    if severity:
        context.append(severity)
    if area:
        context.append(area)
    if effective or expires:
        if effective and expires:
            context.append(f"{effective} to {expires}")
        elif effective:
            context.append(f"effective {effective}")
        else:
            context.append(f"expires {expires}")
    if context:
        pieces.append("(" + "; ".join(context) + ")")
    if description and description not in headline:
        pieces.append(description)
    if instruction:
        pieces.append("Instruction: " + instruction)
    return " ".join(pieces)


def _marine_alert_details(alerts_block: dict) -> tuple[str, str]:
    if not isinstance(alerts_block, dict):
        return "", "No active marine alerts reported."
    alerts = [a for a in (alerts_block.get("alerts") or []) if isinstance(a, dict)]
    if alerts:
        detail = " ".join(_format_marine_alert(alert) for alert in alerts)
        names = [
            _first_marine_value(alert, ("event", "headline", "name", "title"))
            for alert in alerts
        ]
        names = [name for name in names if name]
        summary = "Marine alerts/advisories" if len(alerts) != 1 else "Marine alert/advisory"
        if names:
            summary += ": " + "; ".join(names)
        return detail, summary + ". " + detail

    msg = _clean_marine_text(alerts_block.get("message")) or "No active marine alerts reported."
    return "", msg


def _marine_source_notes(data: dict) -> str:
    statuses = data.get("source_statuses") or []
    unavailable = []
    for status in statuses:
        if not isinstance(status, dict):
            continue
        if status.get("status") not in ("healthy", "ok"):
            name = status.get("name") or status.get("source")
            detail = _clean_marine_text(status.get("detail"))
            if name:
                unavailable.append(name + (f" ({detail})" if detail else ""))
    return "; ".join(unavailable)


def _marine_summary_context(data: dict, alert_summary: str) -> str:
    base_context = data.get("llm_briefing_context") or data.get("headline") or ""
    if alert_summary.lower().startswith("marine alert/advisory"):
        base_context = re.sub(
            r"\bNo active marine alerts reported\.?\s*",
            "",
            base_context,
            flags=re.IGNORECASE,
        )
    parts = [
        base_context,
        alert_summary,
    ]
    forecast = data.get("marine_forecast_baseline") or {}
    wind_text = ((forecast.get("wind_kt") or {}).get("text") or "").strip()
    wave_text = ((forecast.get("waves_ft") or {}).get("text") or "").strip()
    if wind_text:
        parts.append(f"Forecast wind: {wind_text}.")
    if wave_text:
        parts.append(f"Forecast waves: {wave_text}.")
    source_notes = _marine_source_notes(data)
    if source_notes:
        parts.append(f"Source limitations: {source_notes}.")
    return " ".join(_clean_marine_text(p) for p in parts if _clean_marine_text(p))


def _deg_to_cardinal(deg: float | None) -> str:
    if deg is None:
        return ""
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[round(float(deg) / 22.5) % 16]


def _fmt_temp(c: float | None) -> str:
    if c is None or c == 0:
        return ""
    f = round(c * 9 / 5 + 32)
    return f"{c}°C ({f}°F)"


def _fmt_wind_kt(mps: float | None, dir_deg: float | None = None, gust_mps: float | None = None) -> str:
    if not mps or mps == 0:
        return ""
    kt = round(mps * 1.94384, 1)
    card = _deg_to_cardinal(dir_deg)
    s = f"{kt} kt" + (f" {card}" if card else "")
    if gust_mps and gust_mps > mps:
        s += f" (gust {round(gust_mps * 1.94384, 1)} kt)"
    return s


def _format_marine_conditions(content_str: str, zone_label: str) -> tuple[dict, list] | None:
    """
    Parse a marine MCP JSON response into structured card properties + columns.
    Returns (properties, columns) or None if content_str is not recognized marine JSON.
    The column order drives ResultsPanel card layout: first list:true string → title,
    any column whose id matches statusIds ('risk') → pill badge.
    """
    try:
        data = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or "headline" not in data:
        return None

    forecast = data.get("marine_forecast_baseline") or {}
    forecast_wind = (forecast.get("wind_kt") or {}).get("text", "")
    forecast_waves = (forecast.get("waves_ft") or {}).get("text", "")

    wa = data.get("wind_assessment") or {}
    wind_cat = wa.get("category", "")
    wva = data.get("wave_assessment") or {}
    wave_cat = wva.get("category", "")

    alerts_block = data.get("alerts_first") or {}
    alerts_detail, alerts_summary = _marine_alert_details(alerts_block)

    cautions = data.get("cautions") or []
    cautions_str = "; ".join(str(c) for c in cautions) if cautions else ""

    props: dict = {
        "title": "Lake Conditions",
        "summary": data.get("headline", ""),
        "risk_level": (data.get("risk_level") or "").title(),
        "zone_id": zone_label,
        "marine_summary_context": _marine_summary_context(data, alerts_summary),
        "marine_alert_summary": alerts_summary,
        "marine_raw_payload": json.dumps(data, separators=(",", ":")),
    }
    if forecast_wind:
        props["forecast_wind"] = forecast_wind
    if forecast_waves:
        props["forecast_waves"] = forecast_waves
    if wind_cat:
        props["wind_category"] = wind_cat.replace("_", " ")
    if wave_cat:
        props["wave_category"] = wave_cat.replace("_", " ")
    if alerts_detail:
        props["alerts"] = alerts_detail
    if cautions_str:
        props["cautions"] = cautions_str

    columns: list = [
        {"id": "title", "displayName": "Title", "dataType": "string", "popup": False, "list": True},
        {"id": "summary", "displayName": "Summary", "dataType": "string", "popup": True, "list": False},
        {"id": "risk_level", "displayName": "Risk Level", "dataType": "string", "popup": True, "list": False},
        {"id": "zone_id", "displayName": "Zone", "dataType": "string", "popup": True, "list": False},
        {"id": "marine_summary_context", "displayName": "Marine Summary Context", "dataType": "string", "popup": False, "list": False},
        {"id": "marine_alert_summary", "displayName": "Marine Alert Summary", "dataType": "string", "popup": False, "list": False},
        {"id": "marine_raw_payload", "displayName": "Marine Raw Payload", "dataType": "string", "popup": False, "list": False},
    ]
    if forecast_wind:
        columns.append({"id": "forecast_wind", "displayName": "Wind Forecast", "dataType": "string", "popup": True, "list": False})
    if forecast_waves:
        columns.append({"id": "forecast_waves", "displayName": "Wave Forecast", "dataType": "string", "popup": True, "list": False})
    if wind_cat:
        columns.append({"id": "wind_category", "displayName": "Wind Category", "dataType": "string", "popup": True, "list": False})
    if wave_cat:
        columns.append({"id": "wave_category", "displayName": "Wave Category", "dataType": "string", "popup": True, "list": False})
    if alerts_detail:
        columns.append({"id": "alerts", "displayName": "Alerts / Advisories", "dataType": "string", "popup": True, "list": False})
    if cautions_str:
        columns.append({"id": "cautions", "displayName": "Cautions", "dataType": "string", "popup": True, "list": False})

    # --- per-station observations (skip stale and all-zero entries) ----------
    obs = data.get("observation_summary") or {}

    # Dever Crib (primary offshore station)
    dc = obs.get("dever_crib") or {}
    if dc and _marine_is_recent(dc.get("observed_at", "")):
        v = dc.get("values") or {}
        parts = []
        t = _fmt_temp(v.get("air_temperature_c"))
        if t:
            parts.append(t)
        w = _fmt_wind_kt(v.get("wind_speed_mps"), v.get("wind_direction_deg"), v.get("wind_gust_mps"))
        if w:
            parts.append(w)
        rh = v.get("relative_humidity_percent")
        if rh and rh != 0:
            parts.append(f"{rh}% RH")
        if parts:
            props["obs_dever_crib"] = " · ".join(parts)
            columns.append({"id": "obs_dever_crib", "displayName": dc.get("sensor_name", "Dever Crib"), "dataType": "string", "popup": True, "list": False})

    # City beach weather stations
    for s in (obs.get("city_weather") or []):
        if not _marine_is_recent(s.get("observed_at", "")):
            continue
        v = s.get("values") or {}
        temp_c = v.get("air_temperature_c")
        wind_mps = v.get("wind_speed_mps")
        if (not temp_c or temp_c == 0) and (not wind_mps or wind_mps == 0):
            continue
        parts = []
        t = _fmt_temp(temp_c)
        if t:
            parts.append(t)
        w = _fmt_wind_kt(wind_mps, v.get("wind_direction_deg"))
        if w:
            parts.append(w)
        rh = v.get("relative_humidity_percent")
        if rh and rh != 0:
            parts.append(f"{rh}% RH")
        bp = v.get("barometric_pressure_hpa")
        if bp and bp != 0:
            parts.append(f"{bp} hPa")
        if parts:
            sid = "obs_wx_" + s.get("sensor_id", "").replace(" ", "_")
            props[sid] = " · ".join(parts)
            columns.append({"id": sid, "displayName": s.get("sensor_name", sid), "dataType": "string", "popup": True, "list": False})

    # City beach water sensors
    for s in (obs.get("city_water") or []):
        if not _marine_is_recent(s.get("observed_at", "")):
            continue
        v = s.get("values") or {}
        quality = s.get("quality_flags") or []
        temp_c = v.get("water_temperature_c")
        if "water_temperature:bad_sentinel" in quality:
            temp_c = None
        wave_m = v.get("wave_height_m")
        period_s = v.get("wave_period_s")
        if not temp_c and (not wave_m or wave_m == 0) and (not period_s or period_s == 0):
            continue
        parts = []
        t = _fmt_temp(temp_c)
        if t:
            parts.append(f"Water {t}")
        if wave_m and wave_m > 0:
            parts.append(f"Waves {round(wave_m * 3.28084, 1)} ft")
        if period_s and period_s > 0:
            parts.append(f"Period {period_s}s")
        if parts:
            sid = "obs_water_" + s.get("sensor_id", "").replace(" ", "_")
            props[sid] = " · ".join(parts)
            columns.append({"id": sid, "displayName": s.get("sensor_name", sid) + " (water)", "dataType": "string", "popup": True, "list": False})

    # Buoys
    for b in (obs.get("buoys") or []):
        if not _marine_is_recent(b.get("observed_at", "")):
            continue
        v = b.get("values") or {}
        parts = []
        t = _fmt_temp(v.get("water_temperature_c") or v.get("air_temperature_c"))
        if t:
            parts.append(t)
        w = _fmt_wind_kt(v.get("wind_speed_mps"), v.get("wind_direction_deg"), v.get("wind_gust_mps"))
        if w:
            parts.append(w)
        wh = v.get("wave_height_m")
        if wh and wh > 0:
            parts.append(f"Waves {round(wh * 3.28084, 1)} ft")
        if parts:
            sid = "obs_buoy_" + b.get("sensor_id", "").replace(" ", "_")
            props[sid] = " · ".join(parts)
            columns.append({"id": sid, "displayName": b.get("sensor_name", sid), "dataType": "string", "popup": True, "list": False})

    return props, columns


async def _process_mcp_result(result: dict) -> dict | None:
    """Process a Haiku MCP result → GeoJSON FeatureCollection with NWS zone polygon."""
    provider_id = _normalize_provider_id(result.get("provider_id"))
    tool_name = result.get("tool")
    args = result.get("args", {})
    zone_id = result.get("zone_id", "")

    provider = provider_registry.get(provider_id)
    if not provider:
        print(f"[smart_search] Unknown provider: {provider_id!r}")
        return None

    # For Chicago Marine Knowledge the geometry is the COMBINED Chicago shoreline zones
    # (LMZ740/741/742). Alert coloring spans all of them.
    if provider_id == _MARINE_PROVIDER_ID:
        async def _none():
            return None

        geo_cfg = provider._config.get("geometry", {})
        zones = geo_cfg.get("zones") or ([zone_id] if zone_id else [])

        results = await asyncio.gather(
            provider.call_tool(tool_name, args),
            zone_resolver.get_combined_zone_geojson(zones) if zones else _none(),
            return_exceptions=True,
        )
        mcp_result, zone_geom = results
        if isinstance(mcp_result, Exception):
            print(f"[smart_search] MCP call {provider_id}.{tool_name} failed: {mcp_result}")
            return None
        if isinstance(zone_geom, Exception):
            zone_geom = None
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
    alert_display = _marine_alert_display_from_payload(content_str) if provider_id == _MARINE_PROVIDER_ID else {}
    display = {**cfg.get("display", {}), **alert_display}
    feature_id = f"{provider_id}-{zone_label}"
    display_name = cfg.get("description", provider_id)

    marine_fmt = _format_marine_conditions(content_str, zone_label)
    if marine_fmt:
        feature_props, feature_columns = marine_fmt
    else:
        feature_props = {"zone_id": zone_label, "conditions": content_str}
        feature_columns = [
            {"id": "zone_id", "displayName": "Zone", "dataType": "string", "popup": True, "list": True},
            {"id": "conditions", "displayName": "Conditions", "dataType": "string", "popup": True, "list": False},
        ]

    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "id": feature_id,
            "geometry": zone_geom,
            "properties": feature_props,
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
                        "fill": display.get("fill", False),
                        "opacity": display.get("opacity", 50),
                        "size": 8,
                        "borderWidth": 2,
                    }
                },
                "columns": feature_columns,
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

    is_spatial = _dataset_is_spatial(ds)
    soql_where = result.get("soql_where") or ""

    geo_clause = _build_geo_clause(result.get("geography"), ds)
    if geo_clause:
        soql_where = f"({soql_where}) AND {geo_clause}" if soql_where else geo_clause

    prox = result.get("proximity")

    # If the caller supplied GPS coordinates but Haiku omitted a proximity field,
    # default to filtering within 400 m of the user's position rather than falling
    # back to the broad viewport filter.
    if is_spatial and current_location and not prox:
        prox = {"reference": "current location", "distance_meters": 400}

    # For "current location" proximity, push the spatial filter into SoQL via
    # within_circle() so Socrata does the work — no row-count cap, no Python loop.
    _using_circle = False
    if (is_spatial and current_location and prox
            and prox.get("reference", "").lower().strip() == "current location"):
        radius_m = float(prox.get("distance_meters", 400))
        circle_clause = (
            f"within_circle(location, {current_location['lat']}, "
            f"{current_location['lon']}, {radius_m})"
        )
        soql_where = f"({soql_where}) AND {circle_clause}" if soql_where else circle_clause
        _using_circle = True

    limit = 500 if _using_circle else (1000 if prox else 500)

    has_geo_context = bool(result.get("geography") or prox)
    if is_spatial and bounds and not has_geo_context:
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
    rows = _normalize_rows_for_dataset(rows, ds)

    proximity_meta = None
    if is_spatial and prox and rows:
        print(f"[smart_search] proximity reference={prox['reference']!r} distance={prox.get('distance_meters')}m")
        if prox["reference"].lower().strip() == "current location":
            if current_location:
                ref_locs = [{"lat": current_location["lat"], "lon": current_location["lon"], "name": "Your location"}]
            else:
                ref_locs = []
        else:
            ref_locs = await proximity.fetch_reference_locations(prox["reference"], bounds=bounds)
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
            is_persistent = prox["reference"].lower().strip() in proximity.PERSISTENT_PROXIMITY
            proximity_meta = {
                "label": label,
                "distance_meters": distance_m,
                "layer": None if is_persistent else _build_reference_layer(ref_locs, prox["reference"]),
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
    elif bounds and _dataset_is_spatial(ds):
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
    if bbox and _dataset_is_spatial(ds):
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
    rows = _normalize_rows_for_dataset(rows, ds)
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
    rows = _normalize_rows_for_dataset(rows, ds)
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
    persistent = await _persistent_object_search(query, bounds, current_location)
    if persistent is not None:
        persistent["intent"] = "display"
        print(f"[smart_search] query={query!r} persistent={persistent['meta']['view']['id']} count={len(persistent.get('features', []))}")
        return persistent

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
