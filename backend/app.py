"""
FastAPI backend for the banking share-of-wallet dashboard.

Reads data/mock_clients.json once on server startup into memory and serves it over a REST API:

  GET  /api/clients               -> full array of client records
  GET  /api/clients/{id}          -> single client record by entity_id (e.g. "E01")
  POST /api/clients/{id}/briefing -> generate a briefing note for one client

CORS is enabled so a React frontend running on a different port
(e.g. http://localhost:3000 or :5173) can call this API directly.

Run with: uvicorn app:app --reload --port 4000
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from scripts.gemini_client import Gemini_Client
from prompts_briefing import build_briefing_prompt, SYSTEM_INSTRUCTION

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "client_data.json"

# Global variable to hold clients in memory while the server is running
_CLIENTS_CACHE = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once when the FastAPI server starts up. 
    Loads the client data into memory so requests don't hit the disk.
    """
    global _CLIENTS_CACHE
    try:
        print("Loading client data into memory...")
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            _CLIENTS_CACHE = json.load(f)
        print(f"Successfully loaded {len(_CLIENTS_CACHE)} clients into memory.")
    except Exception as err:
        print(f"CRITICAL: Failed to load client data on startup: {err}")
        _CLIENTS_CACHE = []
        
    yield
    
    # Optional: Clean up memory on shutdown if needed
    _CLIENTS_CACHE.clear()
    print("Server shutting down, memory cache cleared.")

# Pass the lifespan handler to FastAPI
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Match the Node/Express error shape: { "error": "..." } instead of
    # FastAPI's default { "detail": "..." }.
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.get("/api/clients")
def get_clients():
    """Serves the client list directly from server RAM."""
    if not _CLIENTS_CACHE:
        raise HTTPException(status_code=500, detail="Client data cache is empty")
    try:
        return _CLIENTS_CACHE
    except Exception as err:
        print(f"Failed to read client data: {err}")
        raise HTTPException(status_code=500, detail="Failed to load client data")


@app.get("/api/clients/{client_id}")
def get_client(client_id: str):
    """Searches the in-memory cache for a specific client."""
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

    return client


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
    output = client.call_gemini_ustructured(prompt=prompt, system_instruction=SYSTEM_INSTRUCTION)
    print(f"Gemini request made\nOutput:\n{output}")
    return {"report": output}

# TODO: hard regen of client.json by calling data_agg