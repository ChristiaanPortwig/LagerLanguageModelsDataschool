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

## Callable class methods

Internal methods beginning with `_` are omitted.

### `DataCollector`

| Method | Purpose |
|--------|---------|
| `collect_data(scrape_scope="all", save_location=None)` | Recommended entry point. Scrapes all sources or SENS only and saves PDFs. |
| `scrape_and_save_reports(save_location=...)` | Scrapes company reports and SENS, returning missing or questionable document records. |
| `get_sens_data(company_name=None, base_dir=...)` | Incrementally downloads SENS announcements for one company or all configured companies. |

### `Data_Processor`

All dataframe-returning methods use `(external_df, sens_df)` order.

| Method | Purpose |
|--------|---------|
| `prepare_incremental_data(...)` | Loads or creates dataframe checkpoints and initializes document state before scraping. |
| `process_new_data(..., process_scope="all")` | Processes untracked PDFs, refreshes changed companies, appends new SENS events, and updates `data/json`. |
| `process_data(...)` | Runs incremental processing, yfinance filling, ZAR standardization, and checkpoint saving. It does not scrape. |
| `save_current_data(external_data, sens_data, ...)` | Writes the current processed dataframes to the JSON directory. |
| `extract_external_data_from_pdfs(source_dir=...)` | Low-level extraction that processes every PDF supplied; it bypasses incremental selection. |
| `validate_external_data(external_df, sens_df)` | Fills missing values and replaces mismatches using yfinance. |
| `standardize_data(external_df, sens_df, fx_as_of_date=None)` | Converts monetary values to base-unit ZAR and adds FX audit columns. |
| `standardize_external_data(...)` | Compatibility alias for `standardize_data`. |

### `Gemini_Client`

| Method | Purpose |
|--------|---------|
| `call_gemini_ustructured(prompt, model=...)` | Sends a text prompt and returns unstructured text. |
| `call_gemini_structured_json(schema_class, prompt, pdfs_dir, model=...)` | Sends a prompt with optional PDFs, validates the response against a schema, and returns JSON data. |
