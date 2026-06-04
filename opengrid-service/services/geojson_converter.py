"""
Converts Socrata JSON row arrays into OpenGrid-compatible GeoJSON FeatureCollections.
"""

import json


def rows_to_geojson(
    rows: list[dict],
    dataset_descriptor: dict,
    lat_field: str = "latitude",
    lon_field: str = "longitude",
) -> dict:
    """
    Convert a list of Socrata row dicts into an OpenGrid GeoJSON FeatureCollection.
    Returns the full structure expected by the OpenGrid frontend including meta.view.
    """
    # Only keep fields that have a column definition — OpenGrid errors on unknown fields
    defined_cols = {col["id"] for col in dataset_descriptor.get("columns", [])}

    features = []
    for row in rows:
        filtered = {k: v for k, v in row.items() if k in defined_cols}
        feature = _row_to_feature(filtered, lat_field, lon_field, row)
        if feature:
            features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "view": _build_view(dataset_descriptor)
        },
    }


def _row_to_feature(row: dict, lat_field: str, lon_field: str, raw_row: dict = None) -> dict | None:
    """Convert a single Socrata row to a GeoJSON Feature.
    row: filtered properties to include; raw_row: full row used for coordinate extraction."""
    src = raw_row if raw_row is not None else row
    lat = src.get(lat_field)
    lon = src.get(lon_field)

    # Socrata sometimes nests coordinates in a "location" object
    if (lat is None or lon is None) and "location" in src:
        loc = src["location"]
        if isinstance(loc, dict):
            lat = loc.get("latitude") or loc.get("lat")
            lon = loc.get("longitude") or loc.get("lon")
        elif isinstance(loc, str):
            try:
                parsed = json.loads(loc)
                lat = parsed.get("latitude")
                lon = parsed.get("longitude")
            except (json.JSONDecodeError, AttributeError):
                pass

    if lat is None or lon is None:
        return None

    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (ValueError, TypeError):
        return None

    # Skip records with 0,0 coordinates (Socrata geocoding failures)
    if lat_f == 0.0 and lon_f == 0.0:
        return None

    # Build properties — only the filtered column-defined fields
    properties = {k: v for k, v in row.items()}

    return {
        "type": "Feature",
        "id": row.get(":id") or row.get("_id") or None,
        "geometry": {
            "type": "Point",
            "coordinates": [lon_f, lat_f],  # GeoJSON: [longitude, latitude]
        },
        "properties": properties,
    }


def _build_view(descriptor: dict) -> dict:
    """Build the meta.view object OpenGrid needs to render columns and popups."""
    return {
        "id": descriptor.get("id"),
        "displayName": descriptor.get("displayName"),
        "options": descriptor.get("options", {}),
        "columns": descriptor.get("columns", []),
    }


def dynamic_rows_to_geojson(
    rows: list[dict],
    dataset_id: str,
    display_name: str,
    socrata_columns: list[dict],
) -> dict:
    """
    Build a GeoJSON FeatureCollection for AI search results where the dataset
    may not be in datasets.yaml. Column metadata comes from the Socrata catalog.
    """
    # Detect lat/lon fields dynamically
    lat_field, lon_field = _detect_geo_fields(rows, socrata_columns)

    features = []
    for row in rows:
        feature = _row_to_feature(row, lat_field, lon_field)
        if feature:
            features.append(feature)

    # Convert Socrata column metadata to OpenGrid column format
    og_columns = [
        {
            "id": col.get("field_name") or col.get("fieldName"),
            "displayName": col.get("display_name") or col.get("name"),
            "dataType": _socrata_type_to_og(col.get("data_type") or col.get("dataTypeName", "text")),
            "filter": True,
            "popup": True,
            "list": True,
        }
        for col in socrata_columns
        if not (col.get("field_name") or col.get("fieldName", "")).startswith(":")
    ]

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "view": {
                "id": dataset_id,
                "displayName": display_name,
                "options": {
                    "rendition": {
                        "icon": "default",
                        "color": "#0066CC",
                        "fillColor": "#66AAFF",
                        "opacity": 85,
                        "size": 6,
                    }
                },
                "columns": og_columns,
            }
        },
    }


def _detect_geo_fields(rows: list[dict], columns: list[dict]) -> tuple[str, str]:
    """Detect latitude and longitude field names from column metadata or row sampling."""
    lat_candidates = ["latitude", "lat", "y_coordinate", "y"]
    lon_candidates = ["longitude", "lon", "long", "x_coordinate", "x"]

    col_names = {
        (c.get("field_name") or c.get("fieldName", "")).lower()
        for c in columns
    }

    for lat in lat_candidates:
        for lon in lon_candidates:
            if lat in col_names and lon in col_names:
                return lat, lon

    # Fall back to sampling first row
    if rows:
        sample = rows[0]
        for lat in lat_candidates:
            for lon in lon_candidates:
                if lat in sample and lon in sample:
                    return lat, lon

    return "latitude", "longitude"


def _socrata_type_to_og(socrata_type: str) -> str:
    mapping = {
        "text": "string",
        "number": "number",
        "double": "float",
        "money": "float",
        "calendar_date": "date",
        "fixed_timestamp": "date",
        "floating_timestamp": "date",
        "checkbox": "string",
        "url": "string",
        "point": "string",
        "location": "string",
    }
    return mapping.get(socrata_type.lower(), "string")
