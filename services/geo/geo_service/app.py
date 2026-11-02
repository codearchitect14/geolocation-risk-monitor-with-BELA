"""HTTP wrapper around the geo library: gazetteer search and article location.

Run: uvicorn geo_service.app:app --port 8083   (needs the NEL service and, optionally, the language model).
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from meridian.config import get_settings
from meridian.geo.search import search_places
from meridian.linking import calibration
from meridian.linking.config import load_config
from meridian.linking.context import CountryIndex
from meridian.linking.locate import connect_for_service, locate, place_json, result_json
from meridian.linking.nel_client import NelClient
from meridian.linking.pipeline import LinkingPipeline, Stages
from meridian.linking.reranker import Reranker
from meridian.llm.client import LlmClient

RERANKER = get_settings().data_dir / "processed" / "eval" / "reranker_geo_config_v1.joblib"
CALIBRATION = (
    Path(__file__).resolve().parents[3] / "apps" / "api" / "meridian" / "config" / "calibration_geo_config_v1.json"
)


class LocateRequest(BaseModel):
    title: str = Field(default="", max_length=500)
    text: str = Field(max_length=50_000)
    lang: str | None = None
    outlet_country: str | None = Field(default=None, pattern="^[A-Z]{2}$")
    use_llm: bool = True


class State:
    nel: NelClient
    llm: LlmClient
    reranker: Reranker
    calibrators: dict[str, calibration.Calibrator]


state = State()


@asynccontextmanager
async def lifespan(_: FastAPI) -> Any:
    state.nel, state.llm = NelClient(), LlmClient()
    state.reranker = Reranker.load(RERANKER)
    state.calibrators = calibration.load(CALIBRATION)
    yield


app = FastAPI(title="Meridian geo service", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "config": load_config().version,
        "reranker": state.reranker.version,
        "nel": state.nel.healthy(),
        "llm": state.llm.healthy(),
        "calibrated_routes": sorted(state.calibrators),
    }


@app.get("/v1/gazetteer/search")
def search(
    q: str = Query(min_length=1, max_length=200),
    country: str | None = Query(default=None, pattern="^[A-Z]{2}$"),
    k: int = Query(default=5, ge=1, le=25),
) -> dict[str, Any]:
    conn = connect_for_service()
    try:
        hits = search_places(conn, q, k=k, country_code=country)
    finally:
        conn.close()
    return {
        "query": q,
        "results": [
            {
                "place_id": h.place_id,
                "name": h.name,
                "type": h.type,
                "country_code": h.country_code,
                "admin1": h.admin1_name,
                "population": h.population,
                "lat": h.lat,
                "lon": h.lon,
                "uncertainty_km": h.uncertainty_km,
                "score": round(h.score, 4),
            }
            for h in hits
        ],
    }


@app.post("/v1/locate")
def locate_article(request: LocateRequest) -> dict[str, Any]:
    if not state.nel.healthy():
        raise HTTPException(503, "entity linking service is not available")
    conn = connect_for_service()
    try:
        llm = state.llm if request.use_llm and state.llm.healthy() else None
        pipeline = LinkingPipeline(conn, state.nel, load_config(), state.reranker, llm, CountryIndex.load(conn))
        started = time.perf_counter()
        result = locate(
            pipeline,
            request.text,
            title=request.title,
            lang=request.lang,
            outlet_country=request.outlet_country,
            stages=Stages(llm=llm is not None),
        )
        payload = result_json(result, state.calibrators)
        payload["seconds"] = round(time.perf_counter() - started, 3)
        return payload
    finally:
        conn.close()


_ = place_json
