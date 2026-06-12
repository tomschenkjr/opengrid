"""
Chicago Public Library event feed helpers.

Source: City of Chicago Socrata dataset vsdy-d8k7. The dataset only contains
upcoming CPL events, so it is safe to cache briefly and reuse for page cards and
library result-pane summaries.
"""
import html
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

from services import geography

_EVENTS_URL = "https://data.cityofchicago.org/resource/vsdy-d8k7.json"
_CACHE_TTL = timedelta(minutes=30)
_events_cache: dict = {"data": None, "expires": None}

_FIELDS = [
    "title", "description", "event_types", "event_audiences", "event_languages",
    "event_page", "location_name", "location_details", "start", "end",
    "featured", "cancelled", "recurring", "registration_closed",
    "registration_status", "registration_starts", "registration_ends",
    "location_address", "location_zip", "location", "day_of_the_week", "event_id",
]


def _headers() -> dict:
    headers = {"User-Agent": "opengrid-service/1.0"}
    token = os.getenv("SOCRATA_APP_TOKEN", "").strip() or None
    if token:
        headers["X-App-Token"] = token
    return headers


def library_key(value: str | None) -> str:
    if not value:
        return ""
    key = value.upper().replace("WASHTINGTON", "WASHINGTON")
    key = re.sub(r"\b(CHICAGO PUBLIC|REGIONAL|BRANCH|LIBRARY|CENTER)\b", " ", key)
    key = re.sub(r"[^A-Z0-9]+", " ", key)
    key = re.sub(r"\bDALEY RICHARD J BRIDGEPORT\b", "DALEY RICHARD J", key)
    key = re.sub(r"\bDALEY RICHARD M W HUMBOLDT\b", "DALEY RICHARD M", key)
    return re.sub(r"\s+", " ", key).strip()


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"true", "1", "yes"}


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<\s*br\s*/?\s*>", " ", value, flags=re.I)
    text = re.sub(r"</\s*p\s*>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _event_page_url(row: dict) -> str | None:
    page = row.get("event_page")
    if isinstance(page, dict):
        return page.get("url")
    if isinstance(page, str) and page.startswith("http"):
        return page
    return None


def _lat_lon(row: dict) -> tuple[float | None, float | None]:
    loc = row.get("location")
    lat = lon = None
    if isinstance(loc, dict):
        lat = loc.get("latitude") or loc.get("lat")
        lon = loc.get("longitude") or loc.get("lon")
        coords = loc.get("coordinates")
        if (lat is None or lon is None) and isinstance(coords, list) and len(coords) >= 2:
            lon, lat = coords[0], coords[1]
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None, None


def _normalize_event(row: dict) -> dict:
    lat, lon = _lat_lon(row)
    description_text = _strip_html(row.get("description"))
    return {
        "id": row.get("event_id") or row.get("title"),
        "event_id": row.get("event_id"),
        "title": row.get("title") or "Library Event",
        "description": description_text,
        "summary": description_text[:260],
        "event_types": row.get("event_types"),
        "event_audiences": row.get("event_audiences"),
        "event_languages": row.get("event_languages"),
        "event_page_url": _event_page_url(row),
        "location_name": row.get("location_name"),
        "location_key": library_key(row.get("location_name")),
        "location_details": row.get("location_details"),
        "location_address": row.get("location_address"),
        "location_zip": row.get("location_zip"),
        "start": row.get("start"),
        "end": row.get("end"),
        "day_of_the_week": row.get("day_of_the_week"),
        "featured": _truthy(row.get("featured")),
        "cancelled": _truthy(row.get("cancelled")),
        "recurring": _truthy(row.get("recurring")),
        "registration_closed": _truthy(row.get("registration_closed")),
        "registration_status": row.get("registration_status"),
        "registration_starts": row.get("registration_starts"),
        "registration_ends": row.get("registration_ends"),
        "lat": lat,
        "lon": lon,
        "source": "Chicago Public Library",
        "category": "Events",
    }


def _soql_quote(value: str) -> str:
    return value.replace("'", "''")


def _build_where(
    event_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    neighborhood: str | None = None,
) -> str | None:
    clauses = []
    if event_id:
        clauses.append(f"event_id = '{_soql_quote(event_id)}'")
    if date_from:
        clauses.append(f"start >= '{_soql_quote(date_from)}'")
    if date_to:
        clauses.append(f"start < '{_soql_quote(date_to)}'")
    if neighborhood:
        number, _official = geography.resolve_community_area(neighborhood)
        polygon = geography.get_community_area_polygon(number) if number else None
        if polygon:
            clauses.append(f"within_polygon(location, '{_soql_quote(polygon)}')")
    return " AND ".join(clauses) if clauses else None


async def _fetch_rows(where: str | None = None, limit: int = 6000) -> list[dict]:
    params = {
        "$select": ",".join(_FIELDS),
        "$limit": min(limit, 6000),
        "$order": "start ASC",
    }
    if where:
        params["$where"] = where
    async with httpx.AsyncClient(headers=_headers(), timeout=45) as http:
        r = await http.get(_EVENTS_URL, params=params)
        r.raise_for_status()
        return r.json()


async def all_events() -> list[dict]:
    now = datetime.now(timezone.utc)
    if _events_cache["data"] and _events_cache["expires"] and now < _events_cache["expires"]:
        return _events_cache["data"]
    rows = await _fetch_rows()
    events = [_normalize_event(row) for row in rows]
    _events_cache["data"] = events
    _events_cache["expires"] = now + _CACHE_TTL
    return events


def _matches_text(event: dict, text: str | None) -> bool:
    if not text:
        return True
    needle = text.lower().strip()
    haystack = " ".join(str(event.get(k) or "") for k in [
        "title", "description", "event_types", "event_audiences",
        "location_name", "location_address", "location_zip",
    ]).lower()
    return needle in haystack


async def events(
    event_id: str | None = None,
    q: str | None = None,
    library: str | None = None,
    neighborhood: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
) -> list[dict]:
    where = _build_where(event_id=event_id, date_from=date_from, date_to=date_to, neighborhood=neighborhood)
    rows = await _fetch_rows(where=where, limit=max(limit, 500)) if where else await all_events()
    normalized = [_normalize_event(row) for row in rows] if where else list(rows)

    lib_key = library_key(library)
    filtered = []
    for event in normalized:
        if lib_key and event.get("location_key") != lib_key:
            continue
        if not _matches_text(event, q):
            continue
        filtered.append(event)
        if len(filtered) >= limit:
            break
    return filtered


async def events_by_library(limit_per_library: int = 8) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for event in await all_events():
        key = event.get("location_key")
        if not key:
            continue
        bucket = grouped.setdefault(key, [])
        if len(bucket) < limit_per_library:
            bucket.append(event)
    return grouped
