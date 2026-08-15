# LagerLanguageModelsDataschool
Repository for Data School Hackathon for team Lager Language Models

## Project Setup
Download the provided csv files and add it to the data directory

The financial-report collector uses Crawl4AI as its browser-rendered fallback,
and the data processor uses pypdf to merge SENS announcements. Install the
dependencies and initialise Crawl4AI before running collection or processing:

```bash
.venv/bin/pip install -U crawl4ai pypdf yfinance
.venv/bin/crawl4ai-setup
```

Run the complete processing pipeline from the repository root:

```python
from backend.scripts.data_processing import Data_Processor

processor = Data_Processor()
external_df, sens_df = processor.process_data()
```

To scrape only new documents, retain incremental JSON state, and calculate
wallet sizes in one run:

```bash
.venv/bin/python -m backend.scripts.wallet_size_pipeline --scrape all
```

Use `--scrape sens` to check only JSE SENS announcements. State and outputs are
written to `data/json/` (`current_external_data.json`,
`current_sens_data.json`, `processed_documents.json`, and
`wallet_sizes.json`). The Python API is `run_wallet_size_pipeline(...)`; it
returns `(external_df, sens_df, wallet_size_df)` and accepts existing frames as
`current_sens_data` and `current_external_data`.

For an auditable wallet estimate, request the calculation details directly:

```python
wallet_size_df, calculation_json = calculate_total_wallet_size(
    company_df,
    corporate_events_df,
    return_calculation_details=True,
)
```

`calculation_json["formulas"]` records each selected product formula, its tier,
inputs, and the pillar/total rollups. `calculation_json["missing_rows"]`
contains JSON-safe company-row templates with improvable fields set to `null`;
populate those fields and merge the rows back into `company_df` for a more
accurate recalculation.

`process_data` extracts base-unit values from PDFs, validates available company
values with yfinance, and converts dated monetary values to ZAR. It now reads
and updates the checkpoints and document fingerprints in `data/json/`, so only
unprocessed documents are extracted. `DataCollector.collect_data(...)` is
scrape-only; incremental selection and dataframe merging belong to
`Data_Processor.process_new_data(...)`. The wallet pipeline calls
`prepare_incremental_data(...)` before scraping so caller-supplied current data
is safely recorded as already processed.

Gemini is instructed to return numeric values in scientific notation and to
expand source scales such as thousands/millions/billions during extraction.
Standardized rows retain the source ISO currency in
`original_currency` alongside `fx_rate_to_zar` and `fx_rate_date`. To
standardize existing frames without extracting PDFs, use
`processor.standardize_data(external_df, sens_df)`. Pass
`fx_as_of_date="YYYY-MM-DD"` when undated foreign-currency rows need a fixed FX
date.

## Citations
- OpenAI ChatGPT 5.6 for data collection
    - Assiting with the writing of data-collection.py. Especially web crawling.
    - Assisting with generating contant values, especially INVESTOR_URL. This provides us with
    optimal accuracy for web scraping, rather than trying to manually scrape these.

- OpenAI ChatGPT 5.6 for data processing:
    - Assists in researching fields to extract.
    - Writing JSON schemas in gemini_structured_schemas.py from a pre-defined attribute list.
