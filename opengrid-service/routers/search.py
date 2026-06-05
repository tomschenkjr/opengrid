"""
/search/smart — classifies query as POI or data, routes accordingly.
"""

import traceback
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.ai_search import smart_search

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
