from fastapi import APIRouter

from app.api.v1 import entities, overlays, geoops, map_state, nl, artifacts, ws, config, maps, history, routes, cop, custom_symbols, render, tiles, events, terrain, graph, geocode, products, wopi, world_sources, world_runs, world_repair, chat, supply

api_router = APIRouter()

api_router.include_router(graph.router, tags=["entity-graph"])
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(products.router, tags=["products"])
api_router.include_router(world_sources.router, prefix="/sources", tags=["world-sources"])
api_router.include_router(world_runs.router, prefix="/runs", tags=["world-runs"])
api_router.include_router(world_repair.router, tags=["world-repair"])
api_router.include_router(wopi.router, tags=["wopi"])

api_router.include_router(config.router, tags=["config"])
api_router.include_router(maps.router, prefix="/maps", tags=["maps"])
api_router.include_router(history.router, prefix="/maps", tags=["snapshots"])
api_router.include_router(entities.router, prefix="/entities", tags=["entities"])
api_router.include_router(overlays.router, prefix="/overlays", tags=["overlays"])
api_router.include_router(routes.router, prefix="/routes", tags=["routes"])
api_router.include_router(geoops.router, prefix="/geoops", tags=["geoops"])
api_router.include_router(map_state.router, prefix="/map", tags=["map"])
api_router.include_router(nl.router, prefix="/nl", tags=["natural-language"])
api_router.include_router(artifacts.router, prefix="/artifacts", tags=["artifacts"])
api_router.include_router(custom_symbols.router, prefix="/custom-symbols", tags=["custom-symbols"])
api_router.include_router(cop.router, prefix="/cop", tags=["cop"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(terrain.router, prefix="/terrain", tags=["terrain"])
api_router.include_router(geocode.router, tags=["geocode"])
api_router.include_router(supply.router, prefix="/supply", tags=["supply"])
api_router.include_router(ws.router, tags=["websocket"])
api_router.include_router(render.router, tags=["render"])
api_router.include_router(tiles.router, tags=["tiles"])
