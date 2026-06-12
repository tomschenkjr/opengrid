"""
/stations/* — fixed geographic stations with real-time sensor data.
Each station has a known location and pulls from a public data feed.
"""
import asyncio
import csv
import io
import os
import re
import traceback
import zipfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException, Query

from services import library_events

_CHICAGO_TZ = ZoneInfo("America/Chicago")

router = APIRouter()

_GLERL_BASE = "https://www.glerl.noaa.gov/metdata/chi"
_BEACH_DNA_URL = "https://data.cityofchicago.org/resource/hmqm-anjq.json"
_BEACH_WEATHER_LOC_URL = "https://data.cityofchicago.org/resource/g3ip-u8rb.json"   # sensor locations
_BEACH_WEATHER_OBS_URL = "https://data.cityofchicago.org/resource/k7hf-8y75.json"   # measurements
_CTA_STOPS_URL       = "https://data.cityofchicago.org/resource/8pix-ypme.json"
_CPS_SCHOOLS_URL     = "https://data.cityofchicago.org/resource/twrw-chuq.json"
_LIBRARIES_URL       = "https://data.cityofchicago.org/resource/x8fc-8rcq.json"
_LIBRARY_VISITORS_URL = "https://data.cityofchicago.org/resource/dx99-mui6.json"
_LIBRARY_CIRCULATION_URL = "https://data.cityofchicago.org/resource/utjc-493b.json"
_POLICE_STATIONS_URL = "https://data.cityofchicago.org/resource/z8bn-74gv.json"
_FIRE_STATIONS_URL   = "https://data.cityofchicago.org/resource/28km-gtjn.json"
_SPEED_CAMERAS_URL   = "https://data.cityofchicago.org/resource/4i42-qv3h.json"
_BIKE_RACKS_URL      = "https://data.cityofchicago.org/resource/hgdw-64h3.json"
_PARKS_URL           = "https://data.cityofchicago.org/resource/ejsh-fztr.json"
_PARK_FACILITIES_URL = "https://data.cityofchicago.org/resource/eix4-gf83.json"
_PARK_BUILDINGS_URL  = "https://data.cityofchicago.org/resource/vcti-mbcd.json"
_PARK_ART_URL        = "https://data.cityofchicago.org/resource/pxyq-qhyd.json"
_DIVVY_GBFS_URL      = "https://gbfs.divvybikes.com/gbfs/2.3/gbfs.json"
_OPEN_AIR_URL        = "https://data.cityofchicago.org/resource/di9s-96ws.json"
_CTA_GTFS_URL        = "https://www.transitchicago.com/downloads/sch_data/google_transit.zip"
_CTA_ARRIVALS_URL    = "https://lapi.transitchicago.com/api/1.0/ttarrivals.aspx"
_CTA_BUS_TRACKER_URL = "https://ctabustracker.com/bustime/api/v2/getpredictions"
_CTA_RT_ORDER        = ["Red", "Blue", "Brn", "G", "Org", "P", "Pexp", "Pink", "Y"]
_METRA_GTFS_URL      = os.getenv("METRA_GTFS_URL", "https://schedules.metrarail.com/gtfs/schedule.zip")

_gtfs_zip_cache: dict     = {"data": None, "expires": None}  # CTA GTFS raw zip
_metra_zip_cache: dict    = {"data": None, "expires": None}  # Metra GTFS raw zip
_metra_parsed_cache: dict = {"data": None, "expires": None}  # all parsed Metra data
_cta_lines_cache: dict    = {"data": None, "expires": None}
_cta_stations_cache: dict = {"data": None, "expires": None}
_bus_stops_cache: dict    = {"data": None, "expires": None}
_schools_cache: dict      = {"data": None, "expires": None}
_facilities_cache: dict   = {}
_library_visitors_cache: dict = {"data": None, "expires": None}
_library_circulation_cache: dict = {"data": None, "expires": None}
_parks_cache: dict        = {"data": None, "expires": None}
_divvy_feeds_cache: dict  = {"data": None, "expires": None}
_divvy_station_info_cache: dict = {"data": None, "expires": None}
_divvy_station_status_cache: dict = {"data": None, "expires": None}
_divvy_vehicle_types_cache: dict = {"data": None, "expires": None}
_divvy_stations_cache: dict = {"data": None, "expires": None}
_open_air_sensors_cache: dict = {"data": None, "expires": None}
_open_air_sensor_detail_cache: dict = {}
_CACHE_TTL = timedelta(hours=24)

_SCHOOL_PRIMARY_CATEGORY_LABELS = {
    "ES": "Elementary School",
    "HS": "High School",
    "MS": "Middle School",
}

_SCHOOL_FIELDS = [
    "school_id", "short_name", "long_name", "school_type", "primary_category",
    "address", "zip", "phone", "progress_report_year",
    "student_growth_rating", "student_attainment_rating", "culture_climate_rating",
    "school_survey_safety", "student_attendance_year_2", "teacher_attendance_avg_pct",
    "chronic_truancy_pct", "freshmen_on_track_school_1", "graduation_4_year_school_1",
    "college_enrollment_school_1", "sat_grade_11_score_school",
    "school_latitude", "school_longitude", "location",
]

_PARK_FIELDS = [
    "objectid_1", "park_no", "park", "location", "zip", "acres", "ward",
    "park_class", "label", "the_geom",
]

_LIBRARY_MONTH_FIELDS = [
    ("january", "Jan"),
    ("february", "Feb"),
    ("march", "Mar"),
    ("april", "Apr"),
    ("may", "May"),
    ("june", "Jun"),
    ("july", "Jul"),
    ("august", "Aug"),
    ("september", "Sep"),
    ("october", "Oct"),
    ("november", "Nov"),
    ("december", "Dec"),
]

_FACILITY_CONFIGS = {
    "libraries": {
        "url": _LIBRARIES_URL,
        "label": "Library",
        "limit": 200,
        "fields": [
            "branch_", "service_hours", "address", "city", "state", "zip",
            "phone", "website", "branch_email", "location",
        ],
    },
    "police-stations": {
        "url": _POLICE_STATIONS_URL,
        "label": "Police Station",
        "limit": 100,
        "fields": [
            "district", "district_name", "address", "city", "state", "zip",
            "website", "phone", "fax", "tty", "latitude", "longitude", "location",
        ],
    },
    "fire-stations": {
        "url": _FIRE_STATIONS_URL,
        "label": "Fire Station",
        "limit": 300,
        "fields": ["name", "address", "city", "state", "zip", "engine", "location"],
    },
    "speed-cameras": {
        "url": _SPEED_CAMERAS_URL,
        "label": "Speed Camera",
        "limit": 500,
        "fields": [
            "id", "location_id", "address", "first_approach", "second_approach",
            "go_live_date", "latitude", "longitude", "location",
        ],
    },
    "bike-racks": {
        "url": _BIKE_RACKS_URL,
        "label": "Bike Rack",
        "limit": 10000,
        "fields": ["latitude", "longitude", "location", "name", "quantity", "type"],
    },
    "park-facilities": {
        "url": _PARK_FACILITIES_URL,
        "label": "Park Facility",
        "limit": 10000,
        "fields": [
            "objectid_1", "park", "park_no", "facility_n", "facility_t",
            "x_coord", "y_coord", "gisobjid", "the_geom",
        ],
    },
    "park-buildings": {
        "url": _PARK_BUILDINGS_URL,
        "label": "Park Building",
        "limit": 5000,
        "fields": [
            "objectid_1", "park", "park_no", "bldg_id", "bldg_type",
            "city_bldg_", "bldg_statu", "ward", "comm_area", "region",
            "address", "bldg_name", "bldg_owner", "lessor", "lessee",
            "stories", "x_coord", "y_coord", "year_built", "bldg_sq_fo",
            "gisobjid", "the_geom",
        ],
    },
    "park-art": {
        "url": _PARK_ART_URL,
        "label": "Park District Art",
        "limit": 5000,
        "fields": [
            "objectid", "park", "park_no", "name", "artist", "owner",
            "official_n", "x_coord", "y_coord", "gisobjid", "the_geom",
        ],
    },
}

_OPEN_AIR_GROUPS = [
    {
        "id": "pm25",
        "title": "PM2.5 Readings",
        "color": "#7b5fb2",
        "trend_field": "pm2_5concmassnowcast_value",
        "values": [
            ("pm2_5concmassnowcast_value", "NowCast Air Quality Indicator"),
            ("pm2_5concmass1hourmean_value", "PM2.5 1 Hour Average"),
            ("pm2_5concmass24hourrollingmean_1", "PM2.5 24 Hour Average"),
        ],
    },
    {
        "id": "no2",
        "title": "NO2 Readings",
        "color": "#b65b4b",
        "trend_field": "no2conc1hourmeanusepaaqi_1",
        "values": [
            ("no2conc1hourmeanusepaaqi_1", "NO2 1-hour Concentration Average, US EPA AQI"),
            ("no2conc1hourmean_value", "NO2 1-hour Concentration Average"),
        ],
    },
    {
        "id": "black_carbon",
        "title": "Black Carbon",
        "color": "#3f4850",
        "trend_field": "bcallsources1hourmean_value",
        "values": [
            ("bcallsources1hourmean_value", "Overall black carbon"),
            ("bcfossilfuel1hourmean_value", "Fossil-fuel combustion signal"),
            ("bcbiomass1hourmean_value", "Biomass / wood-smoke signal"),
        ],
    },
    {
        "id": "weather",
        "title": "Weather",
        "color": "#2d7f88",
        "trend_field": "temperatureambient1hourmean_1",
        "values": [
            ("temperatureambient1hourmean_1", "Temperature"),
            ("relhumidambient1hourmean_1", "Humidity"),
            ("windspeed1hourmean_value", "Wind Speed"),
            ("winddirection1hourmean_value", "Wind Direction"),
            ("atmpressure1hourmean_value", "Barometric Pressure"),
        ],
    },
]

_OPEN_AIR_FIELDS = [
    "datasourceid", "startofperiod", "sensor_name", "location", "latitude", "longitude",
]
for _group in _OPEN_AIR_GROUPS:
    for _field, _label in _group["values"]:
        if _field not in _OPEN_AIR_FIELDS:
            _OPEN_AIR_FIELDS.append(_field)


async def _fetch_gtfs_zip() -> bytes:
    """Download and cache the CTA GTFS zip (shared by rail lines and bus stops)."""
    now = datetime.now(timezone.utc)
    if _gtfs_zip_cache["data"] and _gtfs_zip_cache["expires"] and now < _gtfs_zip_cache["expires"]:
        return _gtfs_zip_cache["data"]
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
        r = await http.get(_CTA_GTFS_URL, headers={"User-Agent": "opengrid-service/1.0"})
        r.raise_for_status()
        _gtfs_zip_cache["data"] = r.content
        _gtfs_zip_cache["expires"] = now + _CACHE_TTL
    return _gtfs_zip_cache["data"]


def _socrata_headers() -> dict:
    headers = {"User-Agent": "opengrid-service/1.0"}
    token = os.getenv("SOCRATA_APP_TOKEN", "").strip() or None
    if token:
        headers["X-App-Token"] = token
    return headers
_CARDINAL = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _deg_to_cardinal(deg: float) -> str:
    return _CARDINAL[round(deg / 22.5) % 16]


def _doy_to_date(year: int, doy: int) -> str:
    dt = datetime(year, 1, 1) + timedelta(days=doy - 1)
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}"


def _c_to_f(c: float) -> float:
    return round(c * 9 / 5 + 32, 1)


def _parse_last_observation(text: str) -> dict:
    lines = [ln for ln in text.strip().splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    parts = lines[-1].split()
    year     = int(parts[1])
    doy      = int(parts[2])
    hhmm     = parts[3].zfill(4)
    air_c    = float(parts[4])
    wind_avg = float(parts[5])
    wind_max = float(parts[6])
    wind_dir = float(parts[7])
    humidity = float(parts[8])

    date_str  = _doy_to_date(year, doy)
    cardinal  = _deg_to_cardinal(wind_dir)
    air_f     = _c_to_f(air_c)
    time_str  = f"{hhmm[:2]}:{hhmm[2:]} UTC"

    return {
        "observed":          f"{date_str} {time_str}",
        "air_temp_c":        air_c,
        "air_temp_f":        air_f,
        "wind_avg_ms":       wind_avg,
        "wind_max_ms":       wind_max,
        "wind_dir_deg":      wind_dir,
        "wind_dir_cardinal": cardinal,
        "humidity_pct":      humidity,
    }


async def _fetch_glerl(date: datetime) -> str | None:
    url = f"{_GLERL_BASE}/{date.year}/{date.strftime('%Y%m%d')}.04t.txt"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers={"User-Agent": "opengrid-service/1.0"})
            if r.status_code == 200 and r.text.strip():
                return r.text
    except Exception:
        pass
    return None


@router.get("/stations/dever-crib")
async def dever_crib_conditions():
    """
    Real-time conditions from the William E. Dever Water Crib (GLERL station 4).
    Returns the most recent observation parsed from NOAA GLERL's daily data file.
    Falls back to yesterday's file if today's isn't published yet.
    """
    now = datetime.now(timezone.utc)
    text = await _fetch_glerl(now) or await _fetch_glerl(now - timedelta(days=1))
    if not text:
        raise HTTPException(status_code=503, detail="GLERL data unavailable")
    try:
        return _parse_last_observation(text)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Parse error: {e}")


@router.get("/stations/beach-dna")
async def beach_dna():
    """
    Most recent Beach Lab DNA test reading per Chicago beach.
    Source: data.cityofchicago.org dataset hmqm-anjq. Rows are returned newest
    first and de-duplicated by beach, so each beach keeps only its latest reading.
    """
    params = {
        "$select": "beach,dna_reading_mean,dna_sample_timestamp,latitude,longitude",
        "$order": "dna_sample_timestamp DESC",
        "$limit": 2000,
    }
    try:
        async with httpx.AsyncClient(headers=_socrata_headers(), timeout=15) as http:
            r = await http.get(_BEACH_DNA_URL, params=params)
            r.raise_for_status()
            rows = r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Beach data unavailable: {e}")

    latest: dict[str, dict] = {}
    for row in rows:
        beach = row.get("beach")
        lat, lon = row.get("latitude"), row.get("longitude")
        if not beach or beach in latest or lat is None or lon is None:
            continue
        try:
            latest[beach] = {
                "beach": beach,
                "dna_reading_mean": row.get("dna_reading_mean"),
                "timestamp": row.get("dna_sample_timestamp"),
                "latitude": float(lat),
                "longitude": float(lon),
            }
        except (TypeError, ValueError):
            continue
    return list(latest.values())


@router.get("/stations/beach-dna/history")
async def beach_dna_history(beach: str = Query(..., description="Beach name")):
    """
    DNA test readings for a single beach over the past 7 days, sorted oldest-first.
    Source: data.cityofchicago.org dataset hmqm-anjq.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    escaped = beach.replace("'", "''")
    params = {
        "$select": "dna_reading_mean,dna_sample_timestamp",
        "$where": f"beach='{escaped}' AND dna_sample_timestamp >= '{since}'",
        "$order": "dna_sample_timestamp ASC",
        "$limit": 200,
    }
    try:
        async with httpx.AsyncClient(headers=_socrata_headers(), timeout=15) as http:
            r = await http.get(_BEACH_DNA_URL, params=params)
            r.raise_for_status()
            rows = r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Beach DNA history unavailable: {e}")

    results = []
    for row in rows:
        ts = row.get("dna_sample_timestamp")
        val = row.get("dna_reading_mean")
        if ts is None or val is None:
            continue
        try:
            results.append({"timestamp": ts, "dna_reading_mean": float(val)})
        except (TypeError, ValueError):
            continue
    return results


@router.get("/stations/beach-weather")
async def beach_weather():
    """
    Beach weather stations: sensor LOCATIONS (g3ip-u8rb, sensor_type='Weather')
    merged with the most recent MEASUREMENT per station (k7hf-8y75), joined on
    station name (locations.sensor_name == measurements.station_name).
    """
    loc_params = {
        "$select": "sensor_name,latitude,longitude",
        "$where": "sensor_type='Weather'",
        "$limit": 200,
    }
    try:
        async with httpx.AsyncClient(headers=_socrata_headers(), timeout=20) as http:
            loc_r = await http.get(_BEACH_WEATHER_LOC_URL, params=loc_params)
            loc_r.raise_for_status()
            locations = loc_r.json()

            # Fetch recent readings per station (newest first). Index 0 is the
            # most recent; the rest are shown as history. Per-station queries
            # handle stations whose latest reading is old.
            async def _readings(name: str):
                try:
                    safe = name.replace("'", "''")
                    r = await http.get(_BEACH_WEATHER_OBS_URL, params={
                        "$where": f"station_name='{safe}'",
                        "$order": "measurement_timestamp DESC",
                        "$limit": 25,
                    })
                    r.raise_for_status()
                    return r.json()
                except Exception:
                    return []

            names = [l.get("sensor_name") for l in locations if l.get("sensor_name")]
            obs = await asyncio.gather(*[_readings(n) for n in names])
            obs_map = dict(zip(names, obs))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Beach weather data unavailable: {e}")

    stations = []
    for loc in locations:
        name = loc.get("sensor_name")
        lat, lon = loc.get("latitude"), loc.get("longitude")
        if not name or lat is None or lon is None:
            continue
        rows = obs_map.get(name) or []
        try:
            stations.append({
                "station_name": name,
                "latitude": float(lat),
                "longitude": float(lon),
                "measurement": rows[0] if rows else None,
                "history": rows[1:] if len(rows) > 1 else [],
            })
        except (TypeError, ValueError):
            continue
    return stations


# ---------------------------------------------------------------------------
# CTA El train stations and rail lines
# ---------------------------------------------------------------------------

_CTA_LINE_KEYS = ["red", "blue", "g", "brn", "p", "pexp", "y", "pnk", "o"]


async def _fetch_cta_lines_geojson() -> dict:
    """Extract rail route shapes from CTA GTFS. Cached 24h."""
    now = datetime.now(timezone.utc)
    if _cta_lines_cache["data"] and _cta_lines_cache["expires"] and now < _cta_lines_cache["expires"]:
        return _cta_lines_cache["data"]

    content = await _fetch_gtfs_zip()

    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        # 1. Rail routes (route_type=1)
        routes: dict[str, dict] = {}
        with zf.open("routes.txt") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
                if row.get("route_type", "").strip() == "1":
                    color = row.get("route_color", "").strip()
                    rid = row["route_id"].strip()
                    routes[rid] = {
                        "short_name": row.get("route_short_name", "").strip(),
                        "long_name": row.get("route_long_name", "").strip(),
                        "color": "#" + color if color else "#555555",
                    }

        # 2. Collect all distinct shape_ids per rail route
        route_shapes: dict[str, set] = {r: set() for r in routes}
        with zf.open("trips.txt") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
                rid = row.get("route_id", "").strip()
                sid = row.get("shape_id", "").strip()
                if rid in route_shapes and sid:
                    route_shapes[rid].add(sid)

        # 3. Parse only the needed shape points
        needed: set[str] = set().union(*route_shapes.values())
        shape_pts: dict[str, list] = {sid: [] for sid in needed}
        with zf.open("shapes.txt") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
                sid = row.get("shape_id", "").strip()
                if sid in shape_pts:
                    shape_pts[sid].append((
                        int(row["shape_pt_sequence"]),
                        float(row["shape_pt_lon"]),
                        float(row["shape_pt_lat"]),
                    ))

    features = []
    for rid, route in routes.items():
        lines = []
        for sid in route_shapes[rid]:
            pts = sorted(shape_pts.get(sid, []), key=lambda x: x[0])
            if pts:
                lines.append([[p[1], p[2]] for p in pts])
        if not lines:
            continue
        geom = ({"type": "MultiLineString", "coordinates": lines}
                if len(lines) > 1
                else {"type": "LineString", "coordinates": lines[0]})
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "route_id": rid,
                "short_name": route["short_name"],
                "long_name": route["long_name"],
                "color": route["color"],
            },
        })

    result = {"type": "FeatureCollection", "features": features}
    _cta_lines_cache["data"] = result
    _cta_lines_cache["expires"] = now + _CACHE_TTL
    return result


@router.get("/stations/cta-lines")
async def cta_lines():
    """CTA El rail line shapes from GTFS (cached 24h)."""
    try:
        return await _fetch_cta_lines_geojson()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"CTA GTFS unavailable: {e}")


@router.get("/stations/cta-trains")
async def cta_trains():
    """CTA El stations deduplicated by parent station (map_id), from Socrata 8pix-ypme."""
    now = datetime.now(timezone.utc)
    if _cta_stations_cache["data"] and _cta_stations_cache["expires"] and now < _cta_stations_cache["expires"]:
        return _cta_stations_cache["data"]

    try:
        async with httpx.AsyncClient(headers=_socrata_headers(), timeout=20) as http:
            r = await http.get(_CTA_STOPS_URL, params={"$limit": 2000})
            r.raise_for_status()
            rows = r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"CTA station data unavailable: {e}")

    def _cta_bool(val) -> bool:
        return val is True or val == "true" or val == "True"

    print(f"[cta_trains] raw rows from Socrata: {len(rows)}")
    if rows:
        print(f"[cta_trains] sample row keys: {list(rows[0].keys())}")
        print(f"[cta_trains] sample row: {rows[0]}")

    seen: dict[str, dict] = {}
    for row in rows:
        map_id = row.get("map_id")
        if not map_id:
            continue

        # Coordinates: try stop_lat/stop_lon first, then GeoJSON location, then old Socrata point
        lat = lon = None
        try:
            lat = float(row["stop_lat"])
            lon = float(row["stop_lon"])
        except (KeyError, TypeError, ValueError):
            pass
        if not lat:
            loc = row.get("location") or {}
            if isinstance(loc, dict):
                if loc.get("type") == "Point":
                    try:
                        coords = loc["coordinates"]
                        lon, lat = float(coords[0]), float(coords[1])
                    except (KeyError, IndexError, TypeError, ValueError):
                        pass
                elif "latitude" in loc:
                    try:
                        lat = float(loc["latitude"])
                        lon = float(loc["longitude"])
                    except (KeyError, TypeError, ValueError):
                        pass
        if not lat or not lon:
            continue

        lines = [k for k in _CTA_LINE_KEYS if _cta_bool(row.get(k))]

        if map_id not in seen:
            seen[map_id] = {
                "map_id": map_id,
                "station_name": row.get("station_name") or row.get("stop_name", ""),
                "lat": lat,
                "lon": lon,
                "lines": set(lines),
                "ada": _cta_bool(row.get("ada")),
            }
        else:
            seen[map_id]["lines"].update(lines)
            if _cta_bool(row.get("ada")):
                seen[map_id]["ada"] = True

    result = []
    for s in seen.values():
        s["lines"] = sorted(s["lines"], key=lambda k: _CTA_LINE_KEYS.index(k) if k in _CTA_LINE_KEYS else 99)
        result.append(s)

    _cta_stations_cache["data"] = result
    _cta_stations_cache["expires"] = now + _CACHE_TTL
    return result


@router.get("/stations/cta-arrivals")
async def cta_arrivals(mapid: str = Query(..., description="CTA parent station map_id")):
    """
    Real-time CTA El arrival predictions for a parent station.
    Groups by route + destination, sorted by line then arrival time.
    Times are expressed as minutes from now (Chicago local time).
    """
    api_key = os.getenv("CTA_TRAIN_TRACKER_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="CTA Train Tracker key not configured")

    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(_CTA_ARRIVALS_URL, params={
                "key":        api_key,
                "mapid":      mapid,
                "outputType": "JSON",
                "max":        6,       # per stop; groups are capped to 3 below
            })
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"CTA Train Tracker unavailable: {e}")

    ctatt = data.get("ctatt") or {}
    err_cd = ctatt.get("errCd")
    if err_cd is not None and str(err_cd) != "0":
        raise HTTPException(status_code=400, detail=ctatt.get("errNm") or "CTA API error")

    etas = ctatt.get("eta") or []
    if isinstance(etas, dict):
        etas = [etas]

    now = datetime.now(_CHICAGO_TZ)
    groups: dict[tuple, dict] = {}

    for eta in etas:
        rt      = eta.get("rt", "")
        dest_nm = eta.get("destNm", "")
        key     = (rt, dest_nm)

        arr_t_str = (eta.get("arrT") or "").strip()
        arr_dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y%m%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                arr_dt = datetime.strptime(arr_t_str, fmt).replace(tzinfo=_CHICAGO_TZ)
                break
            except ValueError:
                continue
        if arr_dt is None:
            continue
        minutes = max(0, round((arr_dt - now).total_seconds() / 60))

        if key not in groups:
            groups[key] = {"rt": rt, "dest_nm": dest_nm, "arrivals": []}

        groups[key]["arrivals"].append({
            "minutes": minutes,
            "is_app":  eta.get("isApp") == "1",
            "is_sch":  eta.get("isSch") == "1",
            "is_dly":  eta.get("isDly") == "1",
        })

    result = sorted(groups.values(), key=lambda g: (
        _CTA_RT_ORDER.index(g["rt"]) if g["rt"] in _CTA_RT_ORDER else 99,
        g["dest_nm"],
    ))
    for g in result:
        g["arrivals"].sort(key=lambda a: a["minutes"])
        g["arrivals"] = g["arrivals"][:3]   # next 3 per line+direction

    return result


# ---------------------------------------------------------------------------
# CTA Bus stops and arrivals
# ---------------------------------------------------------------------------

def _school_category_label(value: str | None) -> str:
    key = (value or "").strip().upper()
    return _SCHOOL_PRIMARY_CATEGORY_LABELS.get(key, value or "")


def _school_metric(row: dict, key: str) -> str | None:
    value = row.get(key)
    return None if value in (None, "") else value


def _school_from_row(row: dict) -> dict | None:
    try:
        lat = float(row.get("school_latitude") or 0)
        lon = float(row.get("school_longitude") or 0)
    except (TypeError, ValueError):
        return None
    if not lat or not lon:
        return None
    return {
        "school_id": row.get("school_id"),
        "short_name": row.get("short_name"),
        "long_name": row.get("long_name") or row.get("short_name") or "CPS School",
        "school_type": row.get("school_type"),
        "primary_category": _school_category_label(row.get("primary_category")),
        "address": row.get("address"),
        "zip": row.get("zip"),
        "phone": row.get("phone"),
        "progress_report_year": row.get("progress_report_year"),
        "student_growth_rating": row.get("student_growth_rating"),
        "student_attainment_rating": row.get("student_attainment_rating"),
        "culture_climate_rating": row.get("culture_climate_rating"),
        "school_survey_safety": row.get("school_survey_safety"),
        "student_attendance_year_2": _school_metric(row, "student_attendance_year_2"),
        "teacher_attendance_avg_pct": _school_metric(row, "teacher_attendance_avg_pct"),
        "chronic_truancy_pct": _school_metric(row, "chronic_truancy_pct"),
        "freshmen_on_track_school_1": _school_metric(row, "freshmen_on_track_school_1"),
        "graduation_4_year_school_1": _school_metric(row, "graduation_4_year_school_1"),
        "college_enrollment_school_1": _school_metric(row, "college_enrollment_school_1"),
        "sat_grade_11_score_school": _school_metric(row, "sat_grade_11_score_school"),
        "lat": lat,
        "lon": lon,
    }


async def _fetch_schools() -> list[dict]:
    """CPS school progress report locations and key metrics. Cached 24h."""
    now = datetime.now(timezone.utc)
    if _schools_cache["data"] and _schools_cache["expires"] and now < _schools_cache["expires"]:
        return _schools_cache["data"]

    try:
        async with httpx.AsyncClient(headers=_socrata_headers(), timeout=30) as http:
            r = await http.get(_CPS_SCHOOLS_URL, params={
                "$select": ",".join(_SCHOOL_FIELDS),
                "$limit": 2000,
            })
            r.raise_for_status()
            rows = r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"School data unavailable: {e}")

    schools = []
    for row in rows:
        school = _school_from_row(row)
        if school:
            schools.append(school)

    print(f"[schools] cached {len(schools)} CPS schools")
    _schools_cache["data"] = schools
    _schools_cache["expires"] = now + _CACHE_TTL
    return schools


@router.get("/stations/schools")
async def schools(
    minLat: float = Query(...), minLon: float = Query(...),
    maxLat: float = Query(...), maxLon: float = Query(...),
):
    """CPS schools within a bounding box from School Progress Reports."""
    all_schools = await _fetch_schools()
    return [
        s for s in all_schools
        if minLat <= s["lat"] <= maxLat and minLon <= s["lon"] <= maxLon
    ]


def _row_lat_lon(row: dict) -> tuple[float | None, float | None]:
    lat = row.get("latitude")
    lon = row.get("longitude")
    loc = row.get("location")
    geom = row.get("the_geom")
    if (lat is None or lon is None) and isinstance(loc, dict):
        lat = loc.get("latitude") or loc.get("lat")
        lon = loc.get("longitude") or loc.get("lon")
        coords = loc.get("coordinates")
        if (lat is None or lon is None) and isinstance(coords, list) and len(coords) >= 2:
            lon = coords[0]
            lat = coords[1]
    if (lat is None or lon is None) and isinstance(geom, dict):
        coords = geom.get("coordinates")
        if geom.get("type") == "Point" and isinstance(coords, list) and len(coords) >= 2:
            lon = coords[0]
            lat = coords[1]
    if lat is None or lon is None:
        lat = row.get("y_coord")
        lon = row.get("x_coord")
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None, None


def _facility_value(row: dict, field: str) -> str | None:
    value = row.get(field)
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        return value.get("url") or value.get("description")
    return str(value)


def _facility_details(row: dict, pairs: list[tuple[str, str]]) -> list[dict]:
    details = []
    for field, label in pairs:
        value = _facility_value(row, field)
        if value:
            details.append({"label": label, "value": value})
    return details


def _library_key(value: str | None) -> str:
    if not value:
        return ""
    key = value.upper().replace("WASHTINGTON", "WASHINGTON")
    key = re.sub(r"\b(CHICAGO PUBLIC|REGIONAL|BRANCH|LIBRARY|CENTER)\b", " ", key)
    key = re.sub(r"[^A-Z0-9]+", " ", key)
    key = re.sub(r"\bDALEY RICHARD J BRIDGEPORT\b", "DALEY RICHARD J", key)
    key = re.sub(r"\bDALEY RICHARD M W HUMBOLDT\b", "DALEY RICHARD M", key)
    return re.sub(r"\s+", " ", key).strip()


def _number_value(value) -> int | float | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return int(number)
    return number


def _library_month_points(row: dict) -> list[dict]:
    return [
        {"label": label, "value": _number_value(row.get(field))}
        for field, label in _LIBRARY_MONTH_FIELDS
    ]


async def _fetch_library_metric(url: str, cache: dict, metric_id: str, label: str) -> dict:
    now = datetime.now(timezone.utc)
    if cache["data"] and cache["expires"] and now < cache["expires"]:
        return cache["data"]

    fields = ["branch", *[field for field, _label in _LIBRARY_MONTH_FIELDS], "ytd"]
    try:
        async with httpx.AsyncClient(headers=_socrata_headers(), timeout=30) as http:
            r = await http.get(url, params={
                "$select": ",".join(fields),
                "$limit": 200,
            })
            r.raise_for_status()
            rows = r.json()
    except Exception as e:
        print(f"[libraries:{metric_id}] unavailable: {e}")
        return cache.get("data") or {}

    by_branch = {}
    for row in rows:
        key = _library_key(_facility_value(row, "branch"))
        if not key:
            continue
        by_branch[key] = {
            "id": metric_id,
            "label": label,
            "year": 2024,
            "total": _number_value(row.get("ytd")),
            "points": _library_month_points(row),
        }

    print(f"[libraries:{metric_id}] cached {len(by_branch)} branch metrics")
    cache["data"] = by_branch
    cache["expires"] = now + _CACHE_TTL
    return by_branch


async def _fetch_library_metrics() -> tuple[dict, dict]:
    visitors, circulation = await asyncio.gather(
        _fetch_library_metric(_LIBRARY_VISITORS_URL, _library_visitors_cache, "visitors", "Visitors"),
        _fetch_library_metric(_LIBRARY_CIRCULATION_URL, _library_circulation_cache, "circulation", "Circulation"),
    )
    return visitors, circulation


def _facility_from_row(kind: str, row: dict) -> dict | None:
    lat, lon = _row_lat_lon(row)
    if lat is None or lon is None or not lat or not lon:
        return None

    if kind == "libraries":
        branch = _facility_value(row, "branch_") or "Chicago Public Library"
        title = f"{branch} Library" if "library" not in branch.lower() else branch
        subtitle = " · ".join(v for v in [
            _facility_value(row, "address"),
            _facility_value(row, "zip"),
        ] if v)
        return {
            "id": f"library-{branch}",
            "kind": kind,
            "kind_label": "Library",
            "title": title,
            "subtitle": subtitle,
            "pill": "Library",
            "lat": lat,
            "lon": lon,
            "details": _facility_details(row, [
                ("service_hours", "Service Hours"),
                ("phone", "Phone"),
                ("branch_email", "Email"),
                ("website", "Website"),
            ]),
        }

    if kind == "police-stations":
        district = _facility_value(row, "district")
        district_name = _facility_value(row, "district_name") or "Police"
        title = f"{district_name} Police Station"
        subtitle = " · ".join(v for v in [
            _facility_value(row, "address"),
            _facility_value(row, "zip"),
        ] if v)
        pill = f"District {district}" if district and district.lower() != "headquarters" else "Police"
        return {
            "id": f"police-{district or district_name}",
            "kind": kind,
            "kind_label": "Police Station",
            "title": title,
            "subtitle": subtitle,
            "pill": pill,
            "lat": lat,
            "lon": lon,
            "details": _facility_details(row, [
                ("phone", "Phone"),
                ("fax", "Fax"),
                ("tty", "TTY"),
                ("website", "Website"),
            ]),
        }

    if kind == "fire-stations":
        name = _facility_value(row, "name") or _facility_value(row, "engine") or "Fire Station"
        title = f"{name} Fire Station" if "fire station" not in name.lower() else name
        subtitle = " · ".join(v for v in [
            _facility_value(row, "address"),
            _facility_value(row, "zip"),
        ] if v)
        return {
            "id": f"fire-{name}",
            "kind": kind,
            "kind_label": "Fire Station",
            "title": title,
            "subtitle": subtitle,
            "pill": _facility_value(row, "engine") or "Fire",
            "lat": lat,
            "lon": lon,
            "details": _facility_details(row, [
                ("engine", "Engine"),
                ("address", "Address"),
            ]),
        }

    if kind == "speed-cameras":
        address = _facility_value(row, "address") or "Speed Camera"
        first = _facility_value(row, "first_approach")
        second = _facility_value(row, "second_approach")
        approaches = " / ".join(v for v in [first, second] if v)
        details = _facility_details(row, [
            ("location_id", "Location ID"),
            ("go_live_date", "Go-Live Date"),
        ])
        if approaches:
            details.insert(0, {"label": "Approaches", "value": approaches})
        return {
            "id": f"speed-camera-{_facility_value(row, 'id') or address}",
            "kind": kind,
            "kind_label": "Speed Camera",
            "title": f"{address} Speed Camera",
            "subtitle": approaches,
            "pill": _facility_value(row, "location_id") or "Camera",
            "lat": lat,
            "lon": lon,
            "details": details,
        }

    if kind == "bike-racks":
        name = _facility_value(row, "name") or _facility_value(row, "location") or "Bike Rack"
        qty = _facility_value(row, "quantity")
        return {
            "id": f"bike-rack-{name}-{lat}-{lon}",
            "kind": kind,
            "kind_label": "Bike Rack",
            "title": name,
            "subtitle": _facility_value(row, "location") or "",
            "pill": f"{qty} racks" if qty else "Bike Rack",
            "lat": lat,
            "lon": lon,
            "details": _facility_details(row, [
                ("quantity", "Quantity"),
                ("type", "Type"),
                ("location", "Location"),
            ]),
        }

    if kind == "park-facilities":
        facility_name = _facility_value(row, "facility_n") or "Park Facility"
        facility_type = _facility_value(row, "facility_t")
        park = _facility_value(row, "park")
        subtitle = " · ".join(v for v in [park, facility_type] if v)
        return {
            "id": f"park-facility-{_facility_value(row, 'objectid_1') or _facility_value(row, 'gisobjid') or facility_name}",
            "kind": kind,
            "kind_label": "Park Facility",
            "title": facility_name,
            "subtitle": subtitle,
            "pill": facility_type or "Facility",
            "lat": lat,
            "lon": lon,
            "details": _facility_details(row, [
                ("park", "Park"),
                ("park_no", "Park No."),
                ("facility_t", "Type"),
                ("gisobjid", "GIS Object ID"),
            ]),
        }

    if kind == "park-buildings":
        bldg_name = _facility_value(row, "bldg_name")
        bldg_type = _facility_value(row, "bldg_type")
        title = bldg_name or bldg_type or "Park Building"
        subtitle = " · ".join(v for v in [
            _facility_value(row, "park"),
            _facility_value(row, "address"),
        ] if v)
        return {
            "id": f"park-building-{_facility_value(row, 'objectid_1') or _facility_value(row, 'bldg_id') or title}",
            "kind": kind,
            "kind_label": "Park Building",
            "title": title,
            "subtitle": subtitle,
            "pill": bldg_type or "Building",
            "lat": lat,
            "lon": lon,
            "details": _facility_details(row, [
                ("park", "Park"),
                ("park_no", "Park No."),
                ("bldg_id", "Building ID"),
                ("bldg_type", "Type"),
                ("bldg_statu", "Status"),
                ("address", "Address"),
                ("ward", "Ward"),
                ("comm_area", "Community Area"),
                ("year_built", "Year Built"),
                ("bldg_sq_fo", "Sq. Ft."),
                ("bldg_owner", "Owner"),
            ]),
        }

    if kind == "park-art":
        name = _facility_value(row, "name") or _facility_value(row, "official_n") or "Park District Artwork"
        park = _facility_value(row, "park")
        artist = _facility_value(row, "artist")
        return {
            "id": f"park-art-{_facility_value(row, 'objectid') or _facility_value(row, 'gisobjid') or name}",
            "kind": kind,
            "kind_label": "Park District Art",
            "title": name,
            "subtitle": park or "",
            "pill": "Artwork",
            "lat": lat,
            "lon": lon,
            "details": _facility_details(row, [
                ("park", "Park"),
                ("park_no", "Park No."),
                ("artist", "Artist"),
                ("owner", "Owner"),
                ("official_n", "Official Name"),
                ("gisobjid", "GIS Object ID"),
            ]),
        }

    return None


async def _fetch_facilities(kind: str) -> list[dict]:
    config = _FACILITY_CONFIGS.get(kind)
    if not config:
        raise KeyError(kind)

    now = datetime.now(timezone.utc)
    cached = _facilities_cache.get(kind)
    if cached and cached["data"] and cached["expires"] and now < cached["expires"]:
        return cached["data"]

    params = {
        "$select": ",".join(config["fields"]),
        "$limit": config.get("limit", 1000),
    }
    try:
        async with httpx.AsyncClient(headers=_socrata_headers(), timeout=30) as http:
            r = await http.get(config["url"], params=params)
            r.raise_for_status()
            rows = r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"{config['label']} data unavailable: {e}")

    library_visitors = {}
    library_circulation = {}
    library_upcoming_events = {}
    if kind == "libraries":
        library_visitors, library_circulation = await _fetch_library_metrics()
        try:
            library_upcoming_events = await library_events.events_by_library(limit_per_library=8)
        except Exception as e:
            print(f"[libraries:events] unavailable: {e}")

    facilities = []
    for row in rows:
        item = _facility_from_row(kind, row)
        if item:
            if kind == "libraries":
                key = _library_key(_facility_value(row, "branch_"))
                visitor_series = library_visitors.get(key)
                circulation_series = library_circulation.get(key)
                upcoming = library_upcoming_events.get(key)
                if visitor_series:
                    item["library_visitors_2024"] = visitor_series
                if circulation_series:
                    item["library_circulation_2024"] = circulation_series
                if upcoming:
                    item["library_events"] = upcoming
            facilities.append(item)

    print(f"[facilities:{kind}] cached {len(facilities)} records")
    _facilities_cache[kind] = {
        "data": facilities,
        "expires": now + _CACHE_TTL,
    }
    return facilities


@router.get("/stations/facilities/{facility_type}")
async def facilities(
    facility_type: str,
    minLat: float = Query(...), minLon: float = Query(...),
    maxLat: float = Query(...), maxLon: float = Query(...),
):
    """Persistent civic facilities within a bounding box."""
    if facility_type not in _FACILITY_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Unknown facility type: {facility_type}")
    all_facilities = await _fetch_facilities(facility_type)
    return [
        f for f in all_facilities
        if minLat <= f["lat"] <= maxLat and minLon <= f["lon"] <= maxLon
    ]


def _geom_points(value):
    if isinstance(value, (int, float)):
        return []
    if (isinstance(value, list) and len(value) >= 2
            and all(isinstance(v, (int, float)) for v in value[:2])):
        return [(float(value[1]), float(value[0]))]
    if isinstance(value, list):
        points = []
        for child in value:
            points.extend(_geom_points(child))
        return points
    return []


def _geom_bbox(geometry: dict | None) -> dict | None:
    if not isinstance(geometry, dict):
        return None
    points = _geom_points(geometry.get("coordinates"))
    if not points:
        return None
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return {
        "minLat": min(lats), "maxLat": max(lats),
        "minLon": min(lons), "maxLon": max(lons),
    }


def _bbox_intersects(a: dict | None, b: dict) -> bool:
    if not a:
        return False
    return not (
        a["maxLat"] < b["minLat"] or a["minLat"] > b["maxLat"] or
        a["maxLon"] < b["minLon"] or a["minLon"] > b["maxLon"]
    )


def _bbox_center(bbox: dict) -> tuple[float, float]:
    return (
        (bbox["minLat"] + bbox["maxLat"]) / 2,
        (bbox["minLon"] + bbox["maxLon"]) / 2,
    )


def _park_from_row(row: dict) -> dict | None:
    geometry = row.get("the_geom")
    bbox = _geom_bbox(geometry)
    if not bbox:
        return None
    lat, lon = _bbox_center(bbox)
    details = []
    for field, label in [
        ("location", "Location"),
        ("park_no", "Park No."),
        ("park_class", "Class"),
        ("acres", "Acres"),
        ("ward", "Ward"),
        ("zip", "ZIP"),
    ]:
        value = row.get(field)
        if value not in (None, ""):
            details.append({"label": label, "value": value})
    park_name = row.get("park") or row.get("label") or "Chicago Park"
    return {
        "id": f"park-{row.get('objectid_1') or row.get('park_no') or park_name}",
        "kind": "parks",
        "kind_label": "Park",
        "title": park_name,
        "subtitle": row.get("location") or "",
        "pill": row.get("park_class") or "Park",
        "park_no": row.get("park_no"),
        "park": park_name,
        "location": row.get("location"),
        "zip": row.get("zip"),
        "acres": row.get("acres"),
        "ward": row.get("ward"),
        "park_class": row.get("park_class"),
        "lat": lat,
        "lon": lon,
        "bbox": bbox,
        "geometry": geometry,
        "details": details,
    }


async def _fetch_parks() -> list[dict]:
    """Chicago Park District park boundary polygons. Cached 24h."""
    now = datetime.now(timezone.utc)
    if _parks_cache["data"] and _parks_cache["expires"] and now < _parks_cache["expires"]:
        return _parks_cache["data"]

    params = {
        "$select": ",".join(_PARK_FIELDS),
        "$limit": 2000,
    }
    try:
        async with httpx.AsyncClient(headers=_socrata_headers(), timeout=45) as http:
            r = await http.get(_PARKS_URL, params=params)
            r.raise_for_status()
            rows = r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Park boundary data unavailable: {e}")

    parks = []
    for row in rows:
        park = _park_from_row(row)
        if park:
            parks.append(park)

    print(f"[parks] cached {len(parks)} park boundaries")
    _parks_cache["data"] = parks
    _parks_cache["expires"] = now + _CACHE_TTL
    return parks


@router.get("/stations/parks")
async def parks(
    minLat: float = Query(...), minLon: float = Query(...),
    maxLat: float = Query(...), maxLon: float = Query(...),
):
    """Chicago Park District park boundary polygons intersecting a bounding box."""
    bounds = {"minLat": minLat, "minLon": minLon, "maxLat": maxLat, "maxLon": maxLon}
    all_parks = await _fetch_parks()
    return [p for p in all_parks if _bbox_intersects(p.get("bbox"), bounds)]


async def _fetch_bus_stops() -> list[dict]:
    """Parse bus stops from CTA GTFS stops.txt. Cached 24h."""
    now = datetime.now(timezone.utc)
    if _bus_stops_cache["data"] and _bus_stops_cache["expires"] and now < _bus_stops_cache["expires"]:
        return _bus_stops_cache["data"]

    content = await _fetch_gtfs_zip()
    stops = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        with zf.open("stops.txt") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
                # Bus stops: not a parent station and no parent_station reference
                if row.get("location_type", "").strip() == "1":
                    continue
                if row.get("parent_station", "").strip():
                    continue
                try:
                    lat = float(row.get("stop_lat") or 0)
                    lon = float(row.get("stop_lon") or 0)
                except (ValueError, TypeError):
                    continue
                if not lat or not lon:
                    continue
                stops.append({
                    "stop_id":   row.get("stop_id", "").strip(),
                    "stop_name": row.get("stop_name", "").strip(),
                    "lat":       lat,
                    "lon":       lon,
                })

    print(f"[bus_stops] cached {len(stops)} stops")
    _bus_stops_cache["data"] = stops
    _bus_stops_cache["expires"] = now + _CACHE_TTL
    return stops


@router.get("/stations/bus-stops")
async def bus_stops(
    minLat: float = Query(...), minLon: float = Query(...),
    maxLat: float = Query(...), maxLon: float = Query(...),
):
    """Bus stops within a bounding box, parsed from CTA GTFS."""
    try:
        all_stops = await _fetch_bus_stops()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"Bus stop data unavailable: {e}")
    return [
        s for s in all_stops
        if minLat <= s["lat"] <= maxLat and minLon <= s["lon"] <= maxLon
    ]


@router.get("/stations/bus-arrivals")
async def bus_arrivals(stpid: str = Query(..., description="CTA bus stop ID")):
    """Real-time CTA bus predictions for a stop, sorted by arrival time."""
    api_key = os.getenv("CTA_BUS_TRACKER_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="CTA Bus Tracker key not configured")

    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(_CTA_BUS_TRACKER_URL, params={
                "key":    api_key,
                "stpid":  stpid,
                "format": "json",
                "top":    10,
            })
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"CTA Bus Tracker unavailable: {e}")

    resp = data.get("bustime-response") or {}
    if resp.get("error"):
        return []   # "No service scheduled" etc.

    preds = resp.get("prd") or []
    if isinstance(preds, dict):
        preds = [preds]

    arrivals = []
    for pred in preds:
        prdctdn = str(pred.get("prdctdn") or "").strip()
        if prdctdn.upper() == "DUE":
            minutes, is_due = 0, True
        else:
            try:
                minutes = int(prdctdn)
                is_due  = minutes <= 1
            except ValueError:
                continue
        dly = pred.get("dly")
        arrivals.append({
            "rt":      pred.get("rt", ""),
            "rtdir":   pred.get("rtdir", ""),
            "des":     pred.get("des", ""),
            "minutes": minutes,
            "is_due":  is_due,
            "is_dly":  dly is True or dly == "true",
        })

    arrivals.sort(key=lambda a: a["minutes"])
    return arrivals


# ---------------------------------------------------------------------------
# Divvy bike stations
# ---------------------------------------------------------------------------

async def _fetch_divvy_stations() -> list[dict]:
    """Fetch Divvy station info and live status from GBFS. Cached briefly."""
    now = datetime.now(timezone.utc)
    if (_divvy_stations_cache["data"] and _divvy_stations_cache["expires"] and
            now < _divvy_stations_cache["expires"]):
        return _divvy_stations_cache["data"]

    feeds = await _fetch_divvy_feed_urls()
    info_rows, status_by_id, vehicle_type_labels = await asyncio.gather(
        _fetch_divvy_station_information(feeds),
        _fetch_divvy_station_status(feeds),
        _fetch_divvy_vehicle_type_labels(feeds),
    )

    def _as_int(value, default=0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _vehicle_types_available(status: dict) -> list[dict]:
        result = []
        for item in status.get("vehicle_types_available") or []:
            vehicle_type_id = str(item.get("vehicle_type_id", "")).strip()
            count = _as_int(item.get("count"))
            result.append({
                "vehicle_type_id": vehicle_type_id,
                "count": count,
                "label": vehicle_type_labels.get(vehicle_type_id, f"vehicle type {vehicle_type_id}"),
            })
        return result

    def _available_label(types: list[dict]) -> str:
        available = [t for t in types if t["count"] > 0]
        if not available:
            return "No vehicles are available"
        parts = [f"{t['count']} {t['label']}" for t in available]
        if len(parts) == 1:
            return f"{parts[0]} are available"
        return f"{', '.join(parts[:-1])} and {parts[-1]} are available"

    stations = []
    for row in info_rows:
        try:
            lat = float(row.get("lat"))
            lon = float(row.get("lon"))
        except (TypeError, ValueError):
            continue
        if not lat or not lon:
            continue

        station_id = str(row.get("station_id", "")).strip()
        status = status_by_id.get(station_id, {})
        vehicle_types = _vehicle_types_available(status)
        num_vehicles_disabled = status.get("num_vehicles_disabled")
        if num_vehicles_disabled is None:
            num_vehicles_disabled = (
                _as_int(status.get("num_bikes_disabled")) +
                _as_int(status.get("num_scooters_unavailable"))
            )

        stations.append({
            "station_id": station_id,
            "name": row.get("name", "").strip(),
            "short_name": row.get("short_name", "").strip(),
            "capacity": _as_int(row.get("capacity")),
            "lat": lat,
            "lon": lon,
            "vehicle_types_available": vehicle_types,
            "vehicle_types_available_label": _available_label(vehicle_types),
            "vehicle_types_available_count": sum(t["count"] for t in vehicle_types),
            "num_vehicles_disabled": _as_int(num_vehicles_disabled),
            "num_docks_available": _as_int(status.get("num_docks_available")),
            "last_reported": status.get("last_reported"),
        })

    print(f"[divvy_stations] cached {len(stations)} GBFS stations")
    _divvy_stations_cache["data"] = stations
    _divvy_stations_cache["expires"] = now + timedelta(seconds=60)
    return stations


async def _fetch_divvy_feed_urls() -> dict:
    now = datetime.now(timezone.utc)
    if (_divvy_feeds_cache["data"] and _divvy_feeds_cache["expires"] and
            now < _divvy_feeds_cache["expires"]):
        return _divvy_feeds_cache["data"]

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as http:
        r = await http.get(_DIVVY_GBFS_URL, headers={"User-Agent": "opengrid-service/1.0"})
        r.raise_for_status()
        payload = r.json()

    data = payload.get("data") or {}
    locale = data.get("en") or next(iter(data.values()), {})
    feeds = locale.get("feeds") or []
    result = {
        feed.get("name"): feed.get("url")
        for feed in feeds
        if feed.get("name") and feed.get("url")
    }
    for required in ("station_information", "station_status", "vehicle_types"):
        if required not in result:
            raise RuntimeError(f"Divvy GBFS feed missing {required}")

    _divvy_feeds_cache["data"] = result
    _divvy_feeds_cache["expires"] = now + _CACHE_TTL
    return result


async def _fetch_divvy_station_information(feeds: dict) -> list[dict]:
    now = datetime.now(timezone.utc)
    if (_divvy_station_info_cache["data"] and _divvy_station_info_cache["expires"] and
            now < _divvy_station_info_cache["expires"]):
        return _divvy_station_info_cache["data"]

    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get(feeds["station_information"], headers={"User-Agent": "opengrid-service/1.0"})
        r.raise_for_status()
        payload = r.json()

    stations = (payload.get("data") or {}).get("stations") or []
    ttl = int(payload.get("ttl") or 3600)
    _divvy_station_info_cache["data"] = stations
    _divvy_station_info_cache["expires"] = now + timedelta(seconds=max(ttl, 300))
    return stations


async def _fetch_divvy_station_status(feeds: dict) -> dict:
    now = datetime.now(timezone.utc)
    if (_divvy_station_status_cache["data"] and _divvy_station_status_cache["expires"] and
            now < _divvy_station_status_cache["expires"]):
        return _divvy_station_status_cache["data"]

    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get(feeds["station_status"], headers={"User-Agent": "opengrid-service/1.0"})
        r.raise_for_status()
        payload = r.json()

    stations = (payload.get("data") or {}).get("stations") or []
    result = {
        str(station.get("station_id", "")).strip(): station
        for station in stations
        if station.get("station_id")
    }
    ttl = int(payload.get("ttl") or 60)
    _divvy_station_status_cache["data"] = result
    _divvy_station_status_cache["expires"] = now + timedelta(seconds=max(ttl, 30))
    return result


async def _fetch_divvy_vehicle_type_labels(feeds: dict) -> dict:
    now = datetime.now(timezone.utc)
    if (_divvy_vehicle_types_cache["data"] and _divvy_vehicle_types_cache["expires"] and
            now < _divvy_vehicle_types_cache["expires"]):
        return _divvy_vehicle_types_cache["data"]

    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(feeds["vehicle_types"], headers={"User-Agent": "opengrid-service/1.0"})
        r.raise_for_status()
        payload = r.json()

    labels = {}
    for vehicle in (payload.get("data") or {}).get("vehicle_types") or []:
        vehicle_type_id = str(vehicle.get("vehicle_type_id", "")).strip()
        form_factor = str(vehicle.get("form_factor", "")).strip()
        propulsion = str(vehicle.get("propulsion_type", "")).strip()
        if form_factor == "bicycle" and propulsion == "electric_assist":
            label = "e-bikes"
        elif form_factor == "bicycle":
            label = "classic bikes"
        elif form_factor == "scooter":
            label = "scooters"
        else:
            label = (form_factor or "vehicles").replace("_", " ")
        if vehicle_type_id:
            labels[vehicle_type_id] = label
    ttl = int(payload.get("ttl") or 3600)
    _divvy_vehicle_types_cache["data"] = labels
    _divvy_vehicle_types_cache["expires"] = now + timedelta(seconds=max(ttl, 300))
    return labels


@router.get("/stations/divvy-stations")
async def divvy_stations(
    minLat: float = Query(...), minLon: float = Query(...),
    maxLat: float = Query(...), maxLon: float = Query(...),
):
    """Divvy bike stations within a bounding box."""
    try:
        all_stations = await _fetch_divvy_stations()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"Divvy station data unavailable: {e}")
    return [
        s for s in all_stations
        if minLat <= s["lat"] <= maxLat and minLon <= s["lon"] <= maxLon
    ]


# ---------------------------------------------------------------------------
# Open Air Chicago air-quality sensors
# ---------------------------------------------------------------------------

def _open_air_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _open_air_coords(row: dict) -> tuple[float | None, float | None]:
    loc = row.get("location") or {}
    coords = loc.get("coordinates") if isinstance(loc, dict) else None
    if coords and len(coords) >= 2:
        try:
            return float(coords[1]), float(coords[0])
        except (TypeError, ValueError):
            pass
    try:
        return float(row.get("latitude")), float(row.get("longitude"))
    except (TypeError, ValueError):
        return None, None


def _open_air_time_label(timestamp: str) -> str:
    if not timestamp:
        return ""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_CHICAGO_TZ).strftime("%-I %p")
    except Exception:
        return timestamp[11:16] if len(timestamp) >= 16 else timestamp


def _open_air_row(row: dict) -> dict | None:
    lat, lon = _open_air_coords(row)
    if lat is None or lon is None:
        return None
    sensor_id = str(row.get("datasourceid", "")).strip()
    if not sensor_id:
        return None
    values = {}
    for field in _OPEN_AIR_FIELDS:
        if field in ("datasourceid", "startofperiod", "sensor_name", "location", "latitude", "longitude"):
            continue
        values[field] = _open_air_float(row.get(field))
    return {
        "datasourceid": sensor_id,
        "sensor_name": row.get("sensor_name", "").strip(),
        "startofperiod": row.get("startofperiod", ""),
        "time_label": _open_air_time_label(row.get("startofperiod", "")),
        "lat": lat,
        "lon": lon,
        "values": values,
    }


def _open_air_group_payload(current: dict, history: list[dict]) -> list[dict]:
    groups = []
    for group in _OPEN_AIR_GROUPS:
        trend_field = group["trend_field"]
        values = [
            {
                "field": field,
                "label": label,
                "value": current["values"].get(field),
            }
            for field, label in group["values"]
        ]
        groups.append({
            "id": group["id"],
            "title": group["title"],
            "color": group["color"],
            "pill_value": current["values"].get(trend_field),
            "trend_field": trend_field,
            "trend_label": values[0]["label"] if values else "",
            "values": values,
            "history": [
                {
                    "time": row["startofperiod"],
                    "label": row["time_label"],
                    "value": row["values"].get(trend_field),
                }
                for row in history
            ],
        })
    return groups


async def _fetch_open_air_latest() -> list[dict]:
    """Fetch recent Open Air rows and keep the latest record per sensor."""
    now = datetime.now(timezone.utc)
    if (_open_air_sensors_cache["data"] and _open_air_sensors_cache["expires"] and
            now < _open_air_sensors_cache["expires"]):
        return _open_air_sensors_cache["data"]

    params = {
        "$select": ",".join(_OPEN_AIR_FIELDS),
        "$order": "startofperiod DESC",
        "$limit": 10000,
    }
    async with httpx.AsyncClient(headers=_socrata_headers(), timeout=45) as http:
        r = await http.get(_OPEN_AIR_URL, params=params)
        r.raise_for_status()
        rows = r.json()

    latest_by_sensor = {}
    for raw in rows:
        parsed = _open_air_row(raw)
        if not parsed or parsed["datasourceid"] in latest_by_sensor:
            continue
        latest_by_sensor[parsed["datasourceid"]] = parsed

    sensors = sorted(latest_by_sensor.values(), key=lambda s: s["sensor_name"])
    print(f"[open_air] cached {len(sensors)} latest sensors")
    _open_air_sensors_cache["data"] = sensors
    _open_air_sensors_cache["expires"] = now + timedelta(minutes=10)
    return sensors


async def _fetch_open_air_detail(datasourceid: str) -> dict:
    sensor_id = datasourceid.strip()
    now = datetime.now(timezone.utc)
    cached = _open_air_sensor_detail_cache.get(sensor_id)
    if cached and cached["expires"] and now < cached["expires"]:
        return cached["data"]

    escaped = sensor_id.replace("'", "''")
    params = {
        "$select": ",".join(_OPEN_AIR_FIELDS),
        "$where": f"datasourceid='{escaped}'",
        "$order": "startofperiod DESC",
        "$limit": 24,
    }
    async with httpx.AsyncClient(headers=_socrata_headers(), timeout=30) as http:
        r = await http.get(_OPEN_AIR_URL, params=params)
        r.raise_for_status()
        rows = r.json()

    history_desc = []
    for raw in rows:
        parsed = _open_air_row(raw)
        if parsed:
            history_desc.append(parsed)
    if not history_desc:
        raise KeyError(sensor_id)

    current = history_desc[0]
    history = list(reversed(history_desc))
    payload = {
        "datasourceid": current["datasourceid"],
        "sensor_name": current["sensor_name"],
        "title": f"{current['sensor_name']} Open Air Chicago Sensor",
        "startofperiod": current["startofperiod"],
        "time_label": current["time_label"],
        "lat": current["lat"],
        "lon": current["lon"],
        "groups": _open_air_group_payload(current, history),
    }
    _open_air_sensor_detail_cache[sensor_id] = {
        "data": payload,
        "expires": now + timedelta(minutes=10),
    }
    return payload


@router.get("/stations/open-air-sensors")
async def open_air_sensors(
    minLat: float = Query(...), minLon: float = Query(...),
    maxLat: float = Query(...), maxLon: float = Query(...),
):
    """Open Air Chicago latest sensor locations within a bounding box."""
    try:
        all_sensors = await _fetch_open_air_latest()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"Open Air Chicago data unavailable: {e}")
    return [
        s for s in all_sensors
        if minLat <= s["lat"] <= maxLat and minLon <= s["lon"] <= maxLon
    ]


@router.get("/stations/open-air-sensor")
async def open_air_sensor(datasourceid: str = Query(..., description="Open Air datasourceid")):
    """Open Air Chicago latest readings and 24-hour trend history for one sensor."""
    try:
        return await _fetch_open_air_detail(datasourceid)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Open Air sensor not found: {datasourceid}")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"Open Air Chicago sensor data unavailable: {e}")


# ---------------------------------------------------------------------------
# Metra commuter rail — static GTFS schedule
# ---------------------------------------------------------------------------

async def _fetch_metra_zip() -> bytes:
    now = datetime.now(timezone.utc)
    if _metra_zip_cache["data"] and _metra_zip_cache["expires"] and now < _metra_zip_cache["expires"]:
        return _metra_zip_cache["data"]
    print(f"[metra] downloading GTFS from {_METRA_GTFS_URL}")
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as http:
        r = await http.get(_METRA_GTFS_URL, headers={"User-Agent": "opengrid-service/1.0"})
        print(f"[metra] GTFS response: status={r.status_code} content-type={r.headers.get('content-type')} size={len(r.content)}")
        r.raise_for_status()
        _metra_zip_cache["data"] = r.content
        _metra_zip_cache["expires"] = now + _CACHE_TTL
    return _metra_zip_cache["data"]


async def _parse_metra_data() -> dict:
    """Parse all needed Metra data from GTFS in one pass. Cached 24h."""
    now = datetime.now(timezone.utc)
    if _metra_parsed_cache["data"] and _metra_parsed_cache["expires"] and now < _metra_parsed_cache["expires"]:
        return _metra_parsed_cache["data"]

    content = await _fetch_metra_zip()

    def _csv(fileobj):
        """Yield GTFS rows with header names AND values stripped of surrounding
        whitespace. Metra pads every field with a leading space after the comma
        (e.g. ' 1', ' 20260603'), which silently breaks exact-match comparisons
        like the calendar day flags (" 1" == "1" is False)."""
        wrapper = io.TextIOWrapper(fileobj, encoding="utf-8-sig")
        reader  = csv.DictReader(wrapper)
        _       = reader.fieldnames          # trigger header read
        reader.fieldnames = [n.strip() for n in reader.fieldnames]
        for row in reader:
            yield {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}

    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = zf.namelist()

        # Routes
        routes: dict[str, dict] = {}
        with zf.open("routes.txt") as f:
            for row in _csv(f):
                rid   = row.get("route_id", "").strip()
                if not rid:
                    continue
                color = row.get("route_color", "").strip()
                routes[rid] = {
                    "short_name": row.get("route_short_name", "").strip(),
                    "long_name":  row.get("route_long_name", "").strip(),
                    "color":      "#" + color if color else "#7b2433",
                }

        # Stops
        stops: list[dict] = []
        with zf.open("stops.txt") as f:
            for row in _csv(f):
                try:
                    lat = float(row.get("stop_lat") or 0)
                    lon = float(row.get("stop_lon") or 0)
                except (ValueError, TypeError):
                    continue
                if lat and lon:
                    stops.append({
                        "stop_id":   row.get("stop_id", "").strip(),
                        "stop_name": row.get("stop_name", "").strip(),
                        "lat":       lat,
                        "lon":       lon,
                    })

        # Calendar
        calendar: dict[str, dict] = {}
        if "calendar.txt" in names:
            with zf.open("calendar.txt") as f:
                _DAYS = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
                for row in _csv(f):
                    sid = row.get("service_id","").strip()
                    calendar[sid] = {
                        "days":       [row.get(d,"0")=="1" for d in _DAYS],
                        "start_date": row.get("start_date","").strip(),
                        "end_date":   row.get("end_date","").strip(),
                    }

        cal_dates: list[dict] = []
        if "calendar_dates.txt" in names:
            with zf.open("calendar_dates.txt") as f:
                for row in _csv(f):
                    cal_dates.append({
                        "service_id":     row.get("service_id","").strip(),
                        "date":           row.get("date","").strip(),
                        "exception_type": row.get("exception_type","").strip(),
                    })

        # Trips + route→shape mapping in one pass
        trips: dict[str, dict] = {}
        route_shapes: dict[str, set] = {r: set() for r in routes}
        with zf.open("trips.txt") as f:
            for row in _csv(f):
                tid = row.get("trip_id","").strip()
                rid = row.get("route_id","").strip()
                sid = row.get("service_id","").strip()
                shp = row.get("shape_id","").strip()
                hts = row.get("trip_headsign","").strip()
                if not tid:
                    continue
                trips[tid] = {"route_id": rid, "service_id": sid, "headsign": hts, "shape_id": shp}
                if rid in route_shapes and shp:
                    route_shapes[rid].add(shp)

        # Stop times index: stop_id → sorted list of (dep_secs, trip_id)
        stop_times: dict[str, list] = {}
        with zf.open("stop_times.txt") as f:
            for row in _csv(f):
                sid   = row.get("stop_id","").strip()
                tid   = row.get("trip_id","").strip()
                t_str = (row.get("departure_time") or row.get("arrival_time") or "").strip()
                if not sid or not tid:
                    continue
                try:
                    h, m, s = [int(x) for x in t_str.split(":")]
                    dep_secs = h * 3600 + m * 60 + s
                except (ValueError, AttributeError):
                    continue
                if sid not in stop_times:
                    stop_times[sid] = []
                stop_times[sid].append((dep_secs, tid))
        for lst in stop_times.values():
            lst.sort()

        # Route shapes GeoJSON
        needed: set[str] = set().union(*route_shapes.values()) if route_shapes else set()
        shape_pts: dict[str, list] = {s: [] for s in needed}
        if "shapes.txt" in names:
            with zf.open("shapes.txt") as f:
                for row in _csv(f):
                    s = row.get("shape_id","").strip()
                    if s in shape_pts:
                        shape_pts[s].append((
                            int(row["shape_pt_sequence"]),
                            float(row["shape_pt_lon"]),
                            float(row["shape_pt_lat"]),
                        ))

        features = []
        for rid, route in routes.items():
            lines = []
            for shp in route_shapes.get(rid, set()):
                pts = sorted(shape_pts.get(shp, []), key=lambda x: x[0])
                if pts:
                    lines.append([[p[1], p[2]] for p in pts])
            if not lines:
                continue
            geom = ({"type": "MultiLineString", "coordinates": lines}
                    if len(lines) > 1
                    else {"type": "LineString", "coordinates": lines[0]})
            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "route_id":   rid,
                    "short_name": route["short_name"],
                    "long_name":  route["long_name"],
                    "color":      route["color"],
                },
            })
        lines_geojson = {"type": "FeatureCollection", "features": features}

    result = {
        "stops":        stops,
        "routes":       routes,
        "lines_geojson": lines_geojson,
        "calendar":     calendar,
        "cal_dates":    cal_dates,
        "trips":        trips,
        "stop_times":   stop_times,
    }
    print(f"[metra] parsed: {len(stops)} stops, {len(routes)} routes, {len(trips)} trips")
    _metra_parsed_cache["data"]    = result
    _metra_parsed_cache["expires"] = now + _CACHE_TTL
    return result


def _metra_active_services(calendar: dict, cal_dates: list, today_str: str, dow: int) -> set[str]:
    active: set[str] = set()
    for sid, cal in calendar.items():
        if cal["start_date"] <= today_str <= cal["end_date"] and cal["days"][dow]:
            active.add(sid)
    for exc in cal_dates:
        if exc["date"] == today_str:
            if exc["exception_type"] == "1":
                active.add(exc["service_id"])
            elif exc["exception_type"] == "2":
                active.discard(exc["service_id"])
    return active


@router.get("/stations/metra-stations")
async def metra_stations():
    """Metra station list from GTFS stops.txt."""
    try:
        data = await _parse_metra_data()
        return data["stops"]
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"Metra data unavailable: {e}")


@router.get("/stations/metra-lines")
async def metra_lines():
    """Metra rail line shapes as GeoJSON from GTFS shapes.txt."""
    try:
        data = await _parse_metra_data()
        return data["lines_geojson"]
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"Metra data unavailable: {e}")


@router.get("/stations/metra-departures")
async def metra_departures(stop_id: str = Query(..., description="Metra GTFS stop_id")):
    """Next scheduled departures from a Metra station, from static GTFS."""
    try:
        data = await _parse_metra_data()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=503, detail=f"Metra data unavailable: {e}")

    now      = datetime.now(_CHICAGO_TZ)
    today    = now.strftime("%Y%m%d")
    dow      = now.weekday()   # 0=Mon … 6=Sun
    now_secs = now.hour * 3600 + now.minute * 60 + now.second

    active   = _metra_active_services(data["calendar"], data["cal_dates"], today, dow)
    # Fallback: GTFS calendar may not cover today — use any service for this day-of-week
    if not active:
        for sid, cal in data["calendar"].items():
            if cal["days"][dow]:
                active.add(sid)

    raw      = data["stop_times"].get(stop_id, [])
    routes   = data["routes"]
    trips    = data["trips"]

    departures = []
    for dep_secs, trip_id in raw:
        if dep_secs <= now_secs:
            continue
        trip = trips.get(trip_id)
        if not trip or trip["service_id"] not in active:
            continue
        route = routes.get(trip["route_id"], {})
        minutes = round((dep_secs - now_secs) / 60)
        h = dep_secs // 3600
        m = (dep_secs % 3600) // 60
        ampm = "AM" if h % 24 < 12 else "PM"
        h12  = h % 12 or 12
        departures.append({
            "route_id":    trip["route_id"],
            "route_name":  route.get("short_name", trip["route_id"]),
            "route_color": route.get("color", "#7b2433"),
            "headsign":    trip["headsign"],
            "time_str":    f"{h12}:{m:02d} {ampm}",
            "minutes":     minutes,
            "dep_secs":    dep_secs,
        })

    departures.sort(key=lambda d: d["dep_secs"])
    return departures[:15]
