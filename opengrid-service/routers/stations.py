"""
/stations/* — fixed geographic stations with real-time sensor data.
Each station has a known location and pulls from a public data feed.
"""
import asyncio
import os
import traceback
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter()

_GLERL_BASE = "https://www.glerl.noaa.gov/metdata/chi"
_BEACH_DNA_URL = "https://data.cityofchicago.org/resource/hmqm-anjq.json"
_BEACH_WEATHER_LOC_URL = "https://data.cityofchicago.org/resource/g3ip-u8rb.json"   # sensor locations
_BEACH_WEATHER_OBS_URL = "https://data.cityofchicago.org/resource/k7hf-8y75.json"   # measurements


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
