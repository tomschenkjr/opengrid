"""
Fetch and cache NWS/marine zone GeoJSON boundaries from api.weather.gov.

Zone ID prefixes:
  LMZ* → marine zones (Lake Michigan)
  ILZ* → NWS forecast zones (Illinois)

Zones are stable — fetched once per process and cached in-memory.
"""

import asyncio

import httpx

_cache: dict[str, dict] = {}

_NWS_BASE = "https://api.weather.gov/zones"
_HEADERS = {
    "User-Agent": "opengrid-service/1.0 (tomschenkjr@gmail.com)",
    "Accept": "application/geo+json",
}


def _zone_type(zone_id: str) -> str:
    return "marine" if zone_id.upper().startswith("LMZ") else "forecast"


async def get_zone_geojson(zone_id: str) -> dict | None:
    """
    Return a GeoJSON geometry dict for a zone, or None on failure.
    Result is cached for the lifetime of the process.
    """
    zone_id = zone_id.upper()
    if zone_id in _cache:
        return _cache[zone_id]

    url = f"{_NWS_BASE}/{_zone_type(zone_id)}/{zone_id}"
    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            geom = data.get("geometry")
            if geom:
                _cache[zone_id] = geom
                print(f"[zone_resolver] Cached geometry for {zone_id} ({geom['type']})")
                return geom
            print(f"[zone_resolver] No geometry in response for {zone_id}")
    except Exception as e:
        print(f"[zone_resolver] Failed to fetch zone {zone_id}: {e}")
    return None


def _polygons_of(geom: dict) -> list:
    """Return the list of polygon coordinate arrays in a Polygon/MultiPolygon."""
    if not geom:
        return []
    if geom.get("type") == "Polygon":
        return [geom["coordinates"]]
    if geom.get("type") == "MultiPolygon":
        return list(geom["coordinates"])
    return []


async def get_combined_zone_geojson(zone_ids: list[str]) -> dict | None:
    """
    Fetch several zones and merge them into a single MultiPolygon geometry
    (no dissolve — the zones are simply combined into one feature for display).
    Cached under the joined key.
    """
    key = "+".join(z.upper() for z in zone_ids)
    if key in _cache:
        return _cache[key]

    geoms = await asyncio.gather(*[get_zone_geojson(z) for z in zone_ids])
    polygons = []
    for g in geoms:
        polygons.extend(_polygons_of(g))
    if not polygons:
        return None

    combined = {"type": "MultiPolygon", "coordinates": polygons}
    _cache[key] = combined
    print(f"[zone_resolver] Combined geometry for {key} ({len(polygons)} polygon(s))")
    return combined


async def warm_zones(zone_ids: list[str]) -> None:
    """Pre-fetch a list of zone boundaries at startup."""
    for zone_id in zone_ids:
        await get_zone_geojson(zone_id)
