from fastapi import APIRouter

router = APIRouter()


@router.get("/capabilities")
async def get_capabilities():
    return {"geoSpatialFiltering": True}
