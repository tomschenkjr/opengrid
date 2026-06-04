"""Stub saved-queries and groups endpoints."""

import yaml
from pathlib import Path
from fastapi import APIRouter

router = APIRouter()

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "datasets.yaml"


def _dataset_ids() -> list[str]:
    with open(_CONFIG_PATH) as f:
        return [d["id"] for d in yaml.safe_load(f).get("datasets", [])]


@router.get("/groups")
async def list_groups(q: str = None, n: int = 100):
    # Return a single public group with access to all configured datasets
    # and basic functions (Advanced Search but not Manage/admin)
    return [
        {
            "_id": {"$oid": "000000000000000000000001"},
            "groupId": "public",
            "name": "Public",
            "functions": ["Advanced Search"],
            "datasets": _dataset_ids(),
        }
    ]


@router.get("/queries")
async def list_queries():
    return []


@router.post("/queries")
async def create_query():
    return {}


@router.put("/queries/{query_id}")
async def update_query(query_id: str):
    return {}


@router.delete("/queries/{query_id}")
async def delete_query(query_id: str):
    return {}
