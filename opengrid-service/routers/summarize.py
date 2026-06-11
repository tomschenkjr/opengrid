"""
/search/summarize — plain-language summary of search results via Claude Haiku.

Receives a query string, dataset name, total count, and a sample of record
properties; returns a one-sentence summary and an array of key phrases to
highlight in the UI.
"""

import json
import re
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from anthropic import Anthropic

router = APIRouter()
client = Anthropic()


class SummarizeRequest(BaseModel):
    query: str
    dataset_name: str
    total_count: int
    sample_records: list[dict]


_CHICAGO_TZ = ZoneInfo("America/Chicago")


def _today_label() -> str:
    return datetime.now(_CHICAGO_TZ).strftime("%A, %B %-d, %Y")


def _marine_payload(rec: dict) -> dict:
    raw = rec.get("marine_raw_payload")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except (TypeError, json.JSONDecodeError):
            pass
    return {
        "headline": rec.get("summary"),
        "risk_level": rec.get("risk_level"),
        "zone_id": rec.get("zone_id"),
        "alerts_first": {
            "message": rec.get("marine_alert_summary"),
            "formatted": rec.get("alerts"),
        },
        "marine_forecast_baseline": {
            "wind_kt": {"text": rec.get("forecast_wind")},
            "waves_ft": {"text": rec.get("forecast_waves")},
        },
        "wind_assessment": {"category": rec.get("wind_category")},
        "wave_assessment": {"category": rec.get("wave_category")},
        "cautions": rec.get("cautions"),
        "llm_briefing_context": rec.get("marine_summary_context"),
        "observations": {
            k: v for k, v in rec.items()
            if k.startswith("obs_") and v not in (None, "")
        },
    }


def _is_forecast_data(sample: list[dict]) -> bool:
    """Detect marine/weather forecast records from raw or structured provider data."""
    if not sample:
        return False
    rec = sample[0]
    return bool(
        rec.get("conditions")
        or rec.get("marine_raw_payload")
        or rec.get("marine_summary_context")
        or (
            rec.get("title") == "Lake Conditions"
            and (rec.get("risk_level") or rec.get("forecast_wind") or rec.get("forecast_waves"))
        )
    )


def _build_forecast_prompt(query: str, dataset_name: str, sample: list[dict]) -> str:
    rec = sample[0] if sample else {}
    if rec.get("marine_raw_payload") or rec.get("marine_summary_context") or rec.get("title") == "Lake Conditions":
        marine_payload = _marine_payload(rec)
        payload_text = json.dumps(marine_payload, separators=(",", ":"))
        return f"""Write a plain-English Chicago sailing briefing from this Chicago Marine Knowledge response.

Query: "{query}"
Source: {dataset_name}
Today in Chicago: {_today_label()}
Marine context JSON:
{payload_text}

Rules:
- Write 3-5 short sentences, no more than 130 words total
- Answer the user's time period first. If they ask about "today", describe today/late afternoon before tonight or tomorrow.
- Read alert/advisory timing carefully. If an advisory starts tomorrow or later, do not say conditions are unsafe today because of it; call it out as a future period to avoid.
- If an advisory is in effect during the requested period, name it and explain the practical impact for sailors or boaters.
- Include concrete wind and wave details from the NOAA forecast and one important current observation when available.
- Mention thunderstorms, source limitations, or stale readings only if they materially affect the sailing decision.
- Do not invent alert timing, wind, waves, or observations. Do not flatten different days into one go/no-go answer.

Respond with JSON only — no markdown, no explanation:
{{"summary": "...", "highlights": ["phrase1", "phrase2", "phrase3"]}}
highlights = 3-5 key phrases worth visual emphasis, such as today's wind, waves, future advisory period, storm risk, or important observations."""

    conditions_text = rec.get("conditions", "No forecast data available")
    return f"""Summarize this marine or weather forecast in 2-3 short plain-English sentences.

Query: "{query}"
Source: {dataset_name}
Forecast:
{conditions_text}

Rules:
- No more than 90 words total
- Lead with the most important condition: wind speed/direction, wave height, or any active advisory
- Include specifics where present: knots, feet, visibility, temperature
- If warnings or advisories are active, name them and explain the practical boating impact
- Write for a sailor or boater deciding whether to go out on Lake Michigan

Respond with JSON only — no markdown, no explanation:
{{"summary": "...", "highlights": ["phrase1", "phrase2", "phrase3"]}}
highlights = 3-5 key conditions worth visual emphasis (wind speed, wave height, alert types, temperatures)."""


def _build_tabular_prompt(query: str, dataset_name: str, total_count: int, sample: list[dict]) -> str:
    date_fields = ("created_date", "date", "inspection_date", "issue_date", "creation_date")
    dates = []
    for rec in sample:
        for f in date_fields:
            if rec.get(f):
                dates.append(str(rec[f])[:10])
                break
    date_note = ""
    if dates:
        dates.sort()
        date_note = f"Date range in sample: {dates[0]} to {dates[-1]}\n"

    sample_json = json.dumps(sample[:30], separators=(",", ":"))

    return f"""Summarize these Chicago open data search results in a single plain-English sentence.

Query: "{query}"
Dataset: {dataset_name}
Total matching records: {total_count}
{date_note}Sample records (properties only): {sample_json}

Rules:
- One sentence only (two short clauses at most)
- Include the exact record count
- Mention the neighborhood or area from the query
- Name specific patterns visible in the data: top request/crime type, busiest street or intersection, open vs closed ratio, or date concentration
- Write for a Chicago resident, not a data analyst

Respond with JSON only — no markdown, no explanation:
{{"summary": "...", "highlights": ["phrase1", "phrase2", "phrase3"]}}
highlights = 2-4 key phrases from the summary worth visual emphasis (counts, locations, types/categories)."""


def _build_prompt(query: str, dataset_name: str, total_count: int, sample: list[dict]) -> str:
    if _is_forecast_data(sample):
        return _build_forecast_prompt(query, dataset_name, sample)
    return _build_tabular_prompt(query, dataset_name, total_count, sample)


@router.post("/search/summarize")
async def summarize_endpoint(body: SummarizeRequest):
    try:
        prompt = _build_prompt(
            body.query, body.dataset_name, body.total_count, body.sample_records
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        m = re.search(r"\{[\s\S]+\}", text)
        if m:
            return json.loads(m.group(0))
        return {"summary": text, "highlights": []}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
