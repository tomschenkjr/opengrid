"""
Census ACS demographic profiles aggregated to Chicago community areas.

At startup this fetches American Community Survey (ACS) 5-year estimates for every
census tract in Cook County, aggregates them up to the 77 community areas using the
tract→community-area crosswalk built in services.geography, and caches a full
Census-Reporter–style profile per community area (5 sections: Demographics, Economics,
Families, Housing, Social) plus a citywide reference for the header comparison.

The Census Data API requires a free API key (CENSUS_API_KEY). Without one the API
redirects to a "Missing Key" page; in that case the caches stay empty and the
community-profile endpoint degrades gracefully.

Aggregation notes:
  - Count fields (the vast majority — age/income/education/housing buckets, etc.) are
    summed across tracts, so derived percentages and distributions are exact.
  - Median fields (gross rent, age, household income, home value) and per-capita income
    cannot be summed; we approximate the community-area value as a tract-median weighted
    average (rent→renter units, age & per-capita→population, HH income→households,
    home value→owner units). Mean travel time is computed exactly from aggregate travel
    time ÷ commuters. Citywide medians come straight from the place-level estimate.
    TODO: switch weighted medians to bucket-interpolation for full accuracy.
"""

import copy
import os
import httpx

from services import economic_development, geography, health_atlas

_CENSUS_BASE = "https://api.census.gov/data"
_CHUNK = 45  # Census API allows ≤ 50 variables per request; leave headroom for NAME + geo.


def _rng(table: str, start: int, end: int) -> list[str]:
    """Expand an inclusive ACS variable range, e.g. _rng('B15003', 1, 25)."""
    return [f"{table}_{i:03d}E" for i in range(start, end + 1)]


# Full variable set. Compact tables are pulled whole (range); very large tables
# (B05006 has 178 vars, B05002/C16001/B07003) use only the columns we need.
_VARS: list[str] = list(dict.fromkeys(
    ["B01003_001E", "B01002_001E", "B25064_001E"]      # population, median age, median rent
    + _rng("B01001", 1, 49)                            # sex by age
    + ["B03002_001E", "B03002_003E", "B03002_004E", "B03002_005E",
       "B03002_006E", "B03002_007E", "B03002_008E", "B03002_009E", "B03002_012E"]  # race/Hispanic
    + ["B19301_001E", "B19013_001E"]                   # per-capita & median HH income
    + _rng("B19001", 1, 17)                            # HH income distribution
    + _rng("B17001", 1, 59)                            # poverty by sex by age
    + _rng("B28001", 1, 11)                            # computer/device types in households
    + _rng("B28003", 1, 6)                             # computer + internet subscription status
    + _rng("B28005", 1, 19)                            # age by computer + internet subscription
    + ["B08013_001E", "B08303_001E"]                   # aggregate travel time, commuters
    + _rng("B08301", 1, 21)                            # means of transportation to work
    + _rng("B11001", 1, 9)                             # household type
    + ["B11002_001E"]                                  # population in households
    + _rng("B12001", 1, 19)                            # marital status by sex
    + _rng("B13016", 1, 10)                            # fertility
    + ["B25001_001E"]                                  # housing units
    + _rng("B25002", 1, 3)                             # occupancy
    + _rng("B25003", 1, 3)                             # tenure
    + _rng("B25024", 1, 11)                            # units in structure
    + _rng("B25038", 1, 15)                            # year householder moved in
    + ["B25077_001E"] + _rng("B25075", 1, 27)          # median value, value distribution
    + ["B07003_001E", "B07003_004E", "B07003_007E",
       "B07003_010E", "B07003_013E", "B07003_016E"]    # geographic mobility
    + _rng("B15003", 1, 25)                            # educational attainment
    + ["C16001_001E", "C16001_002E"]                   # language other than English
    + _rng("B16007", 1, 19)                            # language by age
    + ["B05002_001E", "B05002_013E"]                   # place of birth (foreign-born)
    + ["B05006_001E", "B05006_002E", "B05006_047E", "B05006_095E",
       "B05006_130E", "B05006_139E", "B05006_176E"]    # foreign-born region
    + ["B21001_001E", "B21001_002E", "B21001_005E", "B21001_023E"]  # veterans total/M/F
    + _rng("B21002", 1, 16)                            # veterans by period of service
))

# Weighted-median definitions: metric → (value var, weight var).
_WEIGHTED = {
    "rent":      ("B25064_001E", "B25003_003E"),
    "age":       ("B01002_001E", "B01003_001E"),
    "hhincome":  ("B19013_001E", "B11001_001E"),
    "homevalue": ("B25077_001E", "B25003_002E"),
    "percapita": ("B19301_001E", "B01003_001E"),
}

# Caches populated at startup.
_profiles: dict[int, dict] = {}   # community area number → full profile dict
_citywide: dict = {}              # citywide header metrics
_citywide_sections: list = []     # citywide detailed sections
_acs_year: int = 0


# --------------------------------------------------------------------------- #
# Fetch + aggregate
# --------------------------------------------------------------------------- #
def _num(val) -> float | None:
    """Parse a Census value, treating null/jam sentinels (negatives) as missing."""
    if val in (None, ""):
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f >= 0 else None  # ACS encodes suppressed values as large negatives


def _rows_to_dicts(payload: list[list]) -> list[dict]:
    """Convert a Census [[header...],[row...],...] response to a list of dicts."""
    if not payload or len(payload) < 2:
        return []
    header = payload[0]
    return [dict(zip(header, row)) for row in payload[1:]]


def _geo_key(row: dict) -> tuple:
    """Stable identity for a geography row, to merge variable batches."""
    return (row.get("state"), row.get("county"), row.get("tract"), row.get("place"))


async def _fetch_many(http: httpx.AsyncClient, geo_params: dict, key: str) -> list[dict]:
    """Fetch all _VARS for a geography in ≤45-variable batches, merged by geo key."""
    merged: dict[tuple, dict] = {}
    for i in range(0, len(_VARS), _CHUNK):
        chunk = _VARS[i:i + _CHUNK]
        params = {"get": ",".join(["NAME"] + chunk), "key": key, **geo_params}
        r = await http.get(f"{_CENSUS_BASE}/{_acs_year}/acs/acs5", params=params)
        r.raise_for_status()
        for row in _rows_to_dicts(r.json()):
            merged.setdefault(_geo_key(row), {}).update(row)
    return list(merged.values())


def _new_sums() -> dict:
    return {"v": {}, "w": {m: [0.0, 0.0] for m in _WEIGHTED}}


def _accumulate(sums: dict, row: dict):
    """Add one geography's values into a running sums dict (sum counts, weight medians)."""
    v = sums["v"]
    for var in _VARS:
        n = _num(row.get(var))
        if n is not None:
            v[var] = v.get(var, 0.0) + n
    for metric, (vvar, wvar) in _WEIGHTED.items():
        val = _num(row.get(vvar))
        wt = _num(row.get(wvar))
        if val is not None and wt and wt > 0:
            acc = sums["w"][metric]
            acc[0] += val * wt
            acc[1] += wt


# --------------------------------------------------------------------------- #
# Header metrics (KPI cards + citywide comparison) — unchanged contract
# --------------------------------------------------------------------------- #
def _header_metrics(sums: dict) -> dict:
    v = sums["v"]

    def g(*names):
        return sum(v.get(n, 0) for n in names)

    def pct(part, whole):
        return round(part / whole * 100, 1) if whole else None

    def wmed(metric, ndigits=0):
        vw, w = sums["w"][metric]
        return round(vw / w, ndigits) if w else None

    occupied = g("B25003_001E")
    edu_total = g("B15003_001E")
    age_total = g("B01001_001E")
    pop_65 = g("B01001_020E", "B01001_021E", "B01001_022E", "B01001_023E", "B01001_024E",
               "B01001_025E", "B01001_044E", "B01001_045E", "B01001_046E", "B01001_047E",
               "B01001_048E", "B01001_049E")
    bachelors = g("B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E")
    return {
        "population": round(g("B01003_001E")),
        "median_rent": wmed("rent"),
        "median_age": wmed("age", 1),
        "renter_pct": pct(g("B25003_003E"), occupied),
        "bachelors_pct": pct(bachelors, edu_total),
        "pct_65": pct(pop_65, age_total),
    }


# --------------------------------------------------------------------------- #
# Sectioned profile builder
# --------------------------------------------------------------------------- #
def _build_sections(sums: dict) -> list[dict]:
    v = sums["v"]

    def g(*names):
        return round(sum(v.get(n, 0) for n in names))

    def pct(part, whole):
        return round(part / whole * 100, 1) if whole else None

    def wmed(metric, ndigits=0):
        vw, w = sums["w"][metric]
        return round(vw / w, ndigits) if w else None

    def stat(label, value, fmt, unit=None):
        item = {"type": "stat", "label": label, "value": value, "format": fmt}
        if unit:
            item["unit"] = unit
        return item

    def stat_list(items):
        return {"type": "stat_list", "items": items}

    def pie(label, slices):
        return {"type": "pie", "label": label,
                "slices": [{"label": l, "value": val} for l, val in slices]}

    def bars(kind, label, bins, fmt="count"):
        return {"type": kind, "label": label, "format": fmt,
                "bins": [{"label": l, "value": val} for l, val in bins]}

    def grouped(label, categories, series):
        return {"type": "grouped_column", "label": label, "categories": categories,
                "series": [{"label": s_label, "values": vals} for s_label, vals in series]}

    def stacked(label, segments):
        return {"type": "stacked_column", "label": label,
                "segments": [{"label": l, "value": val} for l, val in segments]}

    # B01001 bracket helper (male/female pairs of the same age band)
    def B(*nums):
        return g(*[f"B01001_{n:03d}E" for n in nums])

    total_pop = g("B01003_001E")
    under18 = B(3, 4, 5, 6, 27, 28, 29, 30)
    pop65 = B(20, 21, 22, 23, 24, 25, 44, 45, 46, 47, 48, 49)

    # ---- Demographics ----------------------------------------------------- #
    demographics = {
        "id": "demographics", "title": "Demographics",
        "groups": [
            {"id": "age", "title": "Age", "items": [
                stat("Median age", wmed("age", 1), "decimal", "years"),
                bars("histogram", "Population by age range", [
                    ("0-9", B(3, 4, 27, 28)),
                    ("10-19", B(5, 6, 7, 29, 30, 31)),
                    ("20-29", B(8, 9, 10, 11, 32, 33, 34, 35)),
                    ("30-39", B(12, 13, 36, 37)),
                    ("40-49", B(14, 15, 38, 39)),
                    ("50-59", B(16, 17, 40, 41)),
                    ("60-69", B(18, 19, 20, 21, 42, 43, 44, 45)),
                    ("70-79", B(22, 23, 46, 47)),
                    ("80+", B(24, 25, 48, 49)),
                ]),
                pie("Population by age category", [
                    ("Under 18", under18),
                    ("18 to 64", max(total_pop - under18 - pop65, 0)),
                    ("65 and over", pop65),
                ]),
            ]},
            {"id": "sex", "title": "Sex", "items": [
                pie("Population by sex", [
                    ("Male", B(2)), ("Female", B(26)),
                ]),
            ]},
            {"id": "race", "title": "Race & Ethnicity", "items": [
                bars("column", "Race & Hispanic/Latino origin", [
                    ("White", g("B03002_003E")),
                    ("Black", g("B03002_004E")),
                    ("Native", g("B03002_005E")),
                    ("Asian", g("B03002_006E")),
                    ("Islander", g("B03002_007E")),
                    ("Other", g("B03002_008E")),
                    ("Two+", g("B03002_009E")),
                    ("Hispanic", g("B03002_012E")),
                ]),
            ]},
        ],
    }

    # ---- Economics -------------------------------------------------------- #
    economics = {
        "id": "economics", "title": "Economics",
        "groups": [
            {"id": "income", "title": "Income", "items": [
                stat_list([
                    {"label": "Per capita income", "value": wmed("percapita"), "format": "currency"},
                    {"label": "Median household income", "value": wmed("hhincome"), "format": "currency"},
                ]),
                bars("histogram", "Household income", [
                    ("Under $50K", g(*_rng("B19001", 2, 10))),
                    ("$50K-$100K", g("B19001_011E", "B19001_012E", "B19001_013E")),
                    ("$100K-$200K", g("B19001_014E", "B19001_015E", "B19001_016E")),
                    ("Over $200K", g("B19001_017E")),
                ], "count"),
            ]},
            {"id": "poverty", "title": "Poverty", "items": [
                stat("Persons below poverty line",
                     pct(g("B17001_002E"), g("B17001_001E")), "percent"),
                pie("Children (Under 18)", [
                    ("Poverty", g("B17001_004E", "B17001_005E", "B17001_006E", "B17001_007E",
                                  "B17001_008E", "B17001_009E", "B17001_018E", "B17001_019E",
                                  "B17001_020E", "B17001_021E", "B17001_022E", "B17001_023E")),
                    ("Non-poverty", g("B17001_033E", "B17001_034E", "B17001_035E", "B17001_036E",
                                      "B17001_037E", "B17001_038E", "B17001_047E", "B17001_048E",
                                      "B17001_049E", "B17001_050E", "B17001_051E", "B17001_052E")),
                ]),
                pie("Seniors (65 and over)", [
                    ("Poverty", g("B17001_015E", "B17001_016E", "B17001_029E", "B17001_030E")),
                    ("Non-poverty", g("B17001_044E", "B17001_045E", "B17001_058E", "B17001_059E")),
                ]),
            ]},
            {"id": "computing_devices", "title": "Computing Devices", "items": [
                stat("Households with one or more computing devices",
                     pct(g("B28001_002E"), g("B28001_001E")), "percent"),
                stacked("Types of computers in household", [
                    ("Desktop/laptop only", g("B28001_004E")),
                    ("Smartphone only", g("B28001_006E")),
                    ("Tablet only", g("B28001_008E")),
                    ("Other computer only", g("B28001_010E")),
                    ("Multiple device types",
                     max(g("B28001_002E") -
                         g("B28001_004E", "B28001_006E", "B28001_008E", "B28001_010E"), 0)),
                    ("No computer", g("B28001_011E")),
                ]),
            ]},
            {"id": "internet_access", "title": "Internet Access", "items": [
                stat("Under 18 with a computer and broadband",
                     pct(g("B28005_005E"), g("B28005_002E")), "percent"),
                bars("histogram", "Computer and internet subscription in household", [
                    ("Broadband", g("B28003_004E")),
                    ("Dial-up only", g("B28003_003E")),
                    ("Computer, no internet", g("B28003_005E")),
                    ("No computer", g("B28003_006E")),
                ]),
            ]},
            {"id": "transportation", "title": "Transportation to Work", "items": [
                stat("Mean travel time to work",
                     round(g("B08013_001E") / g("B08303_001E"), 1) if g("B08303_001E") else None,
                     "decimal", "minutes"),
                bars("histogram", "Means of transportation to work", [
                    ("Drove alone", g("B08301_003E")),
                    ("Carpooled", g("B08301_004E")),
                    ("Public transit", g("B08301_010E")),
                    ("Bicycle", g("B08301_018E")),
                    ("Walked", g("B08301_019E")),
                    ("Other", g("B08301_016E", "B08301_017E", "B08301_020E")),
                    ("Worked at home", g("B08301_021E")),
                ]),
            ]},
        ],
    }

    # ---- Families --------------------------------------------------------- #
    households = g("B11001_001E")
    families = {
        "id": "families", "title": "Families",
        "groups": [
            {"id": "households", "title": "Households", "items": [
                stat_list([
                    {"label": "Number of households", "value": households, "format": "count"},
                    {"label": "Persons per household",
                     "value": round(g("B11002_001E") / households, 2) if households else None,
                     "format": "decimal"},
                ]),
                pie("Population by household type", [
                    ("Married-couple", g("B11001_003E")),
                    ("Other family", g("B11001_004E")),
                    ("Nonfamily", g("B11001_007E")),
                ]),
            ]},
            {"id": "marital", "title": "Marital Status", "items": [
                pie("Marital status", [
                    ("Never married", g("B12001_003E", "B12001_012E")),
                    ("Now married", g("B12001_004E", "B12001_013E")),
                    ("Widowed", g("B12001_009E", "B12001_018E")),
                    ("Divorced", g("B12001_010E", "B12001_019E")),
                ]),
                grouped("Marital status by sex",
                        ["Never married", "Now married", "Widowed", "Divorced"],
                        [("Male", [g("B12001_003E"), g("B12001_004E"),
                                   g("B12001_009E"), g("B12001_010E")]),
                         ("Female", [g("B12001_012E"), g("B12001_013E"),
                                     g("B12001_018E"), g("B12001_019E")])]),
            ]},
            {"id": "fertility", "title": "Fertility", "items": [
                stat("Women 15-50 who gave birth (past year)",
                     pct(g("B13016_002E"), g("B13016_001E")), "percent"),
                bars("column", "Women who gave birth, by age group", [
                    ("15-19", g("B13016_003E")),
                    ("20-24", g("B13016_004E")),
                    ("25-29", g("B13016_005E")),
                    ("30-34", g("B13016_006E")),
                    ("35-39", g("B13016_007E")),
                    ("40-44", g("B13016_008E")),
                    ("45-50", g("B13016_009E")),
                ]),
            ]},
        ],
    }

    # ---- Housing ---------------------------------------------------------- #
    housing = {
        "id": "housing", "title": "Housing",
        "groups": [
            {"id": "units", "title": "Units & Occupancy", "items": [
                stat("Number of housing units", g("B25001_001E"), "count"),
                pie("Occupied vs. vacant", [
                    ("Occupied", g("B25002_002E")), ("Vacant", g("B25002_003E")),
                ]),
                pie("Ownership of occupied units", [
                    ("Owner", g("B25003_002E")), ("Renter", g("B25003_003E")),
                ]),
                pie("Types of structure", [
                    ("1, detached", g("B25024_002E")),
                    ("1, attached", g("B25024_003E")),
                    ("2", g("B25024_004E")),
                    ("3-4", g("B25024_005E")),
                    ("5-9", g("B25024_006E")),
                    ("10+", g("B25024_007E", "B25024_008E", "B25024_009E")),
                    ("Mobile/other", g("B25024_010E", "B25024_011E")),
                ]),
                bars("histogram", "Year moved in", [
                    ("2021+", g("B25038_003E", "B25038_010E")),
                    ("2018-2020", g("B25038_004E", "B25038_011E")),
                    ("2010-2017", g("B25038_005E", "B25038_012E")),
                    ("2000-2009", g("B25038_006E", "B25038_013E")),
                    ("1990-1999", g("B25038_007E", "B25038_014E")),
                    ("Before 1990", g("B25038_008E", "B25038_015E")),
                ]),
            ]},
            {"id": "value", "title": "Value", "items": [
                stat("Median value of owner-occupied units", wmed("homevalue"), "currency"),
                bars("histogram", "Value of owner-occupied units", [
                    ("Under $100K", g(*_rng("B25075", 2, 14))),
                    ("$100K-$200K", g("B25075_015E", "B25075_016E", "B25075_017E", "B25075_018E")),
                    ("$200K-$300K", g("B25075_019E", "B25075_020E")),
                    ("$300K-$500K", g("B25075_021E", "B25075_022E")),
                    ("$500K-$1M", g("B25075_023E", "B25075_024E")),
                    ("$1M+", g("B25075_025E", "B25075_026E", "B25075_027E")),
                ], "count"),
            ]},
            {"id": "mobility", "title": "Geographical Mobility", "items": [
                stat("Moved since previous year",
                     pct(g("B07003_001E") - g("B07003_004E"), g("B07003_001E")), "percent"),
                bars("histogram", "Population migration since previous year", [
                    ("Same house", g("B07003_004E")),
                    ("Within county", g("B07003_007E")),
                    ("Diff. county, same state", g("B07003_010E")),
                    ("Different state", g("B07003_013E")),
                    ("From abroad", g("B07003_016E")),
                ]),
            ]},
        ],
    }

    # ---- Social ----------------------------------------------------------- #
    edu_total = g("B15003_001E")
    social = {
        "id": "social", "title": "Social",
        "groups": [
            {"id": "education", "title": "Educational Attainment", "items": [
                stat_list([
                    {"label": "High school graduate or higher",
                     "value": pct(g(*_rng("B15003", 17, 25)), edu_total), "format": "percent"},
                    {"label": "Bachelor's degree or higher",
                     "value": pct(g(*_rng("B15003", 22, 25)), edu_total), "format": "percent"},
                ]),
                bars("histogram", "Population by level of education", [
                    ("Less than HS", g(*_rng("B15003", 2, 16))),
                    ("HS graduate", g("B15003_017E", "B15003_018E")),
                    ("Some college", g("B15003_019E", "B15003_020E")),
                    ("Associate's", g("B15003_021E")),
                    ("Bachelor's", g("B15003_022E")),
                    ("Graduate/Prof.", g("B15003_023E", "B15003_024E", "B15003_025E")),
                ]),
            ]},
            {"id": "language", "title": "Language", "items": [
                stat("Language other than English spoken at home",
                     pct(g("C16001_001E") - g("C16001_002E"), g("C16001_001E")), "percent"),
                pie("Language at home, children 5-17", [
                    ("English only", g("B16007_003E")),
                    ("Spanish", g("B16007_004E")),
                    ("Other Indo-European", g("B16007_005E")),
                    ("Asian/Pacific Is.", g("B16007_006E")),
                    ("Other", g("B16007_007E")),
                ]),
                pie("Language at home, adults 18+", [
                    ("English only", g("B16007_009E", "B16007_015E")),
                    ("Spanish", g("B16007_010E", "B16007_016E")),
                    ("Other Indo-European", g("B16007_011E", "B16007_017E")),
                    ("Asian/Pacific Is.", g("B16007_012E", "B16007_018E")),
                    ("Other", g("B16007_013E", "B16007_019E")),
                ]),
            ]},
            {"id": "birthplace", "title": "Place of Birth", "items": [
                stat("Foreign-born population",
                     pct(g("B05002_013E"), g("B05002_001E")), "percent"),
                bars("column", "Place of birth for foreign-born", [
                    ("Europe", g("B05006_002E")),
                    ("Asia", g("B05006_047E")),
                    ("Africa", g("B05006_095E")),
                    ("Oceania", g("B05006_130E")),
                    ("Latin America", g("B05006_139E")),
                    ("North America", g("B05006_176E")),
                ]),
            ]},
            {"id": "veterans", "title": "Veteran Status", "items": [
                stat("Population with veteran status",
                     pct(g("B21001_002E"), g("B21001_001E")), "percent"),
                bars("column", "Veterans by wartime service", [
                    ("Gulf War (2001+)", g("B21002_002E", "B21002_003E", "B21002_004E")),
                    ("Gulf War (90-01)", g("B21002_005E", "B21002_006E")),
                    ("Vietnam", g("B21002_007E", "B21002_008E", "B21002_009E")),
                    ("Korea", g("B21002_010E", "B21002_011E")),
                    ("WWII", g("B21002_012E")),
                    ("Other/peacetime", g("B21002_013E", "B21002_014E", "B21002_015E", "B21002_016E")),
                ]),
                stat_list([
                    {"label": "Total veterans", "value": g("B21001_002E"), "format": "count"},
                    {"label": "Male veterans", "value": g("B21001_005E"), "format": "count"},
                    {"label": "Female veterans", "value": g("B21001_023E"), "format": "count"},
                ]),
            ]},
        ],
    }

    return [demographics, economics, families, housing, social]


# --------------------------------------------------------------------------- #
# Lifecycle + public API
# --------------------------------------------------------------------------- #
async def initialize():
    """Fetch ACS tract data, aggregate to community areas, and cache (idempotent)."""
    global _profiles, _citywide, _citywide_sections, _acs_year
    key = os.getenv("CENSUS_API_KEY", "").strip()
    _acs_year = int(os.getenv("ACS_YEAR", "2023"))

    if not key:
        print("ACS: CENSUS_API_KEY not set — community profiles will be unavailable")
        return

    crosswalk = geography.tract_to_commarea()
    if not crosswalk:
        print("ACS: tract→community-area crosswalk is empty — cannot aggregate ACS data")
        return

    try:
        async with httpx.AsyncClient(timeout=120) as http:
            tracts = await _fetch_many(http, {"for": "tract:*", "in": "state:17 county:031"}, key)
            place = await _fetch_many(http, {"for": "place:14000", "in": "state:17"}, key)
    except Exception as e:
        print(f"ACS: failed to fetch Census data: {e}")
        return

    by_ca: dict[int, dict] = {}
    matched = 0
    for row in tracts:
        tractce = (row.get("tract") or "").zfill(6)
        ca = crosswalk.get(tractce)
        if not ca:
            continue
        matched += 1
        _accumulate(by_ca.setdefault(ca, _new_sums()), row)

    _profiles = {
        ca: {"header": _header_metrics(s), "sections": _build_sections(s)}
        for ca, s in by_ca.items()
    }

    if place:
        city_sums = _new_sums()
        _accumulate(city_sums, place[0])
        _citywide = _header_metrics(city_sums)
        _citywide_sections = _build_sections(city_sums)

    print(f"ACS {_acs_year}: cached {len(_profiles)} community-area profiles "
          f"({matched} tracts matched to crosswalk, {len(_VARS)} variables)")


def acs_year() -> int:
    return _acs_year


def is_available() -> bool:
    return bool(_profiles)


# Header presentation metadata (KPI cards + citywide comparison bars).
_KPI_FIELDS = [
    ("population", "Population", "count"),
    ("median_rent", "Median rent", "currency"),
    ("median_age", "Median age", "decimal"),
    ("renter_pct", "Renter-occupied", "percent"),
]
_COMPARISON_FIELDS = [
    ("median_rent", "Median rent", "currency"),
    ("renter_pct", "Renter-occupied", "percent"),
    ("bachelors_pct", "Bachelor's +", "percent"),
    ("pct_65", "Residents 65+", "percent"),
]


def community_profile(number: int) -> dict:
    """Return the shaped community-profile payload (header KPIs + comparison + sections)."""
    name = (geography.community_area_name(number) or "").title()
    base = {"number": number, "name": name, "acs_year": _acs_year}

    profile = _profiles.get(number)
    if not profile:
        return {
            **base,
            "available": False,
            "kpis": [],
            "comparison": [],
            "sections": [],
            "message": "Census data unavailable — set CENSUS_API_KEY and restart the service",
        }

    metrics = profile["header"]
    kpis = [
        {"id": fid, "label": label, "format": fmt,
         "value": metrics.get(fid), "citywide": _citywide.get(fid)}
        for fid, label, fmt in _KPI_FIELDS
    ]
    comparison = [
        {"id": fid, "label": label, "format": fmt,
         "value": metrics.get(fid), "citywide": _citywide.get(fid)}
        for fid, label, fmt in _COMPARISON_FIELDS
    ]
    sections = copy.deepcopy(profile["sections"])
    try:
        hardship = health_atlas.hardship_group(number)
        if hardship:
            economics = next((sec for sec in sections if sec.get("id") == "economics"), None)
            if economics:
                economics.setdefault("groups", []).insert(0, hardship)
            else:
                sections.append({"id": "economics", "title": "Economics", "groups": [hardship]})
    except Exception as e:
        print(f"Health Atlas hardship index unavailable for community area {number}: {e}")

    try:
        econ_dev = economic_development.community_section(number)
        if econ_dev:
            insert_at = next((i + 1 for i, sec in enumerate(sections) if sec.get("id") == "economics"),
                             len(sections))
            sections.insert(insert_at, econ_dev)
    except Exception as e:
        print(f"Economic development profile unavailable for community area {number}: {e}")

    try:
        housing_health = health_atlas.housing_group(number)
        if housing_health:
            housing = next((sec for sec in sections if sec.get("id") == "housing"), None)
            if housing:
                housing.setdefault("groups", []).append(housing_health)
            else:
                sections.append({"id": "housing", "title": "Housing", "groups": [housing_health]})

        health_sections = health_atlas.community_sections(number)
        if health_sections:
            insert_at = next((i + 1 for i, sec in enumerate(sections)
                              if sec.get("id") == "economic_development"),
                             next((i + 1 for i, sec in enumerate(sections)
                                   if sec.get("id") == "economics"),
                                  len(sections)))
            for section in reversed(health_sections):
                sections.insert(insert_at, section)
    except Exception as e:
        print(f"Health Atlas profile additions unavailable for community area {number}: {e}")

    return {**base, "available": True, "kpis": kpis, "comparison": comparison,
            "sections": sections}


def citywide_profile() -> dict:
    """Return the shaped citywide profile payload (Chicago as a whole)."""
    base = {"number": None, "name": "Chicago", "acs_year": _acs_year}

    if not _citywide:
        return {
            **base,
            "available": False,
            "kpis": [],
            "comparison": [],
            "sections": [],
            "message": "Census data unavailable — set CENSUS_API_KEY and restart the service",
        }

    kpis = [
        {"id": fid, "label": label, "format": fmt,
         "value": _citywide.get(fid), "citywide": _citywide.get(fid)}
        for fid, label, fmt in _KPI_FIELDS
    ]
    comparison = [
        {"id": fid, "label": label, "format": fmt,
         "value": _citywide.get(fid), "citywide": _citywide.get(fid)}
        for fid, label, fmt in _COMPARISON_FIELDS
    ]
    sections = copy.deepcopy(_citywide_sections)

    return {**base, "available": True, "kpis": kpis, "comparison": comparison,
            "sections": sections}
