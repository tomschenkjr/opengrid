"""
/geography/* — Chicago geographic reference data for the frontend.
"""
from fastapi import APIRouter

from services.geography import COMMUNITY_AREAS

router = APIRouter()


@router.get("/geography/community-areas")
async def community_areas():
    """
    Return all 77 Chicago community areas as {number, name}, sorted by name.
    Used to populate the neighborhood filter chiclet.
    """
    return [
        {"number": num, "name": name.title()}
        for name, num in sorted(COMMUNITY_AREAS.items())
    ]
