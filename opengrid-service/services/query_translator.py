"""
Translates MongoDB-style filter objects (sent by OpenGrid frontend) into SOQL WHERE clauses.
"""

from datetime import datetime, timezone
import re


def mongo_to_soql(mongo_filter: dict) -> str:
    """Convert a MongoDB query filter dict to a SOQL WHERE clause string."""
    if not mongo_filter:
        return ""
    return _translate(mongo_filter)


def _translate(node: dict | list) -> str:
    if not node:
        return ""

    if isinstance(node, list):
        return " AND ".join(_translate(n) for n in node if n)

    clauses = []
    for key, value in node.items():
        if key == "$and":
            parts = [_translate(v) for v in value if v]
            clauses.append("(" + " AND ".join(parts) + ")")
        elif key == "$or":
            parts = [_translate(v) for v in value if v]
            clauses.append("(" + " OR ".join(parts) + ")")
        else:
            clauses.append(_field_clause(key, value))

    return " AND ".join(c for c in clauses if c)


def _field_clause(field: str, value) -> str:
    if isinstance(value, dict):
        return _operator_clause(field, value)
    # Plain equality
    return f"{field} = {_quote(value)}"


def _operator_clause(field: str, ops: dict) -> str:
    parts = []

    if "$eq" in ops:
        parts.append(f"{field} = {_quote(ops['$eq'])}")

    if "$ne" in ops:
        parts.append(f"{field} != {_quote(ops['$ne'])}")

    if "$gt" in ops:
        parts.append(f"{field} > {_quote(ops['$gt'])}")

    if "$gte" in ops:
        parts.append(f"{field} >= {_quote(ops['$gte'])}")

    if "$lt" in ops:
        parts.append(f"{field} < {_quote(ops['$lt'])}")

    if "$lte" in ops:
        parts.append(f"{field} <= {_quote(ops['$lte'])}")

    if "$in" in ops:
        vals = ", ".join(_quote(v) for v in ops["$in"])
        parts.append(f"{field} IN ({vals})")

    if "$nin" in ops:
        vals = ", ".join(_quote(v) for v in ops["$nin"])
        parts.append(f"{field} NOT IN ({vals})")

    if "$regex" in ops:
        # MongoDB $regex ".*pattern.*" → SOQL LIKE '%pattern%'
        pattern = ops["$regex"]
        like_val = _regex_to_like(pattern)
        parts.append(f"{field} LIKE '{like_val}'")

    return " AND ".join(parts)


def _regex_to_like(pattern: str) -> str:
    """Convert a basic MongoDB regex pattern to a SOQL LIKE pattern."""
    # Strip leading/trailing .* anchors
    pattern = re.sub(r"^\.\*", "", pattern)
    pattern = re.sub(r"\.\*$", "", pattern)
    # Escape single quotes
    pattern = pattern.replace("'", "''")
    # Replace remaining .* with %
    pattern = pattern.replace(".*", "%")
    # Replace . (any char) with _
    pattern = re.sub(r"(?<!\\)\.", "_", pattern)
    return f"%{pattern}%"


def _quote(value) -> str:
    """Quote a value appropriately for SOQL."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        # Check if it looks like a millisecond timestamp (13 digits)
        if isinstance(value, (int, float)) and value > 1e11:
            dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            return f"'{dt.isoformat()}'"
        return str(value)
    if isinstance(value, str):
        # Escape single quotes
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return f"'{value}'"


def geo_filter_to_soql(geo_filter: dict, location_field: str = "location") -> str:
    """Convert a GeoJSON geometry geoFilter to a SOQL spatial function."""
    if not geo_filter:
        return ""

    geo_type = geo_filter.get("type", "")

    if geo_type == "Point":
        # Point with radius — not directly representable without radius, skip
        coords = geo_filter.get("coordinates", [])
        if len(coords) >= 2:
            lon, lat = coords[0], coords[1]
            radius = geo_filter.get("radius", 500)
            return f"within_circle({location_field}, {lat}, {lon}, {radius})"

    if geo_type in ("Polygon", "MultiPolygon"):
        # Convert GeoJSON polygon to WKT for within_polygon
        wkt = _geojson_to_wkt(geo_filter)
        if wkt:
            return f"within_polygon({location_field}, '{wkt}')"

    return ""


def _geojson_to_wkt(geometry: dict) -> str:
    geo_type = geometry.get("type")
    coords = geometry.get("coordinates", [])

    if geo_type == "Polygon":
        rings = []
        for ring in coords:
            pts = ", ".join(f"{c[0]} {c[1]}" for c in ring)
            rings.append(f"({pts})")
        return f"POLYGON({', '.join(rings)})"

    if geo_type == "MultiPolygon":
        polys = []
        for polygon in coords:
            rings = []
            for ring in polygon:
                pts = ", ".join(f"{c[0]} {c[1]}" for c in ring)
                rings.append(f"({pts})")
            polys.append(f"({', '.join(rings)})")
        return f"MULTIPOLYGON({', '.join(polys)})"

    return ""
