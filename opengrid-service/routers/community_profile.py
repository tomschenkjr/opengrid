"""
/geography/community-areas/* — Community Trends profile data.

  - GET .../{number}/profile          → headline ACS indicators + citywide comparison.
  - GET .../{number}/profile/summary  → plain-language AI summary of the profile.
  - GET .../boundaries                → GeoJSON community-area outlines.
"""
import json
import traceback

from fastapi import APIRouter, HTTPException
from anthropic import Anthropic

from services import census_acs, geography

router = APIRouter()
client = Anthropic()


def _round_value(value):
    if isinstance(value, (int, float)):
        return round(value, 1)
    return value


def _fact_from_item(item: dict) -> list[dict]:
    kind = item.get("type")
    if kind == "stat":
        return [{
            "label": item.get("label"),
            "value": _round_value(item.get("value")),
            "format": item.get("format"),
            "unit": item.get("unit"),
            "period": item.get("period"),
        }]
    if kind == "stat_list":
        return [
            {
                "label": s.get("label"),
                "value": _round_value(s.get("value")),
                "format": s.get("format"),
                "unit": s.get("unit"),
                "period": s.get("period"),
            }
            for s in item.get("items", [])
        ]
    if kind == "box_whisker":
        return [{
            "label": item.get("label"),
            "value": _round_value(item.get("value")),
            "format": item.get("format"),
            "distribution": {
                k: _round_value(v)
                for k, v in (item.get("distribution") or {}).items()
            },
        }]
    return []


def _profile_facts(profile: dict) -> dict:
    facts = {
        "community_area": {
            "number": profile.get("number"),
            "name": profile.get("name"),
            "acs_year": profile.get("acs_year"),
        },
        "headline_kpis": [
            {
                "label": k.get("label"),
                "value": _round_value(k.get("value")),
                "citywide": _round_value(k.get("citywide")),
                "format": k.get("format"),
            }
            for k in profile.get("kpis", [])
        ],
        "citywide_comparison": [
            {
                "label": c.get("label"),
                "value": _round_value(c.get("value")),
                "citywide": _round_value(c.get("citywide")),
                "format": c.get("format"),
            }
            for c in profile.get("comparison", [])
        ],
        "section_stats": [],
    }

    for section in profile.get("sections", []):
        for group in section.get("groups", []):
            for item in group.get("items", []):
                for fact in _fact_from_item(item):
                    if fact.get("value") is None:
                        continue
                    facts["section_stats"].append({
                        "section": section.get("title"),
                        "group": group.get("title"),
                        **fact,
                    })

    facts["section_stats"] = facts["section_stats"][:80]
    return facts


def _fallback_summary(profile: dict) -> str:
    name = profile.get("name") or "this community area"
    kpis = {k.get("id"): k for k in profile.get("kpis", [])}
    pieces = []
    pop = kpis.get("population", {}).get("value")
    rent = kpis.get("median_rent", {}).get("value")
    renter = kpis.get("renter_pct", {}).get("value")
    age = kpis.get("median_age", {}).get("value")
    if pop is not None:
        pieces.append(f"population is about {int(round(pop)):,}")
    if rent is not None:
        pieces.append(f"median rent is about ${int(round(rent)):,}")
    if renter is not None:
        pieces.append(f"{round(renter, 1)}% of occupied units are renter-occupied")
    if age is not None:
        pieces.append(f"median age is {round(age, 1)}")
    if not pieces:
        return f"{name} has a loaded Community Trends profile, but a summary is unavailable right now."
    return f"{name} shows {', '.join(pieces)}. Compare the cards below for how those measures stack up against citywide values."


@router.get("/geography/community-areas/boundaries")
async def community_area_boundaries():
    """GeoJSON FeatureCollection of all community-area boundaries with name + number.

    Rendered directly by a custom Leaflet layer on the frontend (not the dataset/results
    pipeline), so it intentionally does not carry meta.view.columns metadata.
    """
    features = []
    for number, geom in geography.all_community_area_geojson().items():
        name = (geography.community_area_name(number) or "").title()
        features.append({
            "type": "Feature",
            "properties": {"number": number, "name": name},
            "geometry": geom,
        })
    features.sort(key=lambda f: f["properties"]["name"])
    return {"type": "FeatureCollection", "features": features}


@router.get("/geography/community-areas/{number}/profile")
async def community_area_profile(number: int):
    """Headline ACS indicators and citywide comparison for one community area."""
    if not geography.community_area_name(number):
        raise HTTPException(status_code=404, detail=f"Unknown community area: {number}")
    profile = census_acs.community_profile(number)
    profile["boundary"] = geography.get_community_area_geojson(number)
    return profile


@router.get("/geography/community-areas/{number}/profile/summary")
async def community_area_profile_summary(number: int):
    """AI-generated plain-language summary of the visible Community Trends profile."""
    if not geography.community_area_name(number):
        raise HTTPException(status_code=404, detail=f"Unknown community area: {number}")

    profile = census_acs.community_profile(number)
    if not profile.get("available"):
        return {"summary": profile.get("message") or "Community profile data is unavailable."}

    facts = _profile_facts(profile)
    prompt = f"""Write a plain-language Community Trends summary for this Chicago community area.

Use only the facts in the JSON. Mention 3-5 notable patterns, especially differences from citywide values when available. Keep it to 2 short paragraphs, no bullets, no markdown, no invented causes.

Facts:
{json.dumps(facts, separators=(",", ":"))}
"""
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=260,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = resp.content[0].text.strip()
        return {"summary": summary or _fallback_summary(profile)}
    except Exception:
        traceback.print_exc()
        return {"summary": _fallback_summary(profile)}
