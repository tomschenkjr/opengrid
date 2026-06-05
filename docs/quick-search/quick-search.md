# Smart Search

The search bar at the top of OpenGrid accepts plain-English questions. An AI model (Claude Haiku) reads your query, identifies the relevant dataset and filters, generates a structured database query, and returns results as map points — all in a few seconds.

You do not need to know field names, operators, or dataset IDs. Write what you want to find the way you would say it out loud.

---

## Query Types

### 1. Basic Data Query

Ask for records from a dataset, optionally with filters.

| Example query | What it returns |
|---|---|
| `crimes last month` | All crime incidents in the previous calendar month |
| `recent food inspections` | Food inspection records from the last 30 days |
| `building permits this year` | Permits issued since January 1 |
| `failed food inspections` | Inspections where result = Fail |
| `theft crimes` | Crimes where primary type = THEFT |
| `open 311 service requests` | 311 requests with status = Open |
| `graffiti removal requests` | 311 requests where request type contains "Graffiti" |
| `rodent complaints` | 311 requests where request type contains "Rodent" |

**Time expressions** the AI understands:

| Phrase | Interpreted as |
|---|---|
| `last month` | Previous calendar month |
| `this year` | January 1 of the current year to today |
| `last week` | Last 7 days |
| `last 30 days` | Last 30 days |
| `yesterday`, `today` | That calendar day |
| Specific dates, e.g. `since March 1` | From that date forward |

---

### 2. Geographic Query

Add a neighborhood, community area, ward, or ZIP code to scope results geographically. The matching boundary is drawn on the map as a blue outline.

| Example query | What it returns |
|---|---|
| `crimes in Logan Square` | Crimes filtered to Logan Square community area + boundary drawn |
| `food inspections in the Loop` | Food inspections in community area 32 + boundary drawn |
| `311 requests in Wicker Park` | 311 requests in West Town (Wicker Park is a neighborhood alias) |
| `building permits in Ward 35` | Permits in ward 35 + boundary drawn |
| `failed food inspections in ZIP 60647` | Inspections filtered to ZIP code 60647 |
| `crimes in Pilsen last month` | Crimes in Lower West Side (Pilsen alias) in the past month |

All 77 Chicago community areas are supported by name. Common neighborhood aliases are also understood:

| What you type | Resolves to |
|---|---|
| Wicker Park | West Town |
| Pilsen | Lower West Side |
| Andersonville | Edgewater |
| Boystown / Northalsted | Lake View |
| River North, Gold Coast, Streeterville | Near North Side |
| Bucktown | Logan Square |
| Chinatown | Armour Square |
| Bronzeville | Douglas |
| Little Village | South Lawndale |
| South Loop | Near South Side |
| The Loop / Downtown | Loop |
| Wrigleyville | Lake View |

---

### 3. Neighborhood Boundary Lookup

Type just a neighborhood or ward name with no dataset intent and the map draws the boundary and zooms to it.

| Example | What happens |
|---|---|
| `Logan Square` | Logan Square boundary drawn, map zoomed to it |
| `West Loop` | Near West Side boundary drawn |
| `Ward 35` | Ward 35 boundary drawn |
| `Edgewater` | Edgewater boundary drawn |

This is useful for orienting yourself on the map before running a data query.

---

### 4. Proximity Query

Filter results to records that fall within a given distance of a reference location. Write "near", "within X of", "close to", or "around" in your query.

#### Near a dataset or amenity

| Example query | What it returns |
|---|---|
| `crimes near schools` | Crimes within ~300 ft of CPS school locations |
| `311 requests near parks` | 311 service requests near park locations |
| `food inspections near hospitals` | Inspections near hospital locations |
| `crimes within half a mile of train stations` | Crimes within 800 m of CTA rail stations |
| `rodent complaints near restaurants` | 311 rodent requests near OSM restaurant locations |

**Supported reference types:**

*Chicago datasets:* crimes, food inspections, building permits, 311 service requests, CPS schools

*OpenStreetMap amenities:* libraries, parks, gas stations, coffee shops, cafes, hospitals, pharmacies, grocery stores, bars, restaurants, fast food, transit stops, bus stops, train stations

#### Near an address

| Example query | What it returns |
|---|---|
| `crimes near 333 S State St` | Crimes within ~400 m of that address |
| `food inspections near 2135 W Division` | Inspections near that intersection |

#### Near a named landmark or business

| Example query | What it returns |
|---|---|
| `crimes near the United Center` | Crimes within ~400 m of the United Center |
| `311 requests near Millennium Park` | 311 requests near Millennium Park |
| `food inspections near Starbucks` | Inspections near Starbucks locations |

#### Distance expressions

| Phrase | Approximate distance |
|---|---|
| `nearby` / `near` / `close to` / `around` | 400 m (~¼ mile, default) |
| `within 1 block` | ~100 m |
| `within a quarter mile` | ~400 m |
| `within half a mile` | ~800 m |
| `within 1 mile` | ~1,600 m |
| `within 500 feet` | ~150 m |

---

### 5. Geolocation Query ("Near Me")

Phrases that reference your own position trigger a browser geolocation prompt. Once you allow access, results are filtered to within approximately 400 meters of your current location.

**Trigger phrases** (any of these work):

- near me · around me · nearby · close to me · by me
- in my neighborhood · in my area · in my vicinity
- at my house · at my home · where I live · near where I live
- around here · near here · in this area
- my block · my street · locally · in my part of town
- current location · my location

| Example query | What it returns |
|---|---|
| `crimes around me` | Crimes within 400 m of your GPS position |
| `rodent complaints near me` | 311 rodent requests near your location |
| `food inspections in my neighborhood` | Food inspections near your current position |
| `building permits around here this year` | Permits near you issued this year |

> **Privacy:** Your coordinates are sent to the OpenGrid service to run the spatial query. They are not stored or logged.

---

### 6. Multi-Dataset Query

Ask for two datasets at once and both render as separate layers on the map.

| Example query | What it returns |
|---|---|
| `show me crimes and 311 requests in Logan Square` | Two layers: crimes + 311 service requests, both filtered to Logan Square |
| `crimes and food inspections in Wicker Park` | Crimes + food inspections in West Town |
| `building permits and rodent complaints near me` | Both datasets filtered to your current location |

Each dataset uses its own color. If a neighborhood is specified, a single boundary outline is shared across both layers.

---

### 7. Place and Address Lookup

If the search bar doesn't identify a dataset intent, it falls back to geocoding the query as a place or address using ArcGIS.

| Example | What happens |
|---|---|
| `Daley Center` | Places a marker at Daley Center |
| `Wrigley Field` | Places a marker at Wrigley Field |
| `50 W Washington` | Places a marker at that address |
| `41.8827, -87.6233` | Places a marker at those coordinates |

This is the same behavior as the original quick search for addresses, lat/long, and place names.

---

## Combining Query Types

You can combine geographic scope, dataset filters, time, and proximity in a single query:

| Example | Components |
|---|---|
| `theft crimes in Logan Square last month` | dataset + crime type + neighborhood + time |
| `failed food inspections near me this year` | dataset + result filter + geolocation + time |
| `open graffiti requests in Ward 35` | dataset + request type + status + ward |
| `crimes within half a mile of schools in Englewood` | dataset + proximity + neighborhood |

---

## AI Summarization

After any search returns results, a **Summarize** button appears next to the search bar. Clicking it sends the current results to an AI model and displays a summary panel at the top of the map.

The summary includes:
- Total record count
- The neighborhood or area referenced in the query
- Notable patterns visible in the data (top request types, geographic concentration, open/closed ratio, common streets or intersections)

Key phrases in the summary are **highlighted in yellow** for quick scanning.

### Using the summary panel

- The panel appears above the map and below the navigation bar.
- Click **×** in the upper-right corner of the panel to dismiss it.
- Running a new search hides the current summary. Click **Summarize** again after new results load to generate a new one.
- The summary reflects the results as loaded — if you pan the map or filter differently, regenerate it.

---

## Tips

- **Be specific about time** — "this year" returns more focused results than an unscoped query, which may default to the last 90 days for large datasets.
- **Use neighborhood aliases** — "Wicker Park", "Bucktown", and "Pilsen" all resolve correctly; you don't need to know the official community area name.
- **Combine filters** — "failed food inspections in Logan Square last month" works in one query.
- **Proximity defaults to 400 m** — Say "within a quarter mile" or "within 500 feet" if you want a specific radius.
- **If no results appear** — The dataset may have no matching records for your filter combination. Try broadening the time range or removing one filter.
- **If results look citywide** — The query may have been interpreted without geographic context. Add a neighborhood name or "near me" to scope it.
