"""
Socrata SoDA API client using sodapy.

Credentials:
  SOCRATA_APP_TOKEN   — App Token (identifies the application, raises rate limits)
  SOCRATA_SECRET_TOKEN — Secret Token (used with App Token for Basic Auth)

Both are optional. With neither, requests are throttled. With only the App Token,
rate limits are raised. With both, requests use HTTP Basic Auth (App Token as
username, Secret Token as password) — required for write access.
"""

import os
from sodapy import Socrata

APP_TOKEN = os.getenv("SOCRATA_APP_TOKEN", "").strip() or None


def get_client(domain: str) -> Socrata:
    # sodapy sends APP_TOKEN as X-App-Token header automatically.
    # No Basic Auth needed for public read-only Socrata data.
    return Socrata(domain, APP_TOKEN, timeout=60)


def query_dataset(
    domain: str,
    dataset_id: str,
    where: str = None,
    limit: int = 500,
    order: str = None,
    offset: int = 0,
) -> list[dict]:
    with get_client(domain) as client:
        kwargs = {"limit": min(limit, 6000)}
        if where:
            kwargs["where"] = where
        if order:
            kwargs["order"] = order
        if offset:
            kwargs["offset"] = offset
        return client.get(dataset_id, **kwargs)


def count_rows(domain: str, dataset_id: str, where: str = None) -> int:
    """Total count(*) for a dataset under an optional WHERE clause."""
    with get_client(domain) as client:
        kwargs = {"select": "count(*) AS n"}
        if where:
            kwargs["where"] = where
        rows = client.get(dataset_id, **kwargs)
    try:
        return int(rows[0]["n"]) if rows else 0
    except (KeyError, ValueError, TypeError):
        return 0


def count_by(
    domain: str,
    dataset_id: str,
    group_field: str,
    where: str = None,
) -> list[dict]:
    """
    Aggregate: count(*) grouped by a field (for choropleths).
    Returns rows like [{"k": "<group value>", "n": "<count>"}, ...].
    """
    with get_client(domain) as client:
        kwargs = {
            "select": f"{group_field} AS k, count(*) AS n",
            "group": group_field,
            "limit": 5000,
        }
        if where:
            kwargs["where"] = where
        return client.get(dataset_id, **kwargs)
