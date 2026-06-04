"""
/datasets endpoints — OpenGrid dataset listing and querying backed by Socrata.
"""

import json
import yaml
from pathlib import Path
from fastapi import APIRouter, HTTPException, Form
from typing import Optional
from services.query_translator import mongo_to_soql, geo_filter_to_soql
from services.socrata import query_dataset
from services.geojson_converter import rows_to_geojson

router = APIRouter()

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "datasets.yaml"
_datasets: list[dict] = []


def _load_datasets() -> list[dict]:
    global _datasets
    if not _datasets:
        with open(_CONFIG_PATH) as f:
            _datasets = yaml.safe_load(f).get("datasets", [])
    return _datasets


def _find_dataset(dataset_id: str) -> dict | None:
    return next((d for d in _load_datasets() if d["id"] == dataset_id), None)


@router.get("/datasets")
async def list_datasets():
    datasets = [d for d in _load_datasets() if not d.get("proximity_only")]
    return sorted(datasets, key=lambda d: d.get("displayName", ""))


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str):
    ds = _find_dataset(dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    return ds


@router.post("/datasets/{dataset_id}/query")
async def query_dataset_endpoint(
    dataset_id: str,
    q: Optional[str] = Form(None),
    n: Optional[int] = Form(500),
    s: Optional[str] = Form(None),
    opts: Optional[str] = Form(None),
):
    ds = _find_dataset(dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")

    # Parse the MongoDB filter object
    mongo_filter = {}
    if q:
        try:
            mongo_filter = json.loads(q)
        except json.JSONDecodeError:
            pass

    # Parse geo filter from opts
    geo_clause = ""
    if opts:
        try:
            opts_obj = json.loads(opts)
            geo_filter = opts_obj.get("geoFilter")
            if geo_filter:
                geo_clause = geo_filter_to_soql(geo_filter)
        except json.JSONDecodeError:
            pass

    # Build SOQL WHERE
    where_parts = []
    mongo_clause = mongo_to_soql(mongo_filter)
    if mongo_clause:
        where_parts.append(mongo_clause)
    if geo_clause:
        where_parts.append(geo_clause)
    where = " AND ".join(where_parts) if where_parts else None

    # Parse sort
    order = None
    if s:
        try:
            sort_obj = json.loads(s)
            # Convert {"date": -1} → "date DESC"
            parts = []
            for field, direction in sort_obj.items():
                parts.append(f"{field} {'DESC' if direction == -1 else 'ASC'}")
            order = ", ".join(parts)
        except (json.JSONDecodeError, AttributeError):
            pass

    rows = query_dataset(
        domain=ds["socrata_domain"],
        dataset_id=ds["socrata_dataset_id"],
        where=where,
        limit=min(n or 500, 6000),
        order=order,
    )

    return rows_to_geojson(
        rows,
        ds,
        lat_field=ds.get("lat_field", "latitude"),
        lon_field=ds.get("lon_field", "longitude"),
    )
