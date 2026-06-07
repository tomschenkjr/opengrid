"""
/search/smart — classifies query as POI or data, routes accordingly.
"""

import traceback
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.ai_search import smart_search, filtered_search, search_records

router = APIRouter()


class Bounds(BaseModel):
    minLat: float
    minLon: float
    maxLat: float
    maxLon: float


class CurrentLocation(BaseModel):
    lat: float
    lon: float


class SearchRequest(BaseModel):
    query: str
    bounds: Bounds | None = None
    current_location: CurrentLocation | None = None


class FilteredRequest(BaseModel):
    datasets: list[str]
    timeframe: str = "all"
    community_area: int | None = None
    bounds: Bounds | None = None


@router.post("/search/smart")
async def smart_search_endpoint(body: SearchRequest):
    try:
        return await smart_search(
            body.query,
            bounds=body.bounds.model_dump() if body.bounds else None,
            current_location=body.current_location.model_dump() if body.current_location else None,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class RecordsRequest(BaseModel):
    dataset: str
    timeframe: str = "all"
    community_area: int | None = None
    soql_where: str | None = None
    offset: int = 0
    limit: int = 200
    order: str = "newest"


@router.post("/search/records")
async def records_endpoint(body: RecordsRequest):
    try:
        return await search_records(
            dataset=body.dataset, timeframe=body.timeframe,
            community_area=body.community_area, soql_where=body.soql_where,
            offset=body.offset, limit=body.limit, order=body.order,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/filtered")
async def filtered_search_endpoint(body: FilteredRequest):
    try:
        return await filtered_search(
            datasets=body.datasets,
            timeframe=body.timeframe,
            community_area=body.community_area,
            bounds=body.bounds.model_dump() if body.bounds else None,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
