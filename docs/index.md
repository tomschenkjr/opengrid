[![OpenGrid logo](./media/OpenGrid_Logo_Horizontal_3Color.png)](https://chicago.opengrid.io/opengrid)

Welcome to OpenGrid, an open-source interactive map for exploring Chicago city data. OpenGrid provides real-time and historical insights into event-based data — crimes, food inspections, building permits, 311 service requests, and more — using natural language search powered by AI.

## Key Capabilities

### AI-Powered Natural Language Search
Type a plain-English question into the search bar and OpenGrid translates it into a structured data query automatically. You do not need to know field names or query syntax. Examples:

- *"crimes in Logan Square last month"*
- *"rodent complaints near me"*
- *"failed food inspections in the Loop"*
- *"show me crimes and 311 requests in Pilsen"*

### Neighborhood Boundary Visualization
When a query references a Chicago community area or ward — either as a data filter or as a standalone lookup — the neighborhood boundary is drawn on the map. Typing just *"Logan Square"* or *"Ward 35"* shows the boundary with the map auto-fitted to it.

### Proximity Search
Queries can reference locations: *"crimes near schools"*, *"food inspections near me"*, *"graffiti around Starbucks"*. Location-based queries automatically request your browser's GPS when you say "near me" or similar phrases.

### Plain-Language Summary
After results load, click the **Summarize** button to get a one-sentence AI-generated overview of what the data shows — count, geographic concentration, notable patterns.

### Advanced Search Panel
For users who prefer structured filtering, the **Find Data** panel provides traditional query-builder controls with AND/OR operators, date range pickers, and geo-spatial location filtering.

### Real-time and Historical Analysis
OpenGrid supports auto-refreshing searches for live monitoring, and historical queries spanning the full depth of each dataset.

## Technical Architecture

OpenGrid consists of two components:

1. **Frontend** (`dist/`) — A static web application built on Leaflet.js and jQuery. Runs entirely in the browser.
2. **Service Layer** (`opengrid-service/`) — A Python/FastAPI backend that translates natural language queries into Socrata SoQL via Claude (Anthropic), queries the Chicago Data Portal, and returns GeoJSON to the frontend.

See the [README](../README.md) for installation and configuration instructions.

<iframe width="740" height="541" src="https://www.youtube.com/embed/pzhmbtf2Vp8" frameborder="0" allow="autoplay; encrypted-media" allowfullscreen></iframe>
