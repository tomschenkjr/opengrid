"""
Navy Pier event feed.

Navy Pier (navypier.org) is WordPress with a custom `navy_pier_events` post type.
The list endpoint gives titles + links but not dates; each event page carries a
schema.org Event/EventSeries JSON-LD block with the real start/end/location, so we
list via REST then read each event's JSON-LD. Cached, with bounded concurrency.
"""
import asyncio
import html as _html
import json
import re
from datetime import datetime, timezone

import httpx

_LIST_URL = "https://navypier.org/wp-json/wp/v2/navy_pier_events"
_LIST_COUNT = 40          # newest posts to consider
_CONCURRENCY = 8
_CACHE_TTL_MINUTES = 360  # 6h

# Navy Pier is at the foot of Streeterville — Near North Side (community area 8).
_VENUE = {
    "location_address": "600 E Grand Ave, Chicago, IL",
    "location_zip": "60611",
    "lat": 41.8916, "lon": -87.6079, "community_area": 8,
}
_BADGE_COLOR = "#0072ce"

_LDJSON_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_events_cache: dict = {"data": None, "expires": None}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ld_events(blob: str) -> list[dict]:
    """Flatten any Event / EventSeries (and their subEvents) found in a JSON-LD blob."""
    try:
        data = json.loads(blob)
    except (ValueError, TypeError):
        return []
    nodes = data if isinstance(data, list) else data.get("@graph", [data])
    out = []
    for node in nodes if isinstance(nodes, list) else [nodes]:
        if not isinstance(node, dict):
            continue
        t = node.get("@type", "")
        if "Event" in (t if isinstance(t, str) else "".join(t)):
            subs = node.get("subEvent")
            if isinstance(subs, list) and subs:
                out.extend(s for s in subs if isinstance(s, dict))
            else:
                out.append(node)
    return out


def _best_upcoming(page_html: str) -> dict | None:
    """Earliest still-upcoming dated Event in the page's JSON-LD, or None."""
    now = _now()
    best, best_dt = None, None
    for blob in _LDJSON_RE.findall(page_html):
        for ev in _ld_events(blob):
            dt = _parse_dt(ev.get("startDate"))
            if not dt or dt < now:
                continue
            if best_dt is None or dt < best_dt:
                best, best_dt = ev, dt
    return best


def _location_name(ev: dict) -> str:
    loc = ev.get("location")
    if isinstance(loc, dict) and loc.get("name"):
        return loc["name"]
    if isinstance(loc, list) and loc and isinstance(loc[0], dict):
        return loc[0].get("name") or "Navy Pier"
    return "Navy Pier"


def _normalize(post: dict, ev: dict) -> dict:
    desc = _strip_html(ev.get("description"))
    venue_name = _location_name(ev)
    return {
        "id": f"np-{post.get('id')}",
        "event_id": f"np-{post.get('id')}",
        "title": _strip_html((post.get("title") or {}).get("rendered")) or ev.get("name") or "Navy Pier Event",
        "description": desc,
        "summary": desc[:260],
        "event_types": ev.get("keywords") or "Navy Pier",
        "event_audiences": None,
        "event_languages": None,
        "event_page_url": ev.get("url") or post.get("link"),
        "location_name": venue_name,
        "location_key": "",
        "location_details": "Navy Pier" if venue_name != "Navy Pier" else None,
        "location_address": _VENUE["location_address"],
        "location_zip": _VENUE["location_zip"],
        "start": ev.get("startDate"),
        "end": ev.get("endDate"),
        "day_of_the_week": (_parse_dt(ev.get("startDate")) or _now()).strftime("%A"),
        "featured": False,
        "cancelled": "Cancelled" in str(ev.get("eventStatus", "")),
        "recurring": False,
        "registration_closed": False,
        "registration_status": None,
        "registration_starts": None,
        "registration_ends": None,
        "lat": _VENUE["lat"],
        "lon": _VENUE["lon"],
        "community_area": _VENUE["community_area"],
        "image": ev.get("image") if isinstance(ev.get("image"), str) else None,
        "source": "Navy Pier",
        "category": "Attraction",
        "badge": "Navy Pier",
        "badge_color": _BADGE_COLOR,
    }


async def _fetch_one(http: httpx.AsyncClient, sem: asyncio.Semaphore, post: dict) -> dict | None:
    link = post.get("link")
    if not link:
        return None
    async with sem:
        try:
            r = await http.get(link)
            r.raise_for_status()
        except Exception:
            return None
    ev = _best_upcoming(r.text)
    return _normalize(post, ev) if ev else None


async def _fetch_all() -> list[dict]:
    headers = {"User-Agent": "opengrid-service/1.0"}
    async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as http:
        try:
            r = await http.get(_LIST_URL, params={"per_page": _LIST_COUNT,
                                                   "_fields": "id,link,title"})
            r.raise_for_status()
            posts = r.json()
        except Exception:
            return []
        sem = asyncio.Semaphore(_CONCURRENCY)
        results = await asyncio.gather(*[_fetch_one(http, sem, p) for p in posts])
    events = [e for e in results if e]
    events.sort(key=lambda e: e.get("start") or "")
    return events


async def all_events() -> list[dict]:
    from datetime import timedelta
    now = _now()
    if _events_cache["data"] and _events_cache["expires"] and now < _events_cache["expires"]:
        return _events_cache["data"]
    events = await _fetch_all()
    _events_cache["data"] = events
    _events_cache["expires"] = now + timedelta(minutes=_CACHE_TTL_MINUTES)
    return events


def _matches_text(event: dict, text: str | None) -> bool:
    if not text:
        return True
    needle = text.lower().strip()
    haystack = " ".join(str(event.get(k) or "") for k in
                        ["title", "description", "event_types", "location_name"]).lower()
    return needle in haystack


def _in_window(start: str | None, date_from: str | None, date_to: str | None) -> bool:
    if not start:
        return False
    # start carries a tz offset; compare on the date/time prefix, which is enough here.
    if date_from and start[:len(date_from)] < date_from:
        return False
    if date_to and start[:len(date_to)] > date_to:
        return False
    return True


async def events(
    event_id: str | None = None,
    q: str | None = None,
    neighborhood: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
) -> list[dict]:
    from services import geography
    if neighborhood:
        number, _ = geography.resolve_community_area(neighborhood)
        if number and number != _VENUE["community_area"]:
            return []

    items = await all_events()
    out = []
    for ev in items:
        if event_id and ev.get("event_id") != event_id:
            continue
        if not event_id and not _in_window(ev.get("start"), date_from, date_to):
            continue
        if not _matches_text(ev, q):
            continue
        out.append(ev)
        if len(out) >= limit:
            break
    return out
