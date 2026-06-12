"""
OpenGrid Service Layer
Implements the OpenGrid REST API contract backed by data.cityofchicago.org (Socrata).
"""

import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from routers import auth, datasets, queries, capabilities, search, summarize, stations, events as events_router, geography as geography_router, map as map_router, community_profile as community_profile_router
from services.ai_search import initialize as ai_initialize
from services import geography, provider_registry, zone_resolver, census_acs


@asynccontextmanager
async def lifespan(app: FastAPI):
    await geography.initialize()      # fetch community area + ward boundary polygons
    await census_acs.initialize()      # fetch + aggregate ACS profiles per community area
    await ai_initialize()              # fetch crime types, warm schema prompt
    provider_registry.load()           # register MCP providers from config/providers.yaml
    warm = []
    for p in provider_registry.all_providers():
        geo = p._config.get("geometry", {})
        if geo.get("default_zone"):
            warm.append(geo["default_zone"])
        warm.extend(geo.get("zones", []))   # combined marine shoreline zones
    await zone_resolver.warm_zones(list(dict.fromkeys(warm)))  # pre-fetch NWS zone boundaries
    yield


app = FastAPI(title="OpenGrid Service Layer", version="1.0.0", lifespan=lifespan)

# CORS — the frontend is a static file and may be served from a different origin
cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-AUTH-TOKEN"],
)

# OpenGrid expects all routes under /opengrid-service/rest
PREFIX = "/opengrid-service/rest"

app.include_router(auth.router, prefix=PREFIX)
app.include_router(datasets.router, prefix=PREFIX)
app.include_router(queries.router, prefix=PREFIX)
app.include_router(capabilities.router, prefix=PREFIX)
app.include_router(search.router, prefix=PREFIX)
app.include_router(summarize.router, prefix=PREFIX)
app.include_router(stations.router, prefix=PREFIX)
app.include_router(events_router.router, prefix=PREFIX)
app.include_router(geography_router.router, prefix=PREFIX)
app.include_router(community_profile_router.router, prefix=PREFIX)
app.include_router(map_router.router, prefix=PREFIX)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "opengrid-service"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
