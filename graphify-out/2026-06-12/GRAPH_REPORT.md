# Graph Report - .  (2026-06-11)

## Corpus Check
- 111 files · ~509,749 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 752 nodes · 1182 edges · 113 communities (109 shown, 4 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 11 edges (avg confidence: 0.72)
- Token cost: 0 input · 57,657 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Chicago Geography Reference|Chicago Geography Reference]]
- [[_COMMUNITY_FastAPI Service Core|FastAPI Service Core]]
- [[_COMMUNITY_Proximity Location Fetchers|Proximity Location Fetchers]]
- [[_COMMUNITY_Civic Facilities Map Layer|Civic Facilities Map Layer]]
- [[_COMMUNITY_Census ACS Profiles|Census ACS Profiles]]
- [[_COMMUNITY_Open Air Quality Layer|Open Air Quality Layer]]
- [[_COMMUNITY_Dataset Registry & Querying|Dataset Registry & Querying]]
- [[_COMMUNITY_Scale-Aware Map Aggregation|Scale-Aware Map Aggregation]]
- [[_COMMUNITY_Config & Frontend Bootstrap|Config & Frontend Bootstrap]]
- [[_COMMUNITY_AI Search GeoJSON Builders|AI Search GeoJSON Builders]]
- [[_COMMUNITY_AI Search View Selection|AI Search View Selection]]
- [[_COMMUNITY_Transit Stations API|Transit Stations API]]
- [[_COMMUNITY_CTA Transit Layer|CTA Transit Layer]]
- [[_COMMUNITY_Park Map Layer|Park Map Layer]]
- [[_COMMUNITY_Health Atlas Metrics|Health Atlas Metrics]]
- [[_COMMUNITY_AI Search Helpers|AI Search Helpers]]
- [[_COMMUNITY_MCP HTTP Provider|MCP HTTP Provider]]
- [[_COMMUNITY_Library Events|Library Events]]
- [[_COMMUNITY_Metra Transit Layer|Metra Transit Layer]]
- [[_COMMUNITY_Announcements Page|Announcements Page]]
- [[_COMMUNITY_Profile Charts|Profile Charts]]
- [[_COMMUNITY_Community Profile API|Community Profile API]]
- [[_COMMUNITY_BeachStation Endpoints|Beach/Station Endpoints]]
- [[_COMMUNITY_Civic Facilities API|Civic Facilities API]]
- [[_COMMUNITY_Open Air Sensor API|Open Air Sensor API]]
- [[_COMMUNITY_AI Search Prompt Building|AI Search Prompt Building]]
- [[_COMMUNITY_GeoJSON Converter|GeoJSON Converter]]
- [[_COMMUNITY_Beach Weather Stations|Beach Weather Stations]]
- [[_COMMUNITY_School Map Layer|School Map Layer]]
- [[_COMMUNITY_Street View|Street View]]
- [[_COMMUNITY_NWS Zone Resolver|NWS Zone Resolver]]
- [[_COMMUNITY_Bus Transit Layer|Bus Transit Layer]]
- [[_COMMUNITY_Module 32|Module 32]]
- [[_COMMUNITY_Module 33|Module 33]]
- [[_COMMUNITY_Module 34|Module 34]]
- [[_COMMUNITY_Module 35|Module 35]]
- [[_COMMUNITY_Module 36|Module 36]]
- [[_COMMUNITY_Module 37|Module 37]]
- [[_COMMUNITY_Module 38|Module 38]]
- [[_COMMUNITY_Module 39|Module 39]]
- [[_COMMUNITY_Module 40|Module 40]]
- [[_COMMUNITY_Module 41|Module 41]]
- [[_COMMUNITY_Module 42|Module 42]]
- [[_COMMUNITY_Module 43|Module 43]]
- [[_COMMUNITY_Module 44|Module 44]]
- [[_COMMUNITY_Module 45|Module 45]]
- [[_COMMUNITY_Module 47|Module 47]]
- [[_COMMUNITY_Module 83|Module 83]]
- [[_COMMUNITY_Module 92|Module 92]]

## God Nodes (most connected - your core abstractions)
1. `fetch_reference_locations()` - 15 edges
2. `FastAPI` - 13 edges
3. `_process_single_result()` - 13 edges
4. `_filtered_one()` - 12 edges
5. `decide_view()` - 11 edges
6. `_socrata_headers()` - 10 edges
7. `_popupHtml()` - 9 edges
8. `query_dataset()` - 9 edges
9. `_clean_marine_text()` - 8 edges
10. `_format_marine_conditions()` - 8 edges

## Surprising Connections (you probably didn't know these)
- `Dataset Chiclets UI` --shares_data_with--> `OpenGrid Dataset Registry`  [INFERRED]
  src/index.html → opengrid-service/config/datasets.yaml
- `Quick Search Help Content` --references--> `OpenGrid Dataset Registry`  [EXTRACTED]
  src/templates/qsearch-help.html → opengrid-service/config/datasets.yaml
- `Quick Search Input UI` --shares_data_with--> `Quick Search Trigger Configuration`  [INFERRED]
  src/index.html → opengrid-service/config/datasets.yaml
- `Plain-Language Summarize UI` --shares_data_with--> `Anthropic SDK Dependency`  [INFERRED]
  src/index.html → opengrid-service/requirements.txt
- `Proximity Aliases Configuration` --semantically_similar_to--> `Chicago Marine Knowledge MCP Provider`  [INFERRED] [semantically similar]
  opengrid-service/config/datasets.yaml → opengrid-service/config/providers.yaml

## Import Cycles
- 1-file cycle: `opengrid-service/main.py -> opengrid-service/main.py`
- 1-file cycle: `opengrid-service/routers/stations.py -> opengrid-service/routers/stations.py`
- 3-file cycle: `opengrid-service/main.py -> opengrid-service/services/ai_search.py -> opengrid-service/routers/stations.py -> opengrid-service/main.py`

## Hyperedges (group relationships)
- **Natural-Language Quick Search Pipeline** — index_index_qsearch_input, config_datasets_quicksearch_config, config_datasets_proximity_config, requirements_requirements_anthropic_sdk [INFERRED 0.75]
- **MCP HTTP Provider Integration** — config_providers_noaa_weather, config_providers_chicago_marine_knowledge, config_providers_mcp_http_protocol, requirements_requirements_mcp_client [INFERRED 0.85]

## Communities (113 total, 4 thin omitted)

### Community 0 - "Chicago Geography Reference"
Cohesion: 0.05
Nodes (42): community_areas(), /geography/* — Chicago geographic reference data for the frontend., Return all 77 Chicago community areas as {number, name}, sorted by name.     Use, all_community_area_geojson(), all_tract_geojson(), _bbox_from_wkt(), community_area_list_for_prompt(), community_area_name() (+34 more)

### Community 1 - "FastAPI Service Core"
Cohesion: 0.07
Nodes (24): FastAPI, lifespan(), OpenGrid Service Layer Implements the OpenGrid REST API contract backed by data., Request, get_token(), _make_token(), Stub authentication endpoints for OpenGrid autologin mode. Issues signed JWTs wi, renew_token() (+16 more)

### Community 2 - "Proximity Location Fetchers"
Cohesion: 0.09
Nodes (33): _fetch_bus_stop_locations(), _fetch_cta_station_locations(), _fetch_dataset_locations(), _fetch_divvy_station_locations(), _fetch_facility_locations(), _fetch_metra_station_locations(), _fetch_open_air_sensor_locations(), _fetch_osm_amenity() (+25 more)

### Community 3 - "Civic Facilities Map Layer"
Cohesion: 0.19
Nodes (24): _buildMarker(), _canvasId(), _destroyCharts(), _detailCard(), _details(), _esc(), _fmtDateTime(), _fmtNumber() (+16 more)

### Community 4 - "Census ACS Profiles"
Cohesion: 0.12
Nodes (21): AsyncClient, _accumulate(), _build_sections(), community_profile(), _fetch_many(), _geo_key(), _header_metrics(), initialize() (+13 more)

### Community 5 - "Open Air Quality Layer"
Cohesion: 0.22
Nodes (21): _aqiIndexColor(), _buildMarker(), _canvasId(), _detailHtml(), _esc(), _fetchDetail(), _fmt(), _groupCard() (+13 more)

### Community 6 - "Dataset Registry & Querying"
Cohesion: 0.16
Nodes (19): _find_dataset(), get_dataset(), list_datasets(), _load_datasets(), query_dataset_endpoint(), /datasets endpoints — OpenGrid dataset listing and querying backed by Socrata., _field_clause(), geo_filter_to_soql() (+11 more)

### Community 7 - "Scale-Aware Map Aggregation"
Cohesion: 0.16
Nodes (18): BaseModel, aggregate_endpoint(), AggregateRequest, Bbox, /map/* — scale-aware map representations (server-side aggregation)., Community-area choropleth counts for a dataset + filter context., Viewport-aware representation: points / choropleth / heatmap by count + zoom., view_endpoint() (+10 more)

### Community 8 - "Config & Frontend Bootstrap"
Cohesion: 0.12
Nodes (20): OpenGrid Dataset Registry, Geographic Columns Mapping, Proximity Aliases Configuration, Quick Search Trigger Configuration, Dataset Rendition (Map Styling) Options, Socrata Open Data Source (data.cityofchicago.org), Chicago Marine Knowledge MCP Provider, mcp_http Provider Type (+12 more)

### Community 9 - "AI Search GeoJSON Builders"
Cohesion: 0.13
Nodes (20): _build_boundary_layer(), _build_filters_meta(), _build_geo_clause(), _build_reference_layer(), _community_area_name(), _dispatch_result(), _filtered_one(), filtered_search() (+12 more)

### Community 10 - "AI Search View Selection"
Cohesion: 0.15
Nodes (19): _ca_features(), decide_view(), heat_points(), _normalize_rows_for_dataset(), _points_fc(), Standard point GeoJSON for the current viewport (for points mode)., Lightweight [lat, lon] list for a heatmap layer., Paged record list for the results pane (query-wide, not viewport-scoped).     Re (+11 more)

### Community 11 - "Transit Stations API"
Cohesion: 0.16
Nodes (17): _bbox_center(), bus_arrivals(), cta_arrivals(), divvy_stations(), _fetch_divvy_feed_urls(), _fetch_divvy_station_information(), _fetch_divvy_station_status(), _fetch_divvy_stations() (+9 more)

### Community 12 - "CTA Transit Layer"
Cohesion: 0.24
Nodes (17): _arrivalCard(), _arrivalsHtml(), _buildMarker(), _clearHighlight(), _esc(), _fetchArrivals(), _highlightLines(), _iconForZoom() (+9 more)

### Community 13 - "Park Map Layer"
Cohesion: 0.24
Nodes (15): _card(), _clearSelection(), _details(), _ensurePane(), _esc(), _highlightStyle(), init(), _injectStyles() (+7 more)

### Community 14 - "Health Atlas Metrics"
Cohesion: 0.25
Nodes (16): Client, _area_key(), _clean_name(), _community_name(), community_sections(), _fetch_metric(), hardship_group(), housing_group() (+8 more)

### Community 15 - "AI Search Helpers"
Cohesion: 0.21
Nodes (16): _alias_in_query(), _bbox_filter(), _deg_to_cardinal(), _detail_text(), _fmt_temp(), _fmt_wind_kt(), _format_marine_conditions(), _marine_is_recent() (+8 more)

### Community 16 - "MCP HTTP Provider"
Cohesion: 0.17
Nodes (11): McpHttpProvider, Any, _call_via_mcp_client(), McpHttpProvider, MCP HTTP provider — uses the official `mcp` Python client library (SSE transport, all_providers(), describe_all(), get() (+3 more)

### Community 17 - "Library Events"
Cohesion: 0.26
Nodes (15): all_events(), _build_where(), _event_page_url(), events(), events_by_library(), _fetch_rows(), _headers(), _lat_lon() (+7 more)

### Community 18 - "Metra Transit Layer"
Cohesion: 0.26
Nodes (15): _buildMarker(), _clearLineHighlight(), _departureCard(), _departuresHtml(), _esc(), _fetchDepartures(), _highlightRoute(), _iconForZoom() (+7 more)

### Community 19 - "Announcements Page"
Cohesion: 0.26
Nodes (11): _card(), _chip(), _detailChip(), _detailRow(), _esc(), _eventHref(), _externalLink(), _fmtDate() (+3 more)

### Community 20 - "Profile Charts"
Cohesion: 0.30
Nodes (9): bars(), color(), _drawBarLabels(), formatValue(), line(), pctOf(), pie(), shortNum() (+1 more)

### Community 21 - "Community Profile API"
Cohesion: 0.24
Nodes (11): community_area_boundaries(), community_area_profile(), community_area_profile_summary(), _fact_from_item(), _fallback_summary(), _profile_facts(), /geography/community-areas/* — Community Trends profile data.    - GET .../{numb, GeoJSON FeatureCollection of all community-area boundaries with name + number. (+3 more)

### Community 22 - "Beach/Station Endpoints"
Cohesion: 0.17
Nodes (12): _bbox_intersects(), beach_dna(), beach_weather(), cta_trains(), _fetch_parks(), parks(), Chicago Park District park boundary polygons. Cached 24h., Chicago Park District park boundary polygons intersecting a bounding box. (+4 more)

### Community 23 - "Civic Facilities API"
Cohesion: 0.24
Nodes (12): facilities(), _facility_details(), _facility_from_row(), _facility_value(), _fetch_facilities(), _fetch_library_metric(), _fetch_library_metrics(), _library_key() (+4 more)

### Community 24 - "Open Air Sensor API"
Cohesion: 0.17
Nodes (12): _fetch_open_air_detail(), _fetch_open_air_latest(), _open_air_coords(), _open_air_float(), _open_air_group_payload(), _open_air_row(), open_air_sensor(), open_air_sensors() (+4 more)

### Community 25 - "AI Search Prompt Building"
Cohesion: 0.17
Nodes (12): _build_provider_section(), _build_system_prompt(), _date_context(), _find_dataset(), geocode_poi(), _load_datasets(), nl_to_soql(), Translate natural language → SOQL or MCP call → GeoJSON(s), or fall back to POI (+4 more)

### Community 26 - "GeoJSON Converter"
Cohesion: 0.23
Nodes (11): _build_view(), _detect_geo_fields(), dynamic_rows_to_geojson(), _extract_lat_lon(), Converts Socrata JSON row arrays into OpenGrid-compatible GeoJSON FeatureCollect, Build a GeoJSON FeatureCollection for AI search results where the dataset     ma, Detect latitude and longitude field names from column metadata or row sampling., Convert a single Socrata row to a GeoJSON Feature.     row: filtered properties (+3 more)

### Community 27 - "Beach Weather Stations"
Cohesion: 0.41
Nodes (11): _add(), _esc(), _historyHtml(), init(), _label(), _popupHtml(), _row(), _toF() (+3 more)

### Community 28 - "School Map Layer"
Cohesion: 0.38
Nodes (11): _buildMarker(), _detailCard(), _esc(), _fmt(), init(), _injectStyles(), _loadForBounds(), _pct() (+3 more)

### Community 29 - "Street View"
Cohesion: 0.36
Nodes (9): attachToMarker(), _cfg(), _esc(), imageHtml(), _key(), _latLon(), _num(), popupHtml() (+1 more)

### Community 30 - "NWS Zone Resolver"
Cohesion: 0.25
Nodes (10): get_combined_zone_geojson(), get_zone_geojson(), _polygons_of(), Fetch and cache NWS/marine zone GeoJSON boundaries from api.weather.gov.  Zone I, Return a GeoJSON geometry dict for a zone, or None on failure.     Result is cac, Return the list of polygon coordinate arrays in a Polygon/MultiPolygon., Fetch several zones and merge them into a single MultiPolygon geometry     (no d, Pre-fetch a list of zone boundaries at startup. (+2 more)

### Community 31 - "Bus Transit Layer"
Cohesion: 0.35
Nodes (10): _arrivalCard(), _arrivalsHtml(), _buildMarker(), _esc(), _fetchArrivals(), init(), _injectStyles(), _loadForBounds() (+2 more)

### Community 32 - "Module 32"
Cohesion: 0.40
Nodes (10): _availabilityPill(), _buildMarker(), _detailCard(), _esc(), _fmtNum(), init(), _loadForBounds(), _showStation() (+2 more)

### Community 33 - "Module 33"
Cohesion: 0.20
Nodes (10): bus_stops(), cta_lines(), _fetch_bus_stops(), _fetch_cta_lines_geojson(), _fetch_gtfs_zip(), Parse bus stops from CTA GTFS stops.txt. Cached 24h., Bus stops within a bounding box, parsed from CTA GTFS., Download and cache the CTA GTFS zip (shared by rail lines and bus stops). (+2 more)

### Community 34 - "Module 34"
Cohesion: 0.20
Nodes (10): _fetch_metra_zip(), _metra_active_services(), metra_departures(), metra_lines(), metra_stations(), _parse_metra_data(), Parse all needed Metra data from GTFS in one pass. Cached 24h., Metra station list from GTFS stops.txt. (+2 more)

### Community 35 - "Module 35"
Cohesion: 0.22
Nodes (9): aggregate_search(), _choropleth_fc(), _dataset_is_spatial(), _empty_choropleth(), Build a SOQL date clause for a timeframe key, or None for 'all'/no date field., Combined WHERE for a viewport query: data predicate + timeframe + area + bbox., Community-area choropleth (kept for /map/aggregate; also used by decide_view)., _timeframe_clause() (+1 more)

### Community 36 - "Module 36"
Cohesion: 0.44
Nodes (8): _area_key(), community_section(), _empty_area(), _load_cache(), _num(), Community-area economic development indicators from Chicago Socrata datasets.  F, _series(), _year()

### Community 37 - "Module 37"
Cohesion: 0.29
Nodes (8): datetime, _c_to_f(), _deg_to_cardinal(), dever_crib_conditions(), _doy_to_date(), _fetch_glerl(), _parse_last_observation(), Real-time conditions from the William E. Dever Water Crib (GLERL station 4).

### Community 38 - "Module 38"
Cohesion: 0.43
Nodes (8): Any, _clean_marine_text(), _first_marine_value(), _format_marine_alert(), _format_marine_timestamp(), _marine_alert_details(), _marine_source_notes(), _marine_summary_context()

### Community 39 - "Module 39"
Cohesion: 0.25
Nodes (8): _extract_mcp_text(), _marine_alert_display_from_payload(), _marine_alert_event(), _normalize_provider_id(), _process_mcp_result(), Process a Haiku MCP result → GeoJSON FeatureCollection with NWS zone polygon., Style the combined Chicago lake-zone polygon from Chicago Marine Knowledge     a, Flatten MCP tool result content into a plain text string.

### Community 40 - "Module 40"
Cohesion: 0.29
Nodes (7): _fetch_schools(), CPS school progress report locations and key metrics. Cached 24h., CPS schools within a bounding box from School Progress Reports., _school_category_label(), _school_from_row(), _school_metric(), schools()

### Community 41 - "Module 41"
Cohesion: 0.52
Nodes (6): _addBeach(), _esc(), _fmtTime(), init(), _popupHtml(), _updateVisibility()

### Community 42 - "Module 42"
Cohesion: 0.33
Nodes (3): Any, Protocol, DataProvider

### Community 43 - "Module 43"
Cohesion: 0.70
Nodes (4): _initCam(), _popupHtml(), _renderMedia(), _renderSource()

### Community 44 - "Module 44"
Cohesion: 0.50
Nodes (4): _fetch_crime_types(), initialize(), Fetch distinct primary_type values from Crimes at startup., Called at service startup: fetch dynamic values and warm the prompt.

## Knowledge Gaps
- **17 isolated node(s):** `name`, `icons`, `Any`, `Any`, `Socrata` (+12 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `datetime` connect `Module 37` to `FastAPI Service Core`, `Proximity Location Fetchers`, `Module 36`, `Dataset Registry & Querying`, `Transit Stations API`, `Health Atlas Metrics`, `AI Search Helpers`, `Library Events`?**
  _High betweenness centrality (0.139) - this node is a cross-community bridge._
- **Why does `FastAPI` connect `FastAPI Service Core` to `Chicago Geography Reference`, `Dataset Registry & Querying`, `Scale-Aware Map Aggregation`, `Transit Stations API`, `Community Profile API`?**
  _High betweenness centrality (0.112) - this node is a cross-community bridge._
- **Why does `decide_view()` connect `AI Search View Selection` to `AI Search Prompt Building`, `Module 35`, `AI Search Helpers`, `Scale-Aware Map Aggregation`?**
  _High betweenness centrality (0.003) - this node is a cross-community bridge._
- **What connects `name`, `icons`, `OpenGrid Service Layer Implements the OpenGrid REST API contract backed by data.` to the rest of the system?**
  _155 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Chicago Geography Reference` be split into smaller, more focused modules?**
  _Cohesion score 0.052854122621564484 - nodes in this community are weakly interconnected._
- **Should `FastAPI Service Core` be split into smaller, more focused modules?**
  _Cohesion score 0.0746031746031746 - nodes in this community are weakly interconnected._
- **Should `Proximity Location Fetchers` be split into smaller, more focused modules?**
  _Cohesion score 0.09090909090909091 - nodes in this community are weakly interconnected._