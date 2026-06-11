"""
Community-area economic development indicators from Chicago Socrata datasets.

Feeds the Community Trends profile with:
  - TIF RDA/IGA project count and approved funding by year
  - SBIF project count and incentive amount by approval year
"""

from datetime import datetime, timedelta, timezone

from services import geography
from services.socrata import query_dataset

_DOMAIN = "data.cityofchicago.org"
_TIF_DATASET = "mex4-ppfc"
_SBIF_DATASET = "etqr-sz5x"
_CACHE_TTL = timedelta(hours=6)

_cache: dict | None = None
_cache_at: datetime | None = None


def _num(value) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _year(value) -> int | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).year
    except ValueError:
        try:
            return int(str(value)[:4])
        except (TypeError, ValueError):
            return None


def _area_key(value) -> str:
    return str(value or "").strip().upper().replace("'", "")


def _series(points: dict[int, float]) -> list[dict]:
    return [
        {"label": str(year), "value": round(value, 2)}
        for year, value in sorted(points.items())
        if year
    ]


def _empty_area() -> dict:
    return {
        "tif_project_ids": set(),
        "tif_approved_by_year": {},
        "sbif_count": 0,
        "sbif_incentive_by_year": {},
    }


def _load_cache() -> dict:
    global _cache, _cache_at
    now = datetime.now(timezone.utc)
    if _cache is not None and _cache_at and now - _cache_at < _CACHE_TTL:
        return _cache

    by_area: dict[str, dict] = {}

    tif_rows = query_dataset(
        _DOMAIN,
        _TIF_DATASET,
        limit=6000,
    )
    for row in tif_rows:
        area = _area_key(row.get("community_area"))
        if not area:
            continue
        entry = by_area.setdefault(area, _empty_area())
        project_id = str(row.get("id") or "").strip()
        if project_id:
            entry["tif_project_ids"].add(project_id)
        year = _year(row.get("cdc_date"))
        if year:
            yearly = entry["tif_approved_by_year"]
            yearly[year] = yearly.get(year, 0.0) + _num(row.get("approved_amount"))

    sbif_rows = query_dataset(
        _DOMAIN,
        _SBIF_DATASET,
        limit=6000,
    )
    for row in sbif_rows:
        area = _area_key(row.get("community_area"))
        if not area:
            continue
        entry = by_area.setdefault(area, _empty_area())
        entry["sbif_count"] += 1
        year = _year(row.get("approval_date"))
        if year:
            yearly = entry["sbif_incentive_by_year"]
            yearly[year] = yearly.get(year, 0.0) + _num(row.get("incentive_amount"))

    _cache = by_area
    _cache_at = now
    return by_area


def community_section(number: int) -> dict | None:
    name = geography.community_area_name(number)
    if not name:
        return None

    entry = _load_cache().get(_area_key(name)) or _empty_area()

    return {
        "id": "economic_development",
        "title": "Economic Development",
        "groups": [
            {
                "id": "tif_projects",
                "title": "TIF Funded RDA and IGA Projects",
                "items": [
                    {
                        "type": "stat",
                        "label": "Total TIF projects (RDA and IGA)",
                        "value": len(entry["tif_project_ids"]),
                        "format": "count",
                    },
                    {
                        "type": "line",
                        "label": "Approved amount by year",
                        "format": "currency",
                        "points": _series(entry["tif_approved_by_year"]),
                    },
                ],
            },
            {
                "id": "sbif_projects",
                "title": "Small Business Improvement Funds (SBIF)",
                "items": [
                    {
                        "type": "stat",
                        "label": "SBIF projects approved",
                        "value": entry["sbif_count"],
                        "format": "count",
                    },
                    {
                        "type": "line",
                        "label": "Incentive amount by approval year",
                        "format": "currency",
                        "points": _series(entry["sbif_incentive_by_year"]),
                    },
                ],
            },
        ],
    }
