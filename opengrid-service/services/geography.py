"""
Chicago geographic boundary resolution.

Provides:
  - Community area name/alias → number lookup (static)
  - Boundary polygon cache fetched from Socrata at startup
  - WKT polygon strings for use in Socrata within_polygon() SOQL queries
"""

import json
import os
import httpx

# All 77 Chicago community areas: uppercase name → area number
COMMUNITY_AREAS: dict[str, int] = {
    "ROGERS PARK": 1, "WEST RIDGE": 2, "UPTOWN": 3, "LINCOLN SQUARE": 4,
    "NORTH CENTER": 5, "LAKE VIEW": 6, "LINCOLN PARK": 7, "NEAR NORTH SIDE": 8,
    "EDISON PARK": 9, "NORWOOD PARK": 10, "JEFFERSON PARK": 11, "FOREST GLEN": 12,
    "NORTH PARK": 13, "ALBANY PARK": 14, "PORTAGE PARK": 15, "IRVING PARK": 16,
    "DUNNING": 17, "MONTCLARE": 18, "BELMONT CRAGIN": 19, "HERMOSA": 20,
    "AVONDALE": 21, "LOGAN SQUARE": 22, "HUMBOLDT PARK": 23, "WEST TOWN": 24,
    "AUSTIN": 25, "WEST GARFIELD PARK": 26, "EAST GARFIELD PARK": 27,
    "NEAR WEST SIDE": 28, "NORTH LAWNDALE": 29, "SOUTH LAWNDALE": 30,
    "LOWER WEST SIDE": 31, "LOOP": 32, "NEAR SOUTH SIDE": 33, "ARMOUR SQUARE": 34,
    "DOUGLAS": 35, "OAKLAND": 36, "FULLER PARK": 37, "GRAND BOULEVARD": 38,
    "KENWOOD": 39, "WASHINGTON PARK": 40, "HYDE PARK": 41, "WOODLAWN": 42,
    "SOUTH SHORE": 43, "CHATHAM": 44, "AVALON PARK": 45, "SOUTH CHICAGO": 46,
    "BURNSIDE": 47, "CALUMET HEIGHTS": 48, "ROSELAND": 49, "PULLMAN": 50,
    "SOUTH DEERING": 51, "EAST SIDE": 52, "WEST PULLMAN": 53, "RIVERDALE": 54,
    "HEGEWISCH": 55, "GARFIELD RIDGE": 56, "ARCHER HEIGHTS": 57, "BRIGHTON PARK": 58,
    "MCKINLEY PARK": 59, "BRIDGEPORT": 60, "NEW CITY": 61, "WEST ELSDON": 62,
    "GAGE PARK": 63, "CLEARING": 64, "WEST LAWN": 65, "CHICAGO LAWN": 66,
    "WEST ENGLEWOOD": 67, "ENGLEWOOD": 68, "GREATER GRAND CROSSING": 69,
    "ASHBURN": 70, "AUBURN GRESHAM": 71, "BEVERLY": 72, "WASHINGTON HEIGHTS": 73,
    "MOUNT GREENWOOD": 74, "MORGAN PARK": 75, "OHARE": 76, "EDGEWATER": 77,
}

# Informal neighborhood names → official community area name
NEIGHBORHOOD_ALIASES: dict[str, str] = {
    "WICKER PARK": "WEST TOWN",
    "PILSEN": "LOWER WEST SIDE",
    "ANDERSONVILLE": "EDGEWATER",
    "BOYSTOWN": "LAKE VIEW",
    "NORTHALSTED": "LAKE VIEW",
    "RIVER NORTH": "NEAR NORTH SIDE",
    "GOLD COAST": "NEAR NORTH SIDE",
    "STREETERVILLE": "NEAR NORTH SIDE",
    "OLD TOWN": "LINCOLN PARK",
    "BUCKTOWN": "LOGAN SQUARE",
    "UKRAINIAN VILLAGE": "WEST TOWN",
    "NOBLE SQUARE": "WEST TOWN",
    "GREEKTOWN": "NEAR WEST SIDE",
    "LITTLE ITALY": "NEAR WEST SIDE",
    "MEDICAL DISTRICT": "NEAR WEST SIDE",
    "UNIVERSITY VILLAGE": "NEAR WEST SIDE",
    "CHINATOWN": "ARMOUR SQUARE",
    "BRONZEVILLE": "DOUGLAS",
    "LITTLE VILLAGE": "SOUTH LAWNDALE",
    "SOUTH LOOP": "NEAR SOUTH SIDE",
    "PRINTERS ROW": "LOOP",
    "THE LOOP": "LOOP",
    "DOWNTOWN": "LOOP",
    "PRINTER'S ROW": "LOOP",
    "WRIGLEYVILLE": "LAKE VIEW",
    "LAKEVIEW": "LAKE VIEW",
    "ROSCOE VILLAGE": "NORTH CENTER",
    "RAVENSWOOD": "LINCOLN SQUARE",
    "ANDERSONVILLE": "EDGEWATER",
    "ROGERS PARK": "ROGERS PARK",
    "HUMBOLDT PARK": "HUMBOLDT PARK",
    "EAST GARFIELD PARK": "EAST GARFIELD PARK",
    "WEST GARFIELD PARK": "WEST GARFIELD PARK",
    "EAST VILLAGE": "WEST TOWN",
    "UKRAINIAN VILLAGE": "WEST TOWN",
    "JEFFERSON PARK": "JEFFERSON PARK",
    "NORWOOD PARK": "NORWOOD PARK",
    "PORTAGE PARK": "PORTAGE PARK",
    "IRVING PARK": "IRVING PARK",
    "AVONDALE": "AVONDALE",
    "BACK OF THE YARDS": "NEW CITY",
    "BRIDGEPORT": "BRIDGEPORT",
    "MCKINLEY PARK": "MCKINLEY PARK",
    "BRIGHTON PARK": "BRIGHTON PARK",
    "ARCHER HEIGHTS": "ARCHER HEIGHTS",
    "GAGE PARK": "GAGE PARK",
    "MARQUETTE PARK": "CHICAGO LAWN",
    "CHICAGO LAWN": "CHICAGO LAWN",
    "WEST LAWN": "WEST LAWN",
    "ENGLEWOOD": "ENGLEWOOD",
    "WEST ENGLEWOOD": "WEST ENGLEWOOD",
    "GREATER GRAND CROSSING": "GREATER GRAND CROSSING",
    "CHATHAM": "CHATHAM",
    "SOUTH SHORE": "SOUTH SHORE",
    "WOODLAWN": "WOODLAWN",
    "HYDE PARK": "HYDE PARK",
    "KENWOOD": "KENWOOD",
    "WASHINGTON PARK": "WASHINGTON PARK",
    "GRAND BOULEVARD": "GRAND BOULEVARD",
    "DOUGLAS": "DOUGLAS",
    "OAKLAND": "OAKLAND",
    "SOUTH CHICAGO": "SOUTH CHICAGO",
    "EAST SIDE": "EAST SIDE",
    "HEGEWISCH": "HEGEWISCH",
    "ROSELAND": "ROSELAND",
    "PULLMAN": "PULLMAN",
    "WEST PULLMAN": "WEST PULLMAN",
    "MORGAN PARK": "MORGAN PARK",
    "BEVERLY": "BEVERLY",
    "MOUNT GREENWOOD": "MOUNT GREENWOOD",
    "AUBURN GRESHAM": "AUBURN GRESHAM",
    "ASHBURN": "ASHBURN",
}

# Boundary polygon cache: area number → WKT string
_community_polygons: dict[int, str] = {}
_ward_polygons: dict[int, str] = {}


def resolve_community_area(name: str) -> tuple[int | None, str | None]:
    """
    Resolve a neighborhood or community area name to its official number.
    Returns (number, official_name) or (None, None) if not found.
    """
    upper = name.upper().strip()
    # Check aliases first
    official = NEIGHBORHOOD_ALIASES.get(upper, upper)
    number = COMMUNITY_AREAS.get(official)
    if number:
        return number, official
    return None, None


def get_community_area_polygon(number: int) -> str | None:
    """Return WKT polygon for use in within_polygon() SOQL, or None if not cached."""
    return _community_polygons.get(number)


def get_ward_polygon(ward: int) -> str | None:
    """Return WKT polygon for a ward boundary, or None if not cached."""
    return _ward_polygons.get(ward)


def _bbox_from_wkt(wkt: str) -> dict | None:
    """Extract min/max lat/lon from a WKT POLYGON string."""
    import re
    coords = re.findall(r"(-?\d+\.\d+)\s+(-?\d+\.\d+)", wkt)
    if not coords:
        return None
    lons = [float(c[0]) for c in coords]
    lats = [float(c[1]) for c in coords]
    return {"minLat": min(lats), "maxLat": max(lats), "minLon": min(lons), "maxLon": max(lons)}


def get_community_area_bbox(number: int) -> dict | None:
    """Return {minLat, maxLat, minLon, maxLon} bounding box for a community area."""
    wkt = _community_polygons.get(number)
    return _bbox_from_wkt(wkt) if wkt else None


def get_ward_bbox(ward: int) -> dict | None:
    """Return {minLat, maxLat, minLon, maxLon} bounding box for a ward."""
    wkt = _ward_polygons.get(ward)
    return _bbox_from_wkt(wkt) if wkt else None


def community_area_list_for_prompt() -> str:
    """Return a compact string of all community areas for the Haiku system prompt."""
    lines = []
    for name, number in sorted(COMMUNITY_AREAS.items(), key=lambda x: x[1]):
        lines.append(f"{name}={number}")
    # Also add key aliases
    alias_lines = []
    seen = set()
    for alias, official in NEIGHBORHOOD_ALIASES.items():
        if alias != official and alias not in COMMUNITY_AREAS:
            target_num = COMMUNITY_AREAS.get(official)
            if target_num and alias not in seen:
                alias_lines.append(f"{alias}→{official}({target_num})")
                seen.add(alias)
    return ", ".join(lines) + "\nAliases: " + ", ".join(alias_lines[:30])


def _geojson_multipolygon_to_wkt(geom: dict) -> str | None:
    """Convert a GeoJSON MultiPolygon or Polygon to WKT for Socrata within_polygon()."""
    if not geom:
        return None
    geo_type = geom.get("type", "")
    coords = geom.get("coordinates", [])

    try:
        if geo_type == "MultiPolygon":
            poly_parts = []
            for polygon in coords:
                ring_parts = []
                for ring in polygon:
                    pts = ", ".join(f"{c[0]} {c[1]}" for c in ring)
                    ring_parts.append(f"({pts})")
                poly_parts.append(f"({', '.join(ring_parts)})")
            return f"MULTIPOLYGON ({', '.join(poly_parts)})"

        if geo_type == "Polygon":
            ring_parts = []
            for ring in coords:
                pts = ", ".join(f"{c[0]} {c[1]}" for c in ring)
                ring_parts.append(f"({pts})")
            return f"MULTIPOLYGON (({', '.join(ring_parts)}))"
    except (IndexError, TypeError):
        return None

    return None


async def _fetch_community_area_polygons():
    """Fetch community area boundary polygons from Socrata."""
    global _community_polygons
    app_token = os.getenv("SOCRATA_APP_TOKEN", "").strip() or None
    headers = {"User-Agent": "opengrid-service/1.0"}
    if app_token:
        headers["X-App-Token"] = app_token

    try:
        async with httpx.AsyncClient(headers=headers, timeout=30) as http:
            # Fetch all 77 community areas with their geometry
            r = await http.get(
                "https://data.cityofchicago.org/resource/igwz-8jzy.json",
                params={"$limit": 100},
            )
            r.raise_for_status()
            rows = r.json()

        for row in rows:
            try:
                number = int(row.get("area_numbe", 0))
                geom_raw = row.get("the_geom")
                if not geom_raw or not number:
                    continue
                if isinstance(geom_raw, str):
                    geom_raw = json.loads(geom_raw)
                wkt = _geojson_multipolygon_to_wkt(geom_raw)
                if wkt:
                    _community_polygons[number] = wkt
            except (ValueError, json.JSONDecodeError, TypeError):
                continue

        print(f"Geography: cached {len(_community_polygons)} community area polygons")
    except Exception as e:
        print(f"Geography: failed to fetch community area polygons: {e}")


async def _fetch_ward_polygons():
    """Fetch ward boundary polygons from Socrata."""
    global _ward_polygons
    app_token = os.getenv("SOCRATA_APP_TOKEN", "").strip() or None
    headers = {"User-Agent": "opengrid-service/1.0"}
    if app_token:
        headers["X-App-Token"] = app_token

    try:
        async with httpx.AsyncClient(headers=headers, timeout=30) as http:
            r = await http.get(
                "https://data.cityofchicago.org/resource/sp34-6z76.json",
                params={"$limit": 60},
            )
            r.raise_for_status()
            rows = r.json()

        for row in rows:
            try:
                # Field may be "ward" or "ward_num" depending on dataset version
                ward_raw = row.get("ward") or row.get("ward_num") or row.get("ward_no")
                ward = int(ward_raw) if ward_raw else 0
                geom_raw = row.get("the_geom") or row.get("geometry")
                if not geom_raw or not ward:
                    continue
                if isinstance(geom_raw, str):
                    geom_raw = json.loads(geom_raw)
                wkt = _geojson_multipolygon_to_wkt(geom_raw)
                if wkt:
                    _ward_polygons[ward] = wkt
            except (ValueError, json.JSONDecodeError, TypeError):
                continue

        print(f"Geography: cached {len(_ward_polygons)} ward polygons")
    except Exception as e:
        print(f"Geography: failed to fetch ward polygons: {e}")


async def initialize():
    """Fetch and cache all boundary polygons at service startup."""
    await _fetch_community_area_polygons()
    await _fetch_ward_polygons()
