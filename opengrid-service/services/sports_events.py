"""
Chicago pro-sports home-game event feed.

One source for every local team via ESPN's public schedule API
(site.api.espn.com), normalized to the same event shape as services.library_events
so the Announcements & Events page renders them in the same feed.

Teams are a registry (TEAMS): adding another is a one-line entry. Only upcoming/live
HOME games are returned; finished games and off-season teams fall away naturally.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from services import geography

_ESPN = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{espn_id}/schedule"

# Home venues (fixed address/coords beat ESPN's venue payload, which lacks lat/lon).
_WRIGLEY = {"location_name": "Wrigley Field", "location_address": "1060 W Addison St, Chicago, IL",
            "location_zip": "60613", "lat": 41.9484, "lon": -87.6553, "community_area": 6}
_RATE = {"location_name": "Rate Field", "location_address": "333 W 35th St, Chicago, IL",
         "location_zip": "60616", "lat": 41.8299, "lon": -87.6338, "community_area": 34}
_UNITED_CENTER = {"location_name": "United Center", "location_address": "1901 W Madison St, Chicago, IL",
                  "location_zip": "60612", "lat": 41.8807, "lon": -87.6742, "community_area": 28}
_SOLDIER_FIELD = {"location_name": "Soldier Field", "location_address": "1410 Special Olympics Dr, Chicago, IL",
                  "location_zip": "60605", "lat": 41.8623, "lon": -87.6167, "community_area": 33}
_WINTRUST = {"location_name": "Wintrust Arena", "location_address": "200 E Cermak Rd, Chicago, IL",
             "location_zip": "60616", "lat": 41.8531, "lon": -87.6270, "community_area": 33}

# Team registry. key → metadata. Add a team by adding a row.
TEAMS: dict[str, dict] = {
    "cubs":       {"name": "Chicago Cubs",       "badge": "Cubs",       "color": "#0e3386",
                   "sport": "baseball",   "league": "mlb",   "espn_id": "16",  "venue": _WRIGLEY,       "league_label": "MLB Baseball"},
    "white-sox":  {"name": "Chicago White Sox",  "badge": "White Sox",  "color": "#27251f",
                   "sport": "baseball",   "league": "mlb",   "espn_id": "4",   "venue": _RATE,          "league_label": "MLB Baseball"},
    "bulls":      {"name": "Chicago Bulls",      "badge": "Bulls",      "color": "#ce1141",
                   "sport": "basketball", "league": "nba",   "espn_id": "4",   "venue": _UNITED_CENTER, "league_label": "NBA Basketball"},
    "blackhawks": {"name": "Chicago Blackhawks", "badge": "Blackhawks", "color": "#cf0a2c",
                   "sport": "hockey",     "league": "nhl",   "espn_id": "4",   "venue": _UNITED_CENTER, "league_label": "NHL Hockey"},
    "fire":       {"name": "Chicago Fire FC",    "badge": "Fire",       "color": "#c8102e",
                   "sport": "soccer",     "league": "usa.1", "espn_id": "182", "venue": _SOLDIER_FIELD, "league_label": "MLS Soccer",
                   # ESPN's soccer team schedule defaults to completed matches; this returns upcoming fixtures.
                   "params": {"fixture": "true"}},
    "sky":        {"name": "Chicago Sky",        "badge": "Sky",        "color": "#418fde",
                   "sport": "basketball", "league": "wnba",  "espn_id": "19",  "venue": _WINTRUST,      "league_label": "WNBA Basketball"},
}

# Typical game length by sport, for a sensible end time.
_DURATION = {
    "baseball": timedelta(hours=3, minutes=15),
    "basketball": timedelta(hours=2, minutes=30),
    "hockey": timedelta(hours=2, minutes=45),
    "soccer": timedelta(hours=2),
}

_CACHE_TTL = timedelta(hours=6)
_events_cache: dict = {"data": None, "expires": None}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for candidate in (value.replace("Z", "+00:00"), value):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _event_link(event: dict) -> str | None:
    links = event.get("links") or []
    for link in links:
        rels = link.get("rel") or []
        if link.get("href") and ("summary" in rels or "gamecast" in rels):
            return link["href"]
    return links[0]["href"] if links and links[0].get("href") else None


def _normalize(event: dict, team_key: str, team: dict) -> dict | None:
    comps = event.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    competitors = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    home = competitors.get("home", {})
    away = competitors.get("away", {})

    # Only this team's HOME games.
    if str(home.get("team", {}).get("id")) != str(team["espn_id"]):
        return None

    status = (comp.get("status") or {}).get("type", {}) or event.get("status", {}).get("type", {})
    state = status.get("state")            # pre | in | post
    if state == "post":
        return None                        # finished — not an upcoming event

    opponent = away.get("team", {}).get("displayName") or "TBD"
    start = event.get("date")
    start_dt = _parse_dt(start)
    end = None
    if start_dt:
        end = (start_dt + _DURATION.get(team["sport"], timedelta(hours=3))).isoformat()

    venue = team["venue"]
    status_label = status.get("description") or ""
    desc = (f"The {team['name']} host the {opponent} at {venue['location_name']}."
            + (f" {status_label}." if status_label and status_label.lower() != "scheduled" else ""))
    game_id = event.get("id")

    return {
        "id": f"spt-{team_key}-{game_id}",
        "event_id": f"spt-{team_key}-{game_id}",
        "title": f"{team['name'].replace('Chicago ', '')} vs. {opponent}",
        "description": desc,
        "summary": desc[:260],
        "event_types": f"Sports; {team['league_label']}",
        "event_audiences": "All ages",
        "event_languages": None,
        "event_page_url": _event_link(event),
        "location_name": venue["location_name"],
        "location_key": "",
        "location_details": team["name"],
        "location_address": venue["location_address"],
        "location_zip": venue["location_zip"],
        "start": start,
        "end": end,
        "day_of_the_week": start_dt.strftime("%A") if start_dt else None,
        "featured": False,
        "cancelled": False,
        "recurring": False,
        "registration_closed": False,
        "registration_status": None,
        "registration_starts": None,
        "registration_ends": None,
        "lat": venue["lat"],
        "lon": venue["lon"],
        "community_area": venue["community_area"],
        "team": team_key,
        "source": f"{team['name']} (ESPN)",
        "category": "Sports",
        "badge": team["badge"],
        "badge_color": team["color"],
    }


async def _fetch_team(http: httpx.AsyncClient, team_key: str, team: dict) -> list[dict]:
    url = _ESPN.format(sport=team["sport"], league=team["league"], espn_id=team["espn_id"])
    try:
        r = await http.get(url, params=team.get("params"))
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []  # one team failing must not sink the rest
    out = []
    for event in data.get("events", []):
        normalized = _normalize(event, team_key, team)
        if normalized:
            out.append(normalized)
    return out


async def _fetch_all() -> list[dict]:
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "opengrid-service/1.0"}) as http:
        results = await asyncio.gather(*[
            _fetch_team(http, key, team) for key, team in TEAMS.items()
        ])
    games = [g for team_games in results for g in team_games]
    games.sort(key=lambda e: e.get("start") or "")
    return games


async def all_events() -> list[dict]:
    now = datetime.now(timezone.utc)
    if _events_cache["data"] and _events_cache["expires"] and now < _events_cache["expires"]:
        return _events_cache["data"]
    games = await _fetch_all()
    _events_cache["data"] = games
    _events_cache["expires"] = now + _CACHE_TTL
    return games


def _matches_text(event: dict, text: str | None) -> bool:
    if not text:
        return True
    needle = text.lower().strip()
    haystack = " ".join(str(event.get(k) or "") for k in [
        "title", "description", "event_types", "location_name",
    ]).lower()
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
    team: str | None = None,
    neighborhood: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
) -> list[dict]:
    # Neighborhood filter: keep only teams whose venue is in that community area.
    allowed_cas: set[int] | None = None
    if neighborhood:
        number, _official = geography.resolve_community_area(neighborhood)
        allowed_cas = {number} if number else set()

    games = await all_events()
    out = []
    for game in games:
        if event_id and game.get("event_id") != event_id:
            continue
        if team and game.get("team") != team:
            continue
        if allowed_cas is not None and game.get("community_area") not in allowed_cas:
            continue
        if not event_id and not _in_window(game.get("start"), date_from, date_to):
            continue
        if not _matches_text(game, q):
            continue
        out.append(game)
        if len(out) >= limit:
            break
    return out
