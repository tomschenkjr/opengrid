"""
/events/* — normalized announcement and event feeds.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Query

from services import library_events, sports_events, navypier_events, parkdistrict_events

router = APIRouter()

# event-id prefix → the source that owns it (for single-event detail lookups).
_DETAIL_SOURCES = [
    ("spt-", sports_events),
    ("np-", navypier_events),
    ("cpd-", parkdistrict_events),
]

# named source → service module (for the feed's source-filter tabs).
_FEED_SOURCES = {
    "library": library_events,
    "sports": sports_events,
    "navypier": navypier_events,
    "parkdistrict": parkdistrict_events,
}


@router.get("/events/library")
async def cpl_library_events(
    event_id: str | None = Query(None),
    q: str | None = Query(None),
    library: str | None = Query(None),
    neighborhood: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(200, ge=1, le=6000),
):
    """Upcoming Chicago Public Library events from City of Chicago Socrata."""
    try:
        rows = await library_events.events(
            event_id=event_id,
            q=q,
            library=library,
            neighborhood=neighborhood,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        return {"source": "Chicago Public Library Events", "count": len(rows), "events": rows}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Library events unavailable: {e}")


@router.get("/events/sports")
async def sports_home_games(
    event_id: str | None = Query(None),
    q: str | None = Query(None),
    team: str | None = Query(None),
    neighborhood: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(200, ge=1, le=600),
):
    """Upcoming home games for Chicago pro teams (Cubs, White Sox, Bulls, Blackhawks,
    Fire, Sky) from ESPN, normalized to the shared event shape."""
    try:
        rows = await sports_events.events(
            event_id=event_id,
            q=q,
            team=team,
            neighborhood=neighborhood,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        return {"source": "Chicago Sports", "count": len(rows), "events": rows}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Sports schedule unavailable: {e}")


@router.get("/events/feed")
async def combined_feed(
    event_id: str | None = Query(None),
    q: str | None = Query(None),
    source: str | None = Query(None),
    neighborhood: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(300, ge=1, le=1000),
):
    """Unified Announcements & Events feed: Chicago Public Library, pro-sports home
    games, Navy Pier, and Chicago Park District, merged and sorted by start time.

    - event_id  → single-event detail, routed to its owning source by id prefix.
    - source    → restrict the feed to one source (the page's filter tabs); library's
                  volume otherwise crowds the smaller sources out of a merged view.
    A failure in any one source is skipped so the rest of the feed still loads.
    """
    common = dict(q=q, neighborhood=neighborhood, date_from=date_from, date_to=date_to, limit=limit)

    # Detail lookup: route to the one source that owns this id.
    if event_id:
        owner = next((s for pfx, s in _DETAIL_SOURCES if event_id.startswith(pfx)), library_events)
        try:
            rows = await owner.events(event_id=event_id, limit=1)
        except Exception:
            rows = []
        return {"source": "Chicago Events", "count": len(rows), "events": rows}

    # Single-source view (filter tab), or all sources merged.
    services = ([_FEED_SOURCES[source]] if source in _FEED_SOURCES
                else list(_FEED_SOURCES.values()))
    results = await asyncio.gather(*[svc.events(**common) for svc in services],
                                   return_exceptions=True)
    merged: list[dict] = []
    for r in results:
        if isinstance(r, list):
            merged.extend(r)
    merged.sort(key=lambda e: e.get("start") or "")
    return {"source": "Chicago Events", "count": len(merged), "events": merged[:limit]}
