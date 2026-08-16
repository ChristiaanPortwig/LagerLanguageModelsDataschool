# Share of Wallet

FastAPI, scheduled collection/processing, and a React dashboard for corporate-client wallet opportunities.

## Run the backend with Docker

Place the three bank ledgers and persisted pipeline data under `data/`:

- `transactional_banking.csv`
- `cross_border_payments.csv`
- `trade_finance.csv`
- `client_data.json`
- `json/current_external_data.json`
- `json/current_sens_data.json`
- `downloads/` (created automatically)

Set `GEMINI_API_KEY` in your shell or a root `.env`, then run:

```bash
docker compose up --build
```

In another terminal, start the frontend development server:

```bash
cd frontend
npm ci
npm run dev
```

- Dashboard: `http://localhost:5173`
- API/OpenAPI: `http://localhost:4000/docs`
- Health: `http://localhost:4000/health`

The mounted `data/` directory is the persistent source of truth. SENS collection runs hourly and full investor-document collection runs daily. Override with `SENS_INTERVAL_SECONDS`, `FULL_INTERVAL_SECONDS`, or disable scheduling with `PIPELINE_SCHEDULER_ENABLED=false`.

## Frontend API contract

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/dashboard` | Complete frontend payload: clients, portfolio totals and sorted opportunity flags |
| GET | `/api/clients` | Dashboard-ready client records |
| GET | `/api/clients/{id}` | One company with scores, confidence and audit data |
| GET | `/api/clients/{id}/calculation` | Wallet formulas, score components and low-confidence reasons |
| POST | `/api/clients/{id}/briefing` | Generate a banker briefing |
| POST | `/api/assistant` | Ask a portfolio/client question |
| GET | `/api/missing-data` | Missing PDFs, wallet fields and SENS scores |
| POST | `/api/clients/{id}/documents?document_type=...&year=...` | Upload and process a PDF (`multipart/form-data`, field `file`) |
| PATCH | `/api/clients/{id}/missing-data` | Supply missing standardized financial values |
| PATCH | `/api/opportunities/{record_id}` | Supply missing 0–1 SENS pillar scores |
| GET | `/api/formulas` | Global scoring formulas and all wallet calculations |
| PUT | `/api/settings/scoring` | Change scoring weights (must sum to 1) and/or SENS half-life |
| POST | `/api/pipeline/run` | Trigger `{"scope":"sens"}` or `{"scope":"all"}` |
| GET | `/api/pipeline/status` | Poll scheduled/manual pipeline state |

Financial update body:

```json
{"values":{"fx_derivative_notional":1250000000}}
```

Opportunity update body:

```json
{"global_markets_opportunity_score":0.8}
```

The API atomically regenerates `data/client_data.json` after processed documents, financial corrections, opportunity-score corrections, or scoring-weight changes. Existing dashboard field names remain available alongside the richer audit schema.

Opportunity flags are calculated by the backend during every regeneration:

- Refinancing is flagged when disclosed debt enters a 180-day maturity window or an upcoming SENS refinancing completion falls inside that window.
- Import/trade finance is flagged when captured import trade finance covers less than 10% of disclosed imports or observed outbound cross-border payment activity.

Each client record includes the supporting dates, amounts, coverage and human-readable reason used by the frontend.

## Local development

```bash
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python -m unittest discover -s backend/tests -v
.venv/bin/uvicorn backend.app:app --reload --port 4000
```

```bash
cd frontend
npm ci
npm run dev
```

Set `VITE_API_BASE_URL` when the API is not at `http://localhost:4000/api`.
