![OpenGrid](img/branding/OpenGrid_Logo_Horizontal_3Color.png)

OpenGrid is an open-source, interactive map platform for exploring Chicago open data. It supports natural language queries powered by AI, proximity-based spatial filtering, neighborhood boundary visualization, and plain-language summarization of results.

This fork is self-hosted and pulls live data from the [Chicago Data Portal](https://data.cityofchicago.org) (Socrata) via a custom Python service layer.

## Features

- **AI-powered natural language search** — Type queries like "crimes in Logan Square last month" or "rodent complaints near schools" and the app translates them into structured Socrata SoQL queries using Claude.
- **Geolocation-aware proximity search** — Queries like "food inspections around me" or "crimes near me" request the browser's GPS and filter results within a configurable radius.
- **Neighborhood boundary display** — Searching for a community area (e.g., "Logan Square") or a data query scoped to one draws the boundary outline on the map.
- **Multi-dataset queries** — Ask for two datasets at once ("show me crimes and 311 requests in Pilsen") and both layers render together.
- **Plain-language summary** — A "Summarize" button sends the current results to Claude and displays a one-sentence summary with key highlights.
- **Advanced search panel** — Traditional filter-based data exploration (still available via "Find Data").

## Architecture

```
Browser  ──►  dist/          (static frontend, Leaflet + jQuery)
                │
                ▼
         opengrid-service/   (Python / FastAPI)
                │
                ├──► Anthropic API  (Claude Haiku — query translation & summarization)
                └──► Chicago Data Portal  (Socrata REST API)
```

The frontend is a static site served from `dist/`. The service layer (`opengrid-service/`) implements the OpenGrid REST API contract and is the only component that talks to external APIs.

## System Requirements

### Frontend
- Any modern web server (nginx, Apache, Python `http.server`, etc.)
- Node.js + npm (for rebuilding the JS/CSS bundles — optional if using pre-built `dist/`)

### Service Layer
- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)
- Optional: a [Socrata App Token](https://dev.socrata.com/foundry/data.cityofchicago.org/) to avoid throttling

### Browser Support
Chrome, Firefox, Safari, Edge. Also tested on iOS Safari and Android Chrome.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/tomschenkjr/opengrid.git
cd opengrid
```

### 2. Set up the service layer

```bash
cd opengrid-service
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in `opengrid-service/`:

```env
ANTHROPIC_API_KEY=sk-ant-...
SOCRATA_APP_TOKEN=your_socrata_token   # optional but recommended
CORS_ORIGINS=*                         # restrict in production
PORT=8080
```

Start the service:

```bash
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

The service is available at `http://localhost:8080`. Health check: `GET /health`.

### 3. Configure the frontend endpoint

Edit `config/EnvSettings.js` to point at your service:

```js
ogrid.Config.service.endpoint = 'http://localhost:8080/opengrid-service/rest';
```

### 4. Serve the frontend

Serve the `dist/` directory from any static web server:

```bash
# Quick local test
python -m http.server 8000 --directory dist
```

Open `http://localhost:8000` in your browser.

### 5. (Optional) Rebuild the dist bundle

> **Note:** The build pipeline uses Gulp 3, which is incompatible with Node.js v12+. If you need to rebuild after editing source files, use the `uglifyjs` and CSS concatenation approach described in the project wiki, or downgrade to Node.js v10.

## Available Datasets

| Dataset | Socrata ID | Description |
|---|---|---|
| Crimes | `ijzp-q8t2` | Chicago Police Department incident reports |
| Food Inspections | `4ijn-s7e5` | CDPH restaurant and food establishment inspections |
| Building Permits | `ydr8-5enu` | City-issued building permits |
| 311 Service Requests | `v6vf-nfxy` | All 311 service requests (graffiti, potholes, rodents, etc.) |

Proximity-only datasets (used as spatial anchors, not shown as primary layers):

| Dataset | Socrata ID | Used for |
|---|---|---|
| CPS Schools | `kh4r-387c` | "near schools" queries |

## Natural Language Search Examples

The search bar accepts plain English. Examples:

- `crimes in Logan Square last month`
- `rodent complaints near me`
- `failed food inspections in the Loop`
- `building permits near Wicker Park this year`
- `crimes and 311 requests in Pilsen`
- `West Town` *(draws the neighborhood boundary)*
- `graffiti removal requests in Ward 35 near a Starbucks`

After results appear, click **Summarize** for a one-sentence AI-generated overview.

## Service Layer API

The service implements the OpenGrid REST contract at `/opengrid-service/rest`. Key endpoints:

| Method | Path | Description |
|---|---|---|
| `POST` | `/search/smart` | Natural language → GeoJSON results |
| `POST` | `/search/summarize` | Generate plain-language summary of results |
| `GET` | `/datasets` | List available datasets |
| `GET` | `/capabilities` | Service capabilities |

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key for Claude |
| `SOCRATA_APP_TOKEN` | No | — | Socrata app token (avoids throttling) |
| `CORS_ORIGINS` | No | `*` | Comma-separated allowed origins |
| `PORT` | No | `8080` | Port the service listens on |

## Submit a Bug

Use the [issue tracker](../../issues/) to report bugs. Please include:

- Description of the bug
- Steps to reproduce
- Expected vs. actual behavior
- Screenshots if applicable
- Browser and OS

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
