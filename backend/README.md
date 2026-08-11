# Share-of-wallet backend

Small FastAPI API that serves the mock client data from `data/mock_clients.json`.

## Setup

```bash
cd backend
pip install -r requirements.txt
```

If `data/mock_clients.json` doesn't exist yet, generate it first:

```bash
python scripts/mock_data.py
```

## Run

```bash
uvicorn app:app --reload --port 4000
```

Server listens on `http://localhost:4000`. `--reload` restarts the server on file
changes (equivalent to the old `npm run dev`).

## Endpoints

| Method | Path                | Description                                      |
|--------|---------------------|---------------------------------------------------|
| GET    | `/api/clients`      | Returns the full array of 20 client records       |
| GET    | `/api/clients/{id}` | Returns one client by `entity_id` (e.g. `E01`), case-insensitive. 404 if not found |

CORS is enabled for all origins, so a React frontend on a different port
(e.g. `http://localhost:3000` or `:5173`) can call this API directly.
