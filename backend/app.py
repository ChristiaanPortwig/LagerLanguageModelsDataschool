"""FastAPI contract for the share-of-wallet dashboard and data pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from backend.prompts_briefing import (
    SYSTEM_INSTRUCTION,
    build_assistant_prompt,
    build_briefing_prompt,
)
from backend.scripts.gemini_client import Gemini_Client
from backend.scripts.pipeline_service import (
    DEFAULT_SCORE_WEIGHTS,
    PipelineBusyError,
    PipelineService,
)


LOGGER = logging.getLogger(__name__)
SERVICE = PipelineService()
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="data-pipeline")


class PipelineRequest(BaseModel):
    scope: Literal["sens", "all"] = "sens"


class ExternalFieldUpdate(BaseModel):
    values: dict[str, float | None] = Field(min_length=1)


class OpportunityScoreUpdate(BaseModel):
    transactional_banking_opportunity_score: float | None = Field(None, ge=0, le=1)
    global_markets_opportunity_score: float | None = Field(None, ge=0, le=1)
    investment_banking_opportunity_score: float | None = Field(None, ge=0, le=1)

    @model_validator(mode="after")
    def at_least_one_score(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("At least one opportunity score is required")
        return self


class ScoreWeightUpdate(BaseModel):
    gap_weight: float = Field(DEFAULT_SCORE_WEIGHTS["gap_weight"], ge=0)
    sens_weight: float = Field(DEFAULT_SCORE_WEIGHTS["sens_weight"], ge=0)
    relationship_weight: float = Field(
        DEFAULT_SCORE_WEIGHTS["relationship_weight"], ge=0
    )

    @model_validator(mode="after")
    def weights_sum_to_one(self):
        if abs(sum(self.model_dump().values()) - 1.0) > 1e-9:
            raise ValueError("Scoring weights must sum to 1")
        return self


class AssistantRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    focused_entity_id: str | None = None


async def _scheduled_loop(scope: Literal["sens", "all"], interval_seconds: int):
    while True:
        await asyncio.sleep(interval_seconds)
        if SERVICE.status()["running"]:
            LOGGER.info("Skipping scheduled %s run; another pipeline is active", scope)
            continue
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(_EXECUTOR, SERVICE.run, scope)
        except Exception:
            LOGGER.exception("Scheduled %s pipeline failed", scope)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    tasks = []
    if os.getenv("PIPELINE_SCHEDULER_ENABLED", "true").lower() in {"1", "true", "yes"}:
        sens_interval = int(os.getenv("SENS_INTERVAL_SECONDS", "3600"))
        full_interval = int(os.getenv("FULL_INTERVAL_SECONDS", "86400"))
        tasks = [
            asyncio.create_task(_scheduled_loop("sens", sens_interval)),
            asyncio.create_task(_scheduled_loop("all", full_interval)),
        ]
        LOGGER.info(
            "Pipeline scheduler enabled: SENS every %ss, full scrape every %ss",
            sens_interval,
            full_interval,
        )
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Share of Wallet API",
    version="1.0.0",
    lifespan=lifespan,
)

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


def _clients() -> list[dict]:
    try:
        clients = json.loads(SERVICE.client_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=503, detail=f"Client data is unavailable: {error}")
    if not isinstance(clients, list) or not clients:
        raise HTTPException(status_code=503, detail="Client data is empty")
    return clients


def _client(client_id: str) -> dict:
    target = client_id.casefold()
    client = next(
        (
            item for item in _clients()
            if str(item.get("entity_id", "")).casefold() == target
        ),
        None,
    )
    if client is None:
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found")
    return client


def _company_folder(client: dict) -> Path:
    folder_name = re.sub(r"[^A-Za-z0-9]+", "_", client["entity_name"]).strip("_")
    return SERVICE.downloads_dir / folder_name


def _run_pipeline(scope: str, scrape: bool = True):
    try:
        SERVICE.run(scope, scrape=scrape)
    except PipelineBusyError:
        LOGGER.info("Pipeline trigger ignored because a run is already active")
    except Exception:
        LOGGER.exception("Background pipeline failed")


@app.get("/health")
def health():
    return {
        "status": "ok" if SERVICE.client_path.exists() else "degraded",
        "client_data_available": SERVICE.client_path.exists(),
        "pipeline": SERVICE.status(),
    }


@app.get("/api/clients")
def get_clients():
    return _clients()


@app.get("/api/clients/{client_id}")
def get_client(client_id: str):
    return _client(client_id)


@app.get("/api/clients/{client_id}/calculation")
def get_client_calculation(client_id: str):
    client = _client(client_id)
    return {
        "entity_id": client["entity_id"],
        "entity_name": client["entity_name"],
        "confidence": client.get("confidence", {}),
        "wallet_calculation": client.get("wallet_calculation", {}),
        "score_calculation": client.get("score_calculation", {}),
        "missing_data": client.get("missing_data", {}),
    }


@app.post("/api/clients/{client_id}/briefing")
def create_client_briefing(client_id: str):
    if not _CLIENTS_CACHE:
        raise HTTPException(status_code=500, detail="Client data cache is empty")

    try:
        clients = _CLIENTS_CACHE
    except Exception as err:
        print(f"Failed to read client data: {err}")
        raise HTTPException(status_code=500, detail="Failed to load client data")

    target = client_id.upper()
    client = next((c for c in clients if c["entity_id"].upper() == target), None)

    if client is None:
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found")

    # Sends the built prompt to Gemini and returns its generated response.
    prompt = build_briefing_prompt(client)

    client = Gemini_Client()
    output = client.call_gemini_ustructured(prompt=prompt)
    print(f"Gemini request made\nOutput:\n{output}")
    return {"report": output}


@app.post("/api/assistant")
def ask_assistant(payload: AssistantRequest):
    prompt = SYSTEM_INSTRUCTION + "\n\n" + build_assistant_prompt(
        payload.question,
        _clients(),
        payload.focused_entity_id,
    )
    try:
        output = Gemini_Client().call_gemini_ustructured(prompt=prompt)
    except Exception as error:
        LOGGER.exception("Assistant request failed")
        raise HTTPException(status_code=502, detail=f"Assistant request failed: {error}")
    return {"answer": output}


@app.get("/api/pipeline/status")
def pipeline_status():
    return SERVICE.status()


@app.post("/api/pipeline/run", status_code=202)
def run_pipeline(payload: PipelineRequest, background_tasks: BackgroundTasks):
    if SERVICE.status()["running"]:
        raise HTTPException(status_code=409, detail="A pipeline update is already running")
    background_tasks.add_task(_run_pipeline, payload.scope, True)
    return {"accepted": True, "scope": payload.scope, "status_url": "/api/pipeline/status"}


@app.get("/api/missing-data")
def get_missing_data():
    return SERVICE.missing_data()


@app.patch("/api/clients/{client_id}/missing-data")
def update_missing_data(client_id: str, payload: ExternalFieldUpdate):
    client = _client(client_id)
    try:
        records = SERVICE.update_external_fields(client["entity_name"], payload.values)
    except PipelineBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except KeyError:
        raise HTTPException(status_code=404, detail="Processed company row not found")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return next(row for row in records if row["entity_id"] == client["entity_id"])


@app.patch("/api/opportunities/{record_id}")
def update_opportunity_score(record_id: str, payload: OpportunityScoreUpdate):
    try:
        records = SERVICE.update_opportunity_scores(
            record_id,
            payload.model_dump(exclude_none=True),
        )
    except PipelineBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except KeyError:
        raise HTTPException(status_code=404, detail="Opportunity record not found")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"updated": True, "client_count": len(records)}


@app.post("/api/clients/{client_id}/documents", status_code=202)
async def upload_client_document(
    client_id: str,
    background_tasks: BackgroundTasks,
    document_type: Literal[
        "annual_report", "financial_statements", "interim_results", "results_presentation", "SENS"
    ],
    year: int,
    file: UploadFile = File(...),
):
    client = _client(client_id)
    if SERVICE.status()["running"]:
        raise HTTPException(status_code=409, detail="A pipeline update is already running")
    if not 2000 <= year <= 2100:
        raise HTTPException(status_code=422, detail="year must be between 2000 and 2100")
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Only PDF files are accepted")
    maximum = int(os.getenv("MAX_UPLOAD_BYTES", str(200 * 1024 * 1024)))
    body = await file.read(maximum + 1)
    if len(body) > maximum:
        raise HTTPException(status_code=413, detail="PDF exceeds MAX_UPLOAD_BYTES")
    if not body.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="Uploaded content is not a PDF")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file.filename or "upload.pdf")
    folder = _company_folder(client)
    if document_type == "SENS":
        folder = folder / "SENS" / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{document_type}__{year}__{safe_name}"
    target.write_bytes(body)
    background_tasks.add_task(
        _run_pipeline,
        "sens" if document_type == "SENS" else "all",
        False,
    )
    return {
        "accepted": True,
        "document": target.relative_to(SERVICE.downloads_dir).as_posix(),
        "status_url": "/api/pipeline/status",
    }


@app.get("/api/formulas")
def get_formulas():
    return SERVICE.formulas()


@app.put("/api/settings/scoring")
def update_scoring_settings(payload: ScoreWeightUpdate):
    try:
        records = SERVICE.update_score_weights(payload.model_dump())
    except PipelineBusyError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {
        "score_weights": SERVICE.score_weights(),
        "client_count": len(records),
    }
