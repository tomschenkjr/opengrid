"""
/search/summarize — plain-language summary of search results via Claude Haiku.

Receives a query string, dataset name, total count, and a sample of record
properties; returns a one-sentence summary and an array of key phrases to
highlight in the UI.
"""

import json
import re
import traceback
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


def _is_forecast_data(sample: list[dict]) -> bool:
    """Detect marine/weather forecast records by presence of a 'conditions' field."""
    return bool(sample and sample[0].get("conditions"))


def _build_forecast_prompt(query: str, dataset_name: str, sample: list[dict]) -> str:
    conditions_text = sample[0].get("conditions", "No forecast data available")
    return f"""Summarize this marine or weather forecast in a single plain-English sentence.

Query: "{query}"
Source: {dataset_name}
Forecast:
{conditions_text}

Rules:
- One sentence only (two short clauses at most)
- Lead with the most important condition: wind speed/direction, wave height, or any active advisory
- Include specifics where present: knots, feet, visibility, temperature
- Note warnings or advisories if any are active
- Write for a sailor or boater deciding whether to go out on Lake Michigan

Respond with JSON only — no markdown, no explanation:
{{"summary": "...", "highlights": ["phrase1", "phrase2", "phrase3"]}}
highlights = 2-4 key conditions worth visual emphasis (wind speed, wave height, alert types, temperatures)."""


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
            max_tokens=300,
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
