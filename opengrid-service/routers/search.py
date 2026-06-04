"""
/search/smart — classifies query as POI or data, routes accordingly.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from services.ai_search import smart_search

router = APIRouter()


class Bounds(BaseModel):
    minLat: float
    minLon: float
    maxLat: float
    maxLon: float


class SearchRequest(BaseModel):
    query: str
    bounds: Bounds | None = None


@router.post("/search/smart")
async def smart_search_endpoint(body: SearchRequest):
    return await smart_search(body.query, bounds=body.bounds.model_dump() if body.bounds else None)
