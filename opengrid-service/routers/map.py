"""
/map/* — scale-aware map representations (server-side aggregation).
"""
import traceback
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.ai_search import aggregate_search, decide_view

router = APIRouter()


class Bbox(BaseModel):
    minLat: float
    minLon: float
    maxLat: float
    maxLon: float


class AggregateRequest(BaseModel):
    dataset: str
    timeframe: str = "all"
    community_area: int | None = None
    soql_where: str | None = None


class ViewRequest(BaseModel):
    dataset: str
    timeframe: str = "all"
    community_area: int | None = None
    soql_where: str | None = None
    bbox: Bbox | None = None
    zoom: float = 11


@router.post("/map/aggregate")
async def aggregate_endpoint(body: AggregateRequest):
    """Community-area choropleth counts for a dataset + filter context."""
    try:
        return await aggregate_search(
            dataset_id=body.dataset,
            timeframe=body.timeframe,
            community_area=body.community_area,
            soql_where=body.soql_where,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/map/view")
async def view_endpoint(body: ViewRequest):
    """Viewport-aware representation: points / choropleth / heatmap by count + zoom."""
    try:
        return await decide_view(
            dataset=body.dataset,
            timeframe=body.timeframe,
            community_area=body.community_area,
            soql_where=body.soql_where,
            bbox=body.bbox.model_dump() if body.bbox else None,
            zoom=body.zoom,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
