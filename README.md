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
| GET | `/api/payment-timing` | All client cash cycles, payment timing and Gemini engagement predictions |
| GET | `/api/clients/{id}/payment-timing` | Cash cycle, payment timing and engagement prediction for one client |
| GET | `/api/clients/{id}/report` | Check whether a current client report exists |
| POST | `/api/clients/{id}/report` | Generate and persist a client report |
| GET | `/api/clients/{id}/report/download` | Download the current report as print-ready HTML |
| GET | `/api/missing-data` | Missing PDFs, wallet fields and automatic SENS-processing status |
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

Every newly scraped SENS document is extracted and its opportunity scores are completed by Gemini in the same pipeline run. A run is marked failed if Gemini is unavailable or leaves any SENS row unscored; incomplete SENS scores are not exposed as manual frontend data-entry work.

The conversational AI assistant is not exposed. Gemini remains scoped to document/SENS processing, timing intelligence, and explicit client-report generation. Generated reports are stored under `data/reports/` and include a separate formula-methodology page. A source fingerprint invalidates and deletes an existing report whenever its client data, timing intelligence, formulas, or relationship-manager assignment changes.

For report generation, client and relationship-manager names and internal identifiers are replaced with opaque placeholders before the prompt is sent to Gemini. The returned narrative is re-identified locally before the report is persisted, so the provider never receives the replacement map.

Relationship ownership uses `data/json/relationship_managers.json` when present and otherwise falls back to the bundled `backend/config/relationship_managers.json`. The bundled entries are explicitly marked mock assignments and use `.invalid` email addresses; this JSON adapter can later be replaced by an internal relationship database.

Opportunity flags are calculated by the backend during every regeneration:

- Refinancing is flagged when disclosed debt enters a 180-day maturity window or an upcoming SENS refinancing completion falls inside that window.
- Import/trade finance is flagged when captured import trade finance covers less than 10% of disclosed imports or observed outbound cross-border payment activity.

Each client record includes the supporting dates, amounts, coverage and human-readable reason used by the frontend.

Cash-cycle intelligence is calculated from the three bank ledgers during backend aggregation. Gemini receives only the calculated timing evidence and returns a structured engagement date, priority, rationale and action. If Gemini is unavailable, the API labels and returns the notebook-derived rules fallback. Set `TIMING_TIMEZONE` (default `Africa/Johannesburg`) to control the business-date boundary; the scheduler refreshes recommendations immediately on startup when due and at midnight when a recommended contact date arrives.

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
