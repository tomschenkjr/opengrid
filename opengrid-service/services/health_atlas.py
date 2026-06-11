"""
Chicago Health Atlas indicators for Community Trends.

The Health Atlas API exposes metadata, coverage, and data separately. This
module keeps the Community Trends integration topic-driven: each configured
metric resolves its latest neighborhood coverage, fetches the corresponding
data, joins geography IDs to community-area names, and caches the result.
"""

from datetime import datetime, timedelta, timezone

import httpx

from services import geography

_BASE_URL = "https://chicagohealthatlas.org/api/v1"
_DATA_URL = f"{_BASE_URL}/data/"
_GEOS_URL = f"{_BASE_URL}/geographies/"
_COVERAGE_URL = f"{_BASE_URL}/coverage"
_LAYER = "neighborhood"
_CACHE_TTL = timedelta(hours=6)

_cache: dict | None = None
_cache_at: datetime | None = None


# The catalog does not currently expose Health Atlas neighborhood topics for:
# Voter Turnout, GHG Emissions from Residential Electricity,
# GHG Emissions from Non-Residential Electricity, GHG Emissions from Residential
# Natural Gas, GHG Emissions from Non-Residential Natural Gas, or a full commute
# mode distribution. Those are intentionally omitted instead of rendering empty
# cards.
_METRICS: tuple[dict, ...] = (
    {
        "id": "hardship_index",
        "topic": "HDX",
        "label": "Hardship Index",
        "format": "decimal",
    },
    {
        "id": "community_belonging",
        "topic": "HCSCBP",
        "label": "Community Belonging Rate",
        "format": "percent",
    },
    {
        "id": "rent_burdened",
        "topic": "RBU",
        "label": "Rent Burdened Households",
        "format": "percent",
    },
    {
        "id": "vacant_housing",
        "topic": "VAC",
        "label": "Vacant Housing Units",
        "format": "percent",
    },
    {
        "id": "eviction_filing_rate",
        "topic": "EVF",
        "label": "Eviction Filing Rate",
        "format": "decimal",
        "unit": "filings per 100 renter households",
    },
    {
        "id": "overall_health_status",
        "topic": "HCSOHSP",
        "label": "Overall Health Status",
        "format": "percent",
    },
    {
        "id": "neighborhood_safety",
        "topic": "HCSNSP",
        "label": "Neighborhood Safety Rate (Perception)",
        "format": "percent",
    },
    {
        "id": "life_expectancy",
        "topic": "VRLE",
        "label": "Life Expectancy",
        "format": "decimal",
        "unit": "years",
    },
    {
        "id": "fatal_opioid_overdose",
        "topic": "MEODR",
        "label": "Fatal Opioid Overdose",
        "format": "decimal",
        "unit": "per 100,000 population",
    },
    {
        "id": "infant_mortality",
        "topic": "VRIMR",
        "label": "Infant Mortality Rate",
        "format": "decimal",
        "unit": "per 1,000 live births",
    },
    {
        "id": "gun_related_homicide",
        "topic": "VRFIR",
        "label": "Gun-Related Homicide",
        "format": "decimal",
        "unit": "per 100,000 population",
    },
    {
        "id": "unmet_mental_health_need",
        "topic": "HCSUMHAP",
        "label": "Unmet Need for Mental Health Treatment Rate",
        "format": "percent",
    },
    {
        "id": "traffic_crashes",
        "topic": "TRC",
        "label": "Traffic Crashes",
        "format": "count",
    },
    {
        "id": "broadband_access",
        "topic": "WWW",
        "label": "Broadband Access",
        "format": "percent",
    },
    {
        "id": "walkability",
        "topic": "EKW",
        "label": "Neighborhood Walkability Score",
        "format": "decimal",
    },
    {
        "id": "active_transportation",
        "topic": "ACT",
        "label": "Active Transportation to Work",
        "format": "percent",
    },
    {
        "id": "mean_commute_time",
        "topic": "TRV",
        "label": "Mean Commute Time",
        "format": "decimal",
        "unit": "minutes",
    },
    {
        "id": "walk_to_transit",
        "topic": "HCSWTSP",
        "label": "Ease of Walking to a Transit Stop",
        "format": "percent",
    },
)

_METRIC_BY_ID = {m["id"]: m for m in _METRICS}

_SECTION_CONFIGS: tuple[dict, ...] = (
    {
        "id": "civic_engagement",
        "title": "Civic Engagement",
        "group_id": "civic_health_atlas",
        "group_title": "",
        "metrics": ("community_belonging",),
    },
    {
        "id": "public_health_safety",
        "title": "Public Health and Safety",
        "group_id": "public_health_safety_health_atlas",
        "group_title": "",
        "metrics": (
            "overall_health_status",
            "neighborhood_safety",
            "life_expectancy",
            "fatal_opioid_overdose",
            "infant_mortality",
            "gun_related_homicide",
            "unmet_mental_health_need",
        ),
    },
    {
        "id": "transportation_infrastructure",
        "title": "Transportation & Infrastructure",
        "group_id": "transportation_infrastructure_health_atlas",
        "group_title": "",
        "metrics": (
            "traffic_crashes",
            "broadband_access",
            "walkability",
            "active_transportation",
            "mean_commute_time",
            "walk_to_transit",
        ),
    },
)


def _area_key(value) -> str:
    return str(value or "").strip().upper().replace("'", "")


def _num(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_name(value: str) -> str:
    return str(value or "").replace(" (Chicago, IL)", "").strip()


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return values[lo] + (values[hi] - values[lo]) * frac


def _summary(values: list[float]) -> dict:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return {"min": None, "q1": None, "median": None, "q3": None, "max": None, "mean": None}
    return {
        "min": vals[0],
        "q1": _percentile(vals, 0.25),
        "median": _percentile(vals, 0.5),
        "q3": _percentile(vals, 0.75),
        "max": vals[-1],
        "mean": sum(vals) / len(vals),
    }


def _latest_neighborhood_coverage(http: httpx.Client, topic: str) -> dict | None:
    resp = http.get(f"{_COVERAGE_URL}/{topic}/")
    resp.raise_for_status()
    coverages = resp.json().get("coverages", {})
    rows = coverages.get(_LAYER) or []
    return rows[0] if rows else None


def _fetch_metric(http: httpx.Client, metric: dict, names_by_geoid: dict[str, str]) -> dict | None:
    coverage = _latest_neighborhood_coverage(http, metric["topic"])
    if not coverage:
        return None

    params = {
        "topic": metric["topic"],
        "population": coverage.get("population", ""),
        "period": coverage.get("period", ""),
        "layer": _LAYER,
        "limit": 1000,
    }
    resp = http.get(_DATA_URL, params=params)
    resp.raise_for_status()

    values_by_area: dict[str, float] = {}
    values: list[float] = []
    for row in resp.json().get("results", []):
        name = names_by_geoid.get(row.get("g"))
        value = _num(row.get("v"))
        if not name or value is None:
            continue
        values_by_area[_area_key(name)] = value
        values.append(value)

    return {
        "topic": metric["topic"],
        "period": coverage.get("period", ""),
        "population": coverage.get("population", ""),
        "values_by_area": values_by_area,
        "summary": _summary(values),
    }


def _load_cache() -> dict:
    global _cache, _cache_at
    now = datetime.now(timezone.utc)
    if _cache is not None and _cache_at and now - _cache_at < _CACHE_TTL:
        return _cache

    with httpx.Client(timeout=60, follow_redirects=True) as http:
        geos = http.get(
            _GEOS_URL,
            params={"layer": _LAYER, "offset": 0, "limit": 1000},
        )
        geos.raise_for_status()

        names_by_geoid = {
            row.get("geoid"): _clean_name(row.get("name", ""))
            for row in geos.json().get("results", [])
            if row.get("layer") == _LAYER and row.get("geoid")
        }

        metrics = {}
        for metric in _METRICS:
            try:
                fetched = _fetch_metric(http, metric, names_by_geoid)
                if fetched:
                    metrics[metric["id"]] = fetched
            except Exception as e:
                print(f"Health Atlas metric {metric['topic']} unavailable: {e}")

    _cache = {"metrics": metrics}
    _cache_at = now
    return _cache


def _community_name(number: int) -> str | None:
    return geography.community_area_name(number)


def _metric_item(metric_id: str, area_name: str) -> dict | None:
    metric = _METRIC_BY_ID.get(metric_id)
    data = _load_cache().get("metrics", {}).get(metric_id)
    if not metric or not data:
        return None

    value = data.get("values_by_area", {}).get(_area_key(area_name))
    return {
        "type": "stat",
        "id": metric_id,
        "label": metric["label"],
        "value": round(value, 1) if value is not None else None,
        "format": metric.get("format", "decimal"),
        "unit": metric.get("unit"),
        "period": data.get("period"),
        "topic": data.get("topic"),
    }


def _metric_group(number: int, group_id: str, title: str, metric_ids: tuple[str, ...]) -> dict | None:
    name = _community_name(number)
    if not name:
        return None

    items = [item for mid in metric_ids if (item := _metric_item(mid, name))]
    if not items:
        return None
    return {"id": group_id, "title": title, "items": items}


def hardship_group(number: int) -> dict | None:
    name = _community_name(number)
    if not name:
        return None

    data = _load_cache().get("metrics", {}).get("hardship_index")
    if not data:
        return None

    value = data["values_by_area"].get(_area_key(name))
    if value is None:
        return None

    return {
        "id": "hardship_index",
        "title": "Hardship Index",
        "items": [
            {
                "type": "stat",
                "label": "Hardship Index",
                "value": round(value, 1),
                "format": "decimal",
                "period": data.get("period"),
                "topic": data.get("topic"),
            },
            {
                "type": "box_whisker",
                "label": "Compared with Chicago community areas",
                "format": "decimal",
                "value": round(value, 1),
                "distribution": {
                    k: (round(v, 1) if v is not None else None)
                    for k, v in data["summary"].items()
                },
            },
        ],
    }


def housing_group(number: int) -> dict | None:
    return _metric_group(
        number,
        "health_atlas_housing",
        "Housing Indicators",
        ("rent_burdened", "vacant_housing", "eviction_filing_rate"),
    )


def community_sections(number: int) -> list[dict]:
    sections: list[dict] = []
    for section in _SECTION_CONFIGS:
        group = _metric_group(
            number,
            section["group_id"],
            section["group_title"],
            section["metrics"],
        )
        if group:
            sections.append({
                "id": section["id"],
                "title": section["title"],
                "groups": [group],
            })
    return sections
