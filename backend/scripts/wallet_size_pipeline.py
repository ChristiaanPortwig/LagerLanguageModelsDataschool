"""Incrementally collect data and estimate company wallet sizes."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

import pandas as pd

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scripts.data_collection import DataCollector
from backend.scripts.data_processing import Data_Processor
from backend.scripts.wallet_size import calculate_total_wallet_size


LOGGER = logging.getLogger(__name__)
DEFAULT_JSON_DIR = Data_Processor.DEFAULT_JSON_DIR
WALLET_SIZE_FILE = "wallet_sizes.json"


def run_wallet_size_pipeline(
    current_sens_data: pd.DataFrame | None = None,
    current_external_data: pd.DataFrame | None = None,
    *,
    scrape_scope: str = "all",
    downloads_dir=None,
    json_dir=None,
    fx_as_of_date=None,
    collector: DataCollector | None = None,
    processor: Data_Processor | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run collection, processing, filling, standardisation, and estimation.

    ``scrape_scope`` controls whether all sources (``"all"``) or only SENS
    announcements (``"sens"``) are scraped. Omitted current dataframes are
    restored from the processor's JSON checkpoints when available.

    Returns ``(external_df, sens_df, wallet_size_df)``. The two source frames
    are validated with yfinance and standardized to ZAR before wallet sizes are
    estimated.
    """
    if scrape_scope not in {"all", "sens"}:
        raise ValueError("scrape_scope must be either 'all' or 'sens'")

    collector = collector or DataCollector()
    processor = processor or Data_Processor()
    json_path = Path(json_dir or DEFAULT_JSON_DIR)

    external_df, sens_df = processor.prepare_incremental_data(
        current_sens_data=current_sens_data,
        current_external_data=current_external_data,
        source_dir=downloads_dir,
        json_location=json_path,
    )
    collector.collect_data(
        scrape_scope=scrape_scope,
        save_location=downloads_dir,
    )
    external_df, sens_df = processor.process_new_data(
        current_sens_data=sens_df,
        current_external_data=external_df,
        source_dir=downloads_dir,
        json_location=json_path,
        process_scope=scrape_scope,
    )
    filled_external, filled_sens = processor.validate_external_data(
        external_df, sens_df
    )
    standardized_external, standardized_sens = processor.standardize_data(
        filled_external,
        filled_sens,
        fx_as_of_date=fx_as_of_date,
    )
    wallet_sizes = calculate_total_wallet_size(
        standardized_external, standardized_sens
    )

    processor.save_current_data(
        standardized_external, standardized_sens, json_location=json_path
    )
    _write_wallet_sizes(wallet_sizes, json_path / WALLET_SIZE_FILE)
    return standardized_external, standardized_sens, wallet_sizes


def _write_wallet_sizes(wallet_sizes: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = json.loads(
        wallet_sizes.reset_index().to_json(
            orient="records", date_format="iso"
        )
    )
    path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Scrape new disclosures and estimate company wallet sizes."
    )
    parser.add_argument(
        "--scrape",
        choices=("all", "sens"),
        default="all",
        help="Scrape every source or only JSE SENS announcements (default: all).",
    )
    parser.add_argument(
        "--downloads-dir",
        type=Path,
        default=DataCollector.DEFAULT_DOWNLOAD_DIR,
        help="Directory containing company PDF downloads.",
    )
    parser.add_argument(
        "--json-dir",
        type=Path,
        default=DEFAULT_JSON_DIR,
        help="Directory for incremental state and result JSON files.",
    )
    parser.add_argument(
        "--fx-as-of-date",
        help="YYYY-MM-DD fallback FX date for rows without a disclosure date.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    external_df, sens_df, wallet_sizes = run_wallet_size_pipeline(
        scrape_scope=args.scrape,
        downloads_dir=args.downloads_dir,
        json_dir=args.json_dir,
        fx_as_of_date=args.fx_as_of_date,
    )
    LOGGER.info(
        "Pipeline complete: %d companies, %d SENS events, %d wallet estimates",
        len(external_df),
        len(sens_df),
        len(wallet_sizes),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
