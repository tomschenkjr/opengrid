"""
Chicago Park District event feed.

chicagoparkdistrict.com/events is a Drupal site with no public API, but the listing
renders clean server-side event cards (event--date / event--title / event--location /
event--duration). We scrape a few pages of that listing, defensively, and cache.
Fragile by nature — a site redesign will require updating the card regexes below.
"""
import html as _html
import re
from datetime import date, datetime, timedelta

import httpx

_BASE = "https://www.chicagoparkdistrict.com"
_EVENTS_URL = f"{_BASE}/events"
_PAGES = 3                 # listing pages to pull (each ~10 cards)
_CACHE_TTL_MINUTES = 360   # 6h
_BADGE_COLOR = "#00833e"   # Park District green

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

# Card field patterns (Drupal "node--type-event" cards).
_DATE_RE = re.compile(r'event--date[^>]*>\s*([A-Za-z]{3,9})\s*<[^>]*>\s*(\d{1,2})', re.S)
_TITLE_RE = re.compile(r'event--title.*?<a\s+href="(/events/[^"]+)"[^>]*>(.*?)</a>', re.S)
_LOC_RE = re.compile(r'event--location.*?<a\s[^>]*>\s*(.*?)\s*</a>', re.S)
_DUR_RE = re.compile(r'event--duration[^>]*>\s*(.*?)\s*</div>', re.S)
_TIME_RE = re.compile(r'(\d{1,2}:\d{2}\s*[AP]M)', re.I)

_events_cache: dict = {"data": None, "expires": None}


def _clean(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _infer_year(month: int, day: int) -> int:
    today = date.today()
    year = today.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return year
    # Listing is upcoming; a date well in the past means it rolls to next year.
    if (today - candidate).days > 60:
        year += 1
    return year


def _combine(month: int, day: int, time_str: str | None) -> str | None:
    year = _infer_year(month, day)
    t = None
    if time_str:
        try:
            t = datetime.strptime(time_str.upper().replace(" ", ""), "%I:%M%p").time()
        except ValueError:
            t = None
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    dt = datetime.combine(d, t) if t else datetime(year, month, day)
    return dt.isoformat()


def _parse_card(chunk: str) -> dict | None:
    dm = _DATE_RE.search(chunk)
    tm = _TITLE_RE.search(chunk)
    if not dm or not tm:
        return None
    month = _MONTHS.get(dm.group(1)[:3].lower())
    if not month:
        return None
    day = int(dm.group(2))

    slug, title = tm.group(1), _clean(tm.group(2))
    if not title:
        return None

    lm = _LOC_RE.search(chunk)
    address = _clean(lm.group(1)) if lm else None
    durm = _DUR_RE.search(chunk)
    duration = _clean(durm.group(1)) if durm else ""
    times = _TIME_RE.findall(duration)
    start = _combine(month, day, times[0] if times else None)
    end = _combine(month, day, times[1]) if len(times) > 1 else None
    if not start:
        return None

    zip_m = re.search(r"\b(\d{5})\b", address or "")
    return {
        "id": f"cpd-{slug.rsplit('/', 1)[-1]}",
        "event_id": f"cpd-{slug.rsplit('/', 1)[-1]}",
        "title": title,
        "description": "",
        "summary": "",
        "event_types": "Parks & Recreation",
        "event_audiences": None,
        "event_languages": None,
        "event_page_url": _BASE + slug,
        "location_name": "Chicago Park District",
        "location_key": "",
        "location_details": address,
        "location_address": address,
        "location_zip": zip_m.group(1) if zip_m else None,
        "start": start,
        "end": end,
        "day_of_the_week": datetime.fromisoformat(start).strftime("%A"),
        "featured": False,
        "cancelled": False,
        "recurring": False,
        "registration_closed": False,
        "registration_status": None,
        "registration_starts": None,
        "registration_ends": None,
        "lat": None,
        "lon": None,
        "community_area": None,
        "source": "Chicago Park District",
        "category": "Parks",
        "badge": "Park District",
        "badge_color": _BADGE_COLOR,
    }


async def _fetch_all() -> list[dict]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; opengrid-service/1.0)"}
    events: list[dict] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as http:
        for page in range(_PAGES):
            try:
                r = await http.get(_EVENTS_URL, params={"page": page} if page else None)
                r.raise_for_status()
            except Exception:
                break
            chunks = re.split(r"node--type-event", r.text)[1:]
            if not chunks:
                break
            for chunk in chunks:
                card = _parse_card(chunk)
                if card and card["event_id"] not in seen:
                    seen.add(card["event_id"])
                    events.append(card)
    events.sort(key=lambda e: e.get("start") or "")
    return events


async def all_events() -> list[dict]:
    now = datetime.now()
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
                        ["title", "event_types", "location_address"]).lower()
    return needle in haystack


def _in_window(start: str | None, date_from: str | None, date_to: str | None) -> bool:
    if not start:
        return False
    if date_from and start < date_from:
        return False
    if date_to and start > date_to:
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
    # Park events are scattered citywide with no per-event community area, so a
    # neighborhood filter can't be applied reliably — return none when one is set.
    if neighborhood:
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
