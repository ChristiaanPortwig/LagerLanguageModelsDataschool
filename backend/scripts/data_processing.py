import ast
import hashlib
import json
import logging
import math
import re
import shutil
import time
import unicodedata
import warnings
from numbers import Number
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import yfinance as yf
from pypdf import PdfWriter

from config.gemini_structured_schemas import (
    CompanyLevelExtDataCombinationResponse,
    CompanyLevelExtDataResponse,
    SENSOpportunityScoresResponse,
    SENSEventsResponse,
)
from config.prompts import (
    COMPANY_LEVEL_COMBINATION_PROMPT,
    COMPANY_LEVEL_PROMPT,
    SENS_OPPORTUNITY_SCORING_PROMPT,
    SENS_PROMPT,
)
from .gemini_client import Gemini_Client


LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


# Yahoo Finance uses the ``.JO`` suffix for Johannesburg Stock Exchange shares.
JSE_NAMES = {
    "OUTsurance Group": "OUT.JO",
    "Bid Corporation": "BID.JO",
    "Bid Corporation Limited": "BID.JO",
    "Bidcorp": "BID.JO",
    "Bidcorp Limited": "BID.JO",
    "MTN Group": "MTN.JO",
    "Mobile Telephone Networks Holdings Limited": "MTN.JO",
    "Aspen Pharmacare": "APN.JO",
    "Aspen Pharmacare Holdings Limited": "APN.JO",
    "NEPI Rockcastle": "NRP.JO",
    "Pepkor Holdings": "PPH.JO",
    "Naspers": "NPN.JO",
    "The Bidvest Group": "BVT.JO",
    "Bidvest Group": "BVT.JO",
    "Sanlam": "SLM.JO",
    "Sanlam Life Insurance Limited": "SLM.JO",
    "Gold Fields": "GFI.JO",
    "Clicks Group": "CLS.JO",
    "Anglo American": "AGL.JO",
    "Anglo American plc": "AGL.JO",
    "AngloGold Ashanti": "ANG.JO",
    "AngloGold Ashanti plc": "ANG.JO",
    "BHP Group": "BHG.JO",
    "BHP Group Limited": "BHG.JO",
    "Shoprite Holdings": "SHP.JO",
    "Valterra Platinum": "VAL.JO",
    "Vodacom Group": "VOD.JO",
    "Shaftesbury Capital plc": "SHC.JO",
    "Glencore": "GLN.JO",
    "Glencore plc": "GLN.JO",
    "Prosus": "PRX.JO",
}


# These are the stable issuer names used by data collection and in final data.
CANONICAL_JSE_NAMES = {
    "OUTsurance Group": "OUT.JO",
    "Bid Corporation": "BID.JO",
    "MTN Group": "MTN.JO",
    "Aspen Pharmacare": "APN.JO",
    "NEPI Rockcastle": "NRP.JO",
    "Pepkor Holdings": "PPH.JO",
    "Naspers": "NPN.JO",
    "The Bidvest Group": "BVT.JO",
    "Sanlam": "SLM.JO",
    "Gold Fields": "GFI.JO",
    "Clicks Group": "CLS.JO",
    "Anglo American": "AGL.JO",
    "AngloGold Ashanti": "ANG.JO",
    "BHP Group": "BHG.JO",
    "Shoprite Holdings": "SHP.JO",
    "Valterra Platinum": "VAL.JO",
    "Vodacom Group": "VOD.JO",
    "Shaftesbury Capital plc": "SHC.JO",
    "Glencore": "GLN.JO",
    "Prosus": "PRX.JO",
}


COUNTRY_CODE_ALIASES = {
    "angola": "AO",
    "anguilla": "AI",
    "argentina": "AR",
    "australia": "AU",
    "austria": "AT",
    "bahrain": "BH",
    "belgium": "BE",
    "benin": "BJ",
    "bermuda": "BM",
    "botswana": "BW",
    "brazil": "BR",
    "bulgaria": "BG",
    "cameroon": "CM",
    "canada": "CA",
    "chile": "CL",
    "china": "CN",
    "colombia": "CO",
    "congo brazzaville": "CG",
    "cote d ivoire": "CI",
    "cote divoire": "CI",
    "croatia": "HR",
    "czech republic": "CZ",
    "democratic republic of the congo": "CD",
    "drc": "CD",
    "egypt": "EG",
    "equatorial guinea": "GQ",
    "estonia": "EE",
    "eswatini": "SZ",
    "ethiopia": "ET",
    "finland": "FI",
    "france": "FR",
    "germany": "DE",
    "ghana": "GH",
    "guinea": "GN",
    "hong kong": "HK",
    "hungary": "HU",
    "india": "IN",
    "ireland": "IE",
    "israel": "IL",
    "italy": "IT",
    "japan": "JP",
    "jersey": "JE",
    "kazakhstan": "KZ",
    "kenya": "KE",
    "latvia": "LV",
    "lesotho": "LS",
    "liberia": "LR",
    "lithuania": "LT",
    "macau": "MO",
    "malawi": "MW",
    "malaysia": "MY",
    "mauritius": "MU",
    "mexico": "MX",
    "mozambique": "MZ",
    "namibia": "NA",
    "netherlands": "NL",
    "new caledonia": "NC",
    "new zealand": "NZ",
    "nigeria": "NG",
    "norway": "NO",
    "oman": "OM",
    "peru": "PE",
    "philippines": "PH",
    "poland": "PL",
    "portugal": "PT",
    "romania": "RO",
    "rwanda": "RW",
    "saudi arabia": "SA",
    "singapore": "SG",
    "slovakia": "SK",
    "south africa": "ZA",
    "south sudan": "SS",
    "spain": "ES",
    "sudan": "SD",
    "switzerland": "CH",
    "tanzania": "TZ",
    "the netherlands": "NL",
    "turkey": "TR",
    "turkiye": "TR",
    "uae": "AE",
    "uganda": "UG",
    "ukraine": "UA",
    "united arab emirates": "AE",
    "united kingdom": "GB",
    "united states": "US",
    "united states of america": "US",
    "uk": "GB",
    "uruguay": "UY",
    "usa": "US",
    "zambia": "ZM",
    "zimbabwe": "ZW",
}


CURRENCY_CODE_ALIASES = {
    "$": "USD",
    "a$": "AUD",
    "aud": "AUD",
    "australian dollar": "AUD",
    "c$": "CAD",
    "cad": "CAD",
    "canadian dollar": "CAD",
    "chf": "CHF",
    "cny": "CNY",
    "eur": "EUR",
    "euro": "EUR",
    "gbp": "GBP",
    "pound sterling": "GBP",
    "r": "ZAR",
    "rand": "ZAR",
    "south african rand": "ZAR",
    "sterling": "GBP",
    "us dollar": "USD",
    "us dollars": "USD",
    "usd": "USD",
    "zar": "ZAR",
    "zarc": "ZAR",
    "zac": "ZAR",
    "€": "EUR",
    "£": "GBP",
}


EXTERNAL_NUMERIC_FIELDS = {
    "revenue",
    "cost_of_sales",
    "inventory",
    "trade_receivables",
    "trade_payables",
    "cash_and_cash_equivalents",
    "operating_cash_flow",
    "total_debt",
    "short_term_debt",
    "long_term_debt",
    "debt_due_within_12_months",
    "debt_due_12_to_24_months",
    "undrawn_committed_facilities",
    "finance_costs",
    "capital_expenditure",
    "foreign_revenue",
    "foreign_currency_assets",
    "foreign_currency_liabilities",
    "fx_derivative_notional",
    "floating_rate_debt",
    "interest_rate_derivative_notional",
    "bank_loan_debt",
    "imports_value",
    "exports_value",
    "commodity_linked_revenue",
    "commodity_exposure_value",
    "commodity_derivative_notional",
    "project_or_contract_value",
    "external_debt_raised",
    "guarantees_outstanding",
    "letters_of_credit_disclosed",
    "contingent_liabilities",
    "employee_expenses",
    "employee_count",
    "dividends_paid",
    "tax_paid",
    "receivable_days",
    "payable_days",
    "inventory_days",
    "cash_conversion_cycle",
    "assets_under_management",
    "market_capitalisation",
    "share_price",
    "share_return",
    "enterprise_value",
}


EXTERNAL_MONETARY_FIELDS = EXTERNAL_NUMERIC_FIELDS - {
    "employee_count",
    "receivable_days",
    "payable_days",
    "inventory_days",
    "cash_conversion_cycle",
    "share_return",
}


# A per-report scale applies to financial tables, not quoted per-share prices.
EXTERNAL_SCALED_MONETARY_FIELDS = EXTERNAL_MONETARY_FIELDS - {"share_price"}


YFINANCE_NUMERIC_WARNING_REL_TOLERANCE = 0.05


# Yahoo reports JSE quote prices in cents (ZAc), while repaired price history
# and quote-derived valuation fields are expressed in rand. These fields must
# not be converted using an issuer's financial-statement currency.
YFINANCE_ZAR_QUOTE_FIELDS = {
    "market_capitalisation",
    "share_price",
    "enterprise_value",
}


YFINANCE_STATEMENT_FIELDS = {
    "revenue": (
        "income",
        ("Total Revenue", "Operating Revenue"),
        False,
    ),
    "cost_of_sales": (
        "income",
        (
            "Cost Of Revenue",
            "Reconciled Cost Of Revenue",
            "Cost Of Sales",
        ),
        True,
    ),
    "finance_costs": (
        "income",
        ("Interest Expense", "Interest Expense Non Operating"),
        True,
    ),
    "employee_expenses": (
        ("income", "cash_flow"),
        ("Salaries And Wages", "Payments On Behalf Of Employees"),
        True,
    ),
    "inventory": (
        "balance",
        ("Inventory",),
        False,
    ),
    "trade_receivables": (
        "balance",
        ("Accounts Receivable", "Receivables"),
        False,
    ),
    "trade_payables": (
        "balance",
        (
            "Payables",
            "Accounts Payable",
            "Payables And Accrued Expenses",
        ),
        False,
    ),
    "cash_and_cash_equivalents": (
        "balance",
        (
            "Cash Cash Equivalents And Short Term Investments",
            "Cash And Cash Equivalents",
            "Cash Cash Equivalents And Federal Funds Sold",
            "Cash Financial",
        ),
        False,
    ),
    "total_debt": ("balance", ("Total Debt",), False),
    "short_term_debt": (
        "balance",
        (
            "Current Debt",
            "Current Debt And Capital Lease Obligation",
            "Other Current Borrowings",
            "Current Notes Payable",
        ),
        False,
    ),
    "debt_due_within_12_months": (
        "balance",
        (
            "Current Debt",
            "Current Debt And Capital Lease Obligation",
            "Other Current Borrowings",
            "Current Notes Payable",
        ),
        False,
    ),
    "long_term_debt": (
        "balance",
        ("Long Term Debt", "Long Term Debt And Capital Lease Obligation"),
        False,
    ),
    "operating_cash_flow": (
        "cash_flow",
        (
            "Operating Cash Flow",
            "Cash Flow From Continuing Operating Activities",
            "Total Cash From Operating Activities",
        ),
        False,
    ),
    "capital_expenditure": (
        "cash_flow",
        ("Capital Expenditure", "Capital Expenditure Reported"),
        True,
    ),
    "foreign_revenue": ("cash_flow", ("Foreign Sales",), False),
    "dividends_paid": (
        "cash_flow",
        (
            "Cash Dividends Paid",
            "Common Stock Dividend Paid",
            "Dividend Paid CFO",
            "Dividends Paid Direct",
        ),
        True,
    ),
    "tax_paid": (
        "cash_flow",
        (
            "Income Tax Paid Supplemental Data",
            "Income Tax Paid Supplemental",
            "Income Tax Paid",
            "Taxes Refund Paid Direct",
        ),
        True,
    ),
}


YFINANCE_INFO_FIELDS = {
    # The statement value for these fields is preferred. These info entries are
    # useful fallbacks for issuers/periods whose Yahoo statements are sparse.
    "revenue": ("totalRevenue",),
    "cost_of_sales": ("costOfRevenue",),
    "cash_and_cash_equivalents": ("totalCash",),
    "operating_cash_flow": ("operatingCashflow",),
    "total_debt": ("totalDebt",),
    "market_capitalisation": ("marketCap",),
    "share_price": (
        "_zarSharePrice",
        "currentPrice",
        "regularMarketPrice",
    ),
    "share_return": ("52WeekChange",),
    "enterprise_value": ("enterpriseValue",),
    "employee_count": ("fullTimeEmployees",),
    "assets_under_management": ("assetsUnderManagement",),
    "ownership_major_shareholders": ("_majorShareholders",),
}


YFINANCE_DERIVED_WORKING_CAPITAL_FIELDS = {
    "receivable_days": ("trade_receivables", "revenue"),
    "payable_days": ("trade_payables", "cost_of_sales"),
    "inventory_days": ("inventory", "cost_of_sales"),
}


class Data_Processor:
    """
    Processes data
    """

    REQUEST_DELAY_SECONDS = 10
    RETRY_DELAY_SECONDS = 60
    MAX_ALLOWED_FAILURES = 2
    JSE_NAMES = JSE_NAMES
    DEFAULT_DOWNLOAD_DIR = (
        Path(__file__).resolve().parents[2] / "data" / "downloads"
    )
    DEFAULT_JSON_DIR = Path(__file__).resolve().parents[2] / "data" / "json"
    PROCESSED_DOCUMENTS_FILE = "processed_documents.json"
    EXTERNAL_DATA_FILE = "current_external_data.json"
    SENS_DATA_FILE = "current_sens_data.json"
    SENS_OPPORTUNITY_SCORE_COLUMNS = (
        "transactional_banking_opportunity_score",
        "global_markets_opportunity_score",
        "investment_banking_opportunity_score",
    )

    def __init__(self):
        self.gemini_client = Gemini_Client()
        self.last_extraction_status = {
            "external_documents": set(),
            "sens_documents": set(),
        }
        self.last_failed_scrapes: dict[str, list[str]] = {}

    def prepare_incremental_data(
        self,
        current_sens_data: pd.DataFrame | None = None,
        current_external_data: pd.DataFrame | None = None,
        *,
        source_dir=None,
        json_location=None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Load/checkpoint current frames and initialise processing state.

        Call this before scraping. If the processed-document manifest does not
        exist, PDFs already on disk are marked processed only for dataframe
        kinds explicitly supplied by the caller or restored from a checkpoint.
        With no current data, existing PDFs remain unprocessed for a first run.

        Returns ``(external_df, sens_df)``.
        """
        downloads_dir, json_dir = self._incremental_paths(
            source_dir, json_location
        )
        external_path = json_dir / self.EXTERNAL_DATA_FILE
        sens_path = json_dir / self.SENS_DATA_FILE
        has_current_external = (
            current_external_data is not None or external_path.exists()
        )
        has_current_sens = current_sens_data is not None or sens_path.exists()

        external_df = self._current_dataframe(
            current_external_data, external_path, "current_external_data"
        )
        sens_df = self._current_dataframe(
            current_sens_data, sens_path, "current_sens_data"
        )
        self.save_current_data(external_df, sens_df, json_location=json_dir)

        state_path = json_dir / self.PROCESSED_DOCUMENTS_FILE
        if not state_path.exists() and (has_current_external or has_current_sens):
            current_documents = self._document_fingerprints(downloads_dir)
            processed_documents = {
                relative_path: fingerprint
                for relative_path, fingerprint in current_documents.items()
                if (
                    fingerprint["kind"] == "external" and has_current_external
                )
                or (fingerprint["kind"] == "sens" and has_current_sens)
            }
            self._write_processed_documents(processed_documents, state_path)
        return external_df, sens_df

    def process_new_data(
        self,
        current_sens_data: pd.DataFrame | None = None,
        current_external_data: pd.DataFrame | None = None,
        *,
        source_dir=None,
        json_location=None,
        process_scope="all",
        return_failures: bool = False,
    ):
        """Extract only documents not recorded in the JSON manifest.

        A changed non-SENS report reprocesses all reports for that company and
        replaces its current company row. Only changed SENS PDFs are processed
        and appended. Processing state and updated raw frames are written to
        the JSON directory before this method returns. Set ``return_failures``
        to receive the failed-scrape keyword dictionary as a third value.
        """
        if process_scope not in {"all", "sens"}:
            raise ValueError("process_scope must be either 'all' or 'sens'")

        downloads_dir, json_dir = self._incremental_paths(
            source_dir, json_location
        )
        external_path = json_dir / self.EXTERNAL_DATA_FILE
        sens_path = json_dir / self.SENS_DATA_FILE
        current_external_data = self._current_dataframe(
            current_external_data, external_path, "current_external_data"
        )
        current_sens_data = self._current_dataframe(
            current_sens_data, sens_path, "current_sens_data"
        )

        state_path = json_dir / self.PROCESSED_DOCUMENTS_FILE
        processed_documents = self._load_processed_documents(state_path)
        available_documents = self._document_fingerprints(downloads_dir)
        changed_paths = {
            relative_path
            for relative_path, fingerprint in available_documents.items()
            if processed_documents.get(relative_path) != fingerprint
        }
        if process_scope == "sens":
            changed_paths = {
                path
                for path in changed_paths
                if self._document_kind(path) == "sens"
            }

        changed_sens = {
            path
            for path in changed_paths
            if self._document_kind(path) == "sens"
        }
        changed_external = changed_paths - changed_sens
        changed_companies = {
            Path(path).parts[0] for path in changed_external
        }
        updated_external = current_external_data.copy(deep=True)
        updated_sens = current_sens_data.copy(deep=True)
        processed_now = set()
        failed_scrapes: dict[str, set[str]] = {}

        if changed_companies:
            with TemporaryDirectory(prefix="external_updates_") as temp_dir:
                batch_dir = Path(temp_dir)
                company_documents = set()
                for relative_path in available_documents:
                    path = Path(relative_path)
                    if (
                        self._document_kind(relative_path) == "external"
                        and path.parts[0] in changed_companies
                    ):
                        company_documents.add(relative_path)
                        self._copy_for_processing(
                            downloads_dir / path, batch_dir / path
                        )
                extracted_external, _ = self.extract_external_data_from_pdfs(
                    batch_dir
                )
                self._merge_failed_scrapes(
                    failed_scrapes, self.last_failed_scrapes
                )
                successful_external_paths = self._successful_batch_paths(
                    "external_documents", batch_dir, company_documents
                )

            successful_companies = self._companies_in_dataframe(
                extracted_external
            )
            if successful_companies:
                updated_external = self._replace_company_rows(
                    updated_external,
                    extracted_external,
                    successful_companies,
                )
                processed_now.update(
                    relative_path
                    for relative_path in successful_external_paths
                    if self._canonical_company_name(
                        Path(relative_path).parts[0]
                    ) in successful_companies
                )
            else:
                LOGGER.warning(
                    "No company rows were extracted; changed report files "
                    "will be retried on the next run"
                )

        if changed_sens:
            with TemporaryDirectory(prefix="sens_updates_") as temp_dir:
                batch_dir = Path(temp_dir)
                for relative_path in changed_sens:
                    path = Path(relative_path)
                    self._copy_for_processing(
                        downloads_dir / path, batch_dir / path
                    )
                _, extracted_sens = self.extract_external_data_from_pdfs(
                    batch_dir
                )
                self._merge_failed_scrapes(
                    failed_scrapes, self.last_failed_scrapes
                )
                successful_sens_paths = self._successful_batch_paths(
                    "sens_documents", batch_dir, changed_sens
                )
            updated_sens = self._append_unique_rows(updated_sens, extracted_sens)
            # A SENS announcement can validly contain no wallet-relevant event.
            processed_now.update(successful_sens_paths)

        for relative_path in processed_now:
            processed_documents[relative_path] = available_documents[relative_path]
        self.save_current_data(
            updated_external, updated_sens, json_location=json_dir
        )
        self._write_processed_documents(processed_documents, state_path)
        self.last_failed_scrapes = {
            company: sorted(keywords)
            for company, keywords in sorted(failed_scrapes.items())
            if keywords
        }
        if return_failures:
            return updated_external, updated_sens, self.get_failed_scrape_keywords()
        return updated_external, updated_sens

    @staticmethod
    def _merge_failed_scrapes(target: dict[str, set[str]], additions) -> None:
        for company, keywords in additions.items():
            target.setdefault(company, set()).update(keywords)

    def get_failed_scrape_keywords(self) -> dict[str, list[str]]:
        """Return failed PDF extraction keywords grouped by company.

        Keys are canonical company names. Values are stable, human-readable
        document keywords such as ``"annual report"`` or ``"SENS"``. The
        returned dictionary is a copy and can be safely mutated by callers.
        """
        return {
            company: list(keywords)
            for company, keywords in self.last_failed_scrapes.items()
        }

    def save_current_data(
        self,
        external_data: pd.DataFrame,
        sens_data: pd.DataFrame,
        json_location=None,
    ) -> None:
        """Persist processed dataframes without changing document state."""
        if not isinstance(external_data, pd.DataFrame):
            raise TypeError("external_data must be a pandas DataFrame")
        if not isinstance(sens_data, pd.DataFrame):
            raise TypeError("sens_data must be a pandas DataFrame")
        json_dir = Path(json_location or self.DEFAULT_JSON_DIR)
        json_dir.mkdir(parents=True, exist_ok=True)
        self._write_dataframe(external_data, json_dir / self.EXTERNAL_DATA_FILE)
        self._write_dataframe(sens_data, json_dir / self.SENS_DATA_FILE)

    def _incremental_paths(self, source_dir, json_location):
        downloads_dir = Path(source_dir or self.DEFAULT_DOWNLOAD_DIR)
        json_dir = Path(json_location or self.DEFAULT_JSON_DIR)
        downloads_dir.mkdir(parents=True, exist_ok=True)
        json_dir.mkdir(parents=True, exist_ok=True)
        return downloads_dir, json_dir

    @staticmethod
    def _document_kind(relative_path: str) -> str:
        return (
            "sens"
            if "SENS" in Path(relative_path).parts[1:-1]
            else "external"
        )

    @classmethod
    def _document_fingerprints(cls, downloads_dir: Path) -> dict[str, dict]:
        fingerprints = {}
        if not downloads_dir.exists():
            return fingerprints
        for path in sorted(downloads_dir.rglob("*.pdf")):
            if not path.is_file():
                continue
            digest = hashlib.sha256()
            with path.open("rb") as pdf_file:
                for chunk in iter(lambda: pdf_file.read(1024 * 1024), b""):
                    digest.update(chunk)
            relative_path = path.relative_to(downloads_dir).as_posix()
            fingerprints[relative_path] = {
                "kind": cls._document_kind(relative_path),
                "sha256": digest.hexdigest(),
                "size": path.stat().st_size,
            }
        return fingerprints

    @staticmethod
    def _load_processed_documents(path: Path) -> dict[str, dict]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            LOGGER.warning("Could not read processing state %s: %s", path, error)
            return {}
        documents = (
            payload.get("documents", {}) if isinstance(payload, dict) else {}
        )
        return documents if isinstance(documents, dict) else {}

    @staticmethod
    def _write_processed_documents(documents: dict, path: Path) -> None:
        payload = {"version": 1, "documents": dict(sorted(documents.items()))}
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _read_dataframe(path: Path) -> pd.DataFrame:
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            LOGGER.warning("Could not read dataframe checkpoint %s: %s", path, error)
            return pd.DataFrame()
        if not isinstance(records, list):
            LOGGER.warning("Dataframe checkpoint %s is not a JSON list", path)
            return pd.DataFrame()
        return pd.DataFrame(records)

    @classmethod
    def _current_dataframe(cls, dataframe, path: Path, parameter: str):
        if dataframe is not None:
            if not isinstance(dataframe, pd.DataFrame):
                raise TypeError(f"{parameter} must be a pandas DataFrame")
            return dataframe.copy(deep=True)
        if path.exists():
            return cls._read_dataframe(path)
        return pd.DataFrame()

    @staticmethod
    def _write_dataframe(dataframe: pd.DataFrame, path: Path) -> None:
        records = json.loads(
            dataframe.to_json(orient="records", date_format="iso")
        )
        path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _copy_for_processing(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def _successful_batch_paths(
        self, status_key: str, batch_dir: Path, candidates: set[str]
    ) -> set[str]:
        successful = set()
        for path in self.last_extraction_status.get(status_key, set()):
            try:
                relative_path = (
                    Path(path)
                    .resolve()
                    .relative_to(batch_dir.resolve())
                    .as_posix()
                )
            except (OSError, ValueError):
                LOGGER.warning(
                    "Ignoring processing status path outside batch: %s", path
                )
                continue
            if relative_path in candidates:
                successful.add(relative_path)
        return successful

    @classmethod
    def _companies_in_dataframe(cls, dataframe: pd.DataFrame) -> set[str]:
        if dataframe.empty or "company" not in dataframe.columns:
            return set()
        return {
            cls._canonical_company_name(company)
            for company in dataframe["company"]
            if cls._has_value(company)
        }

    @classmethod
    def _replace_company_rows(
        cls,
        current: pd.DataFrame,
        replacements: pd.DataFrame,
        companies: set[str],
    ) -> pd.DataFrame:
        if current.empty or "company" not in current.columns:
            retained = current.iloc[0:0]
        else:
            retained = current.loc[
                ~current["company"].map(cls._canonical_company_name).isin(companies)
            ]
        return pd.concat([retained, replacements], ignore_index=True, sort=False)

    @staticmethod
    def _append_unique_rows(
        current: pd.DataFrame, additions: pd.DataFrame
    ) -> pd.DataFrame:
        if additions.empty:
            return current.copy(deep=True)
        combined = pd.concat([current, additions], ignore_index=True, sort=False)
        keys = combined.apply(
            lambda row: pd.DataFrame([row]).to_json(
                orient="records", date_format="iso"
            ),
            axis=1,
        )
        return combined.loc[~keys.duplicated(keep="first")].reset_index(drop=True)

    def _call_gemini_with_retry(self, schema, prompt, pdf_source):
        """Skip a Gemini input after it fails more than twice."""
        max_attempts = self.MAX_ALLOWED_FAILURES + 1
        for attempt in range(1, max_attempts + 1):
            try:
                response = self.gemini_client.call_gemini_structured_json(
                    schema,
                    prompt,
                    pdf_source,
                )
            except Exception as error:
                LOGGER.warning(
                    "Gemini request for %s failed on attempt %d of %d; "
                    "waiting %d seconds: %s",
                    pdf_source,
                    attempt,
                    max_attempts,
                    self.RETRY_DELAY_SECONDS,
                    error,
                )
                time.sleep(self.RETRY_DELAY_SECONDS)
                if attempt == max_attempts:
                    LOGGER.error(
                        "Skipping %s after %d failed Gemini requests",
                        pdf_source,
                        max_attempts,
                    )
                    return None
            else:
                time.sleep(self.REQUEST_DELAY_SECONDS)
                return response

        return None

    @staticmethod
    def _merge_pdfs(pdf_paths: list[Path], output_path: Path) -> None:
        """Merge PDFs into one file, retaining filenames as PDF bookmarks."""
        writer = PdfWriter()
        try:
            for pdf_path in pdf_paths:
                writer.append(str(pdf_path), outline_item=pdf_path.name)
            with output_path.open("wb") as output_file:
                writer.write(output_file)
        finally:
            writer.close()

    @staticmethod
    def _has_value(value) -> bool:
        """Return whether an extracted value should replace an older value."""
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, dict, set)):
            return bool(value)
        try:
            return not pd.isna(value)
        except (TypeError, ValueError):
            return True

    def _combine_company_records_with_gemini(
        self, records: list[dict]
    ) -> list[dict]:
        """Ask Gemini to reconcile independently extracted rows by fiscal year."""
        if not records:
            return []

        candidate_df = pd.DataFrame(records)
        combined_records = []
        for company, company_df in candidate_df.groupby(
            "company", sort=True, dropna=False
        ):
            if not self._has_value(company):
                LOGGER.warning("Skipping candidate rows without a company name")
                continue

            canonical_company = self._canonical_company_name(company)
            records_json = company_df.to_json(
                orient="records",
                date_format="iso",
                force_ascii=False,
            )
            response = self._call_gemini_with_retry(
                CompanyLevelExtDataCombinationResponse,
                COMPANY_LEVEL_COMBINATION_PROMPT.format(
                    company=canonical_company,
                    records_json=records_json,
                ),
                None,
            )
            if response is None or response.get("record") is None:
                continue

            record = self._normalise_company_record(
                response["record"], canonical_company
            )
            if record.get("reporting_period_type") != "annual":
                LOGGER.warning(
                    "Skipping non-annual reconciled record for %s",
                    canonical_company,
                )
                continue
            combined_records.append(record)

        return combined_records

    @classmethod
    def _canonical_company_name(cls, company) -> str:
        """Return the stable data-collection name for a JSE issuer."""
        if not cls._has_value(company):
            return ""

        supplied = str(company).strip().replace("_", " ")
        supplied_code = supplied.upper()
        ticker = None
        if supplied_code.endswith(".JO"):
            ticker = supplied_code
        elif any(
            supplied_code == value.removesuffix(".JO")
            for value in CANONICAL_JSE_NAMES.values()
        ):
            ticker = f"{supplied_code}.JO"
        else:
            company_key = cls._normalise_company_name(supplied)
            ticker = next(
                (
                    value
                    for name, value in JSE_NAMES.items()
                    if cls._normalise_company_name(name) == company_key
                ),
                None,
            )

        if ticker is None:
            return supplied
        return next(
            name
            for name, canonical_ticker in CANONICAL_JSE_NAMES.items()
            if canonical_ticker == ticker
        )

    @staticmethod
    def _canonical_currency_code(currency):
        if not Data_Processor._has_value(currency):
            return None
        supplied = str(currency).strip()
        key = re.sub(r"\s+", " ", supplied.casefold())
        if key in CURRENCY_CODE_ALIASES:
            return CURRENCY_CODE_ALIASES[key]
        if len(supplied) == 3 and supplied.isalpha():
            return supplied.upper()
        return supplied.upper()

    @staticmethod
    def _canonical_country_code(country):
        if not Data_Processor._has_value(country):
            return None
        supplied = str(country).strip()
        if len(supplied) == 2 and supplied.isalpha():
            return supplied.upper()
        ascii_name = unicodedata.normalize("NFKD", supplied).encode(
            "ascii", "ignore"
        ).decode("ascii")
        key = re.sub(r"[^a-z]+", " ", ascii_name.casefold()).strip()
        code = COUNTRY_CODE_ALIASES.get(key)
        if code is None:
            LOGGER.warning(
                "Could not normalize country %r to ISO 3166-1 alpha-2; "
                "using null",
                supplied,
            )
        return code

    @staticmethod
    def _canonical_reporting_unit(unit):
        if not Data_Processor._has_value(unit):
            return None
        scale = Data_Processor._reporting_scale(unit)
        return {
            1.0: "units",
            1_000.0: "thousands",
            1_000_000.0: "millions",
            1_000_000_000.0: "billions",
        }[scale]

    @classmethod
    def _iso_date(cls, value):
        parsed = cls._parse_date(value)
        if pd.isna(parsed):
            return None
        return parsed.date().isoformat()

    @classmethod
    def _numeric_value(cls, value):
        """Coerce formatted numbers while keeping missing data missing."""
        if not cls._has_value(value) or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return value

        supplied = str(value).strip()
        is_parenthesised = supplied.startswith("(") and supplied.endswith(")")
        supplied = supplied.strip("()")
        supplied = re.sub(r"[,%\s]", "", supplied)
        try:
            number = float(supplied)
        except (TypeError, ValueError):
            return None
        return -number if is_parenthesised else number

    @staticmethod
    def _sorted_unique(values) -> list:
        values = Data_Processor._list_values(values)
        unique = {
            str(value).strip()
            for value in values
            if Data_Processor._has_value(value)
        }
        return sorted(unique, key=str.casefold)

    @staticmethod
    def _list_values(values) -> list:
        if isinstance(values, str):
            try:
                values = ast.literal_eval(values)
            except (SyntaxError, ValueError):
                return []
        if isinstance(values, (list, tuple, set)):
            return list(values)
        return []

    @classmethod
    def _normalise_company_record(cls, record, company) -> dict:
        normalised = dict(record)
        normalised["company"] = cls._canonical_company_name(company)
        normalised["report_date"] = cls._iso_date(record.get("report_date"))
        normalised["reporting_currency"] = cls._canonical_currency_code(
            record.get("reporting_currency")
        )
        normalised["reporting_unit"] = cls._canonical_reporting_unit(
            record.get("reporting_unit")
        )

        for field in EXTERNAL_NUMERIC_FIELDS.intersection(normalised):
            normalised[field] = cls._numeric_value(normalised[field])

        currencies = {
            cls._canonical_currency_code(value)
            for value in cls._list_values(record.get("currencies_exposed_to"))
            if cls._has_value(value)
        }
        normalised["currencies_exposed_to"] = sorted(
            value for value in currencies if value
        )

        countries = {
            cls._canonical_country_code(value)
            for value in cls._list_values(record.get("countries_of_operation"))
            if cls._has_value(value)
        }
        normalised["countries_of_operation"] = sorted(
            value for value in countries if value
        )

        for field in (
            "foreign_subsidiaries",
            "major_customers_suppliers",
            "commodity_exposure",
            "bond_maturity_dates",
            "ownership_major_shareholders",
        ):
            if field in normalised:
                normalised[field] = cls._sorted_unique(normalised[field])
        return normalised

    @classmethod
    def _normalise_sens_record(cls, record, company) -> dict:
        normalised = dict(record)
        normalised["company"] = cls._canonical_company_name(company)
        normalised["announcement_date"] = cls._iso_date(
            record.get("announcement_date")
        )
        normalised["expected_completion_date"] = cls._iso_date(
            record.get("expected_completion_date")
        )
        normalised["event_value"] = cls._numeric_value(
            record.get("event_value")
        )
        normalised["event_unit"] = cls._canonical_reporting_unit(
            record.get("event_unit")
        )
        normalised["currency"] = cls._canonical_currency_code(
            record.get("currency")
        )
        normalised["country"] = cls._canonical_country_code(
            record.get("country")
        )
        if "banking_opportunities" in normalised:
            normalised["banking_opportunities"] = cls._sorted_unique(
                normalised["banking_opportunities"]
            )
        return normalised

    def extract_external_data_from_pdfs(
        self,
        source_dir=Path(__file__).resolve().parents[2] / "data" / "downloads",
        *,
        return_failures: bool = False,
    ):
        """
        Extracts external data from the pdfs in each company directory in the source directory.

        Params:
            source_dir: str - The root source directory. Assumes structure from data_collection.py,
            where there is a SENS subdirectory in ever company's directory. This is set to
            data/downloads by default

        Returns:
            ``(curr_company_lvl_df, curr_sens_df)``. When ``return_failures``
            is true, a third value maps company names to the keywords for PDFs
            that could not be extracted.
        """

        source_path = Path(source_dir)
        self.last_extraction_status = {
            "external_documents": set(),
            "sens_documents": set(),
        }
        self.last_failed_scrapes = {}
        attempted_documents: set[Path] = set()
        company_dirs = sorted(
            path for path in source_path.iterdir() if path.is_dir()
        )
        company_records = []
        sens_records = []

        for company_dir in company_dirs:
            canonical_company = self._canonical_company_name(company_dir.name)
            # Non-SENS documents must be processed independently so that Gemini
            # cannot combine or confuse values from different reporting periods.
            for document_path in sorted(company_dir.glob("*.pdf")):
                attempted_documents.add(document_path.resolve())
                curr_company_lvl_json = self._call_gemini_with_retry(
                    CompanyLevelExtDataResponse,
                    COMPANY_LEVEL_PROMPT.format(company=canonical_company),
                    document_path,
                )
                if curr_company_lvl_json is not None:
                    self.last_extraction_status["external_documents"].add(
                        str(document_path.resolve())
                    )
                    for record in curr_company_lvl_json.get("records", []):
                        normalised_record = self._normalise_company_record(
                            record, canonical_company
                        )
                        # The collector's filename retains the classified report
                        # type (for example ``interim_results__``), making it more
                        # reliable reconciliation evidence than a generated title.
                        normalised_record["source_document"] = document_path.name
                        company_records.append(normalised_record)

            sens_paths = sorted((company_dir / "SENS").glob("*.pdf"))
            if not sens_paths:
                continue
            attempted_documents.update(path.resolve() for path in sens_paths)

            with TemporaryDirectory(prefix="merged_sens_") as temp_dir:
                merged_sens_path = (
                    Path(temp_dir) / f"{company_dir.name}__SENS_merged.pdf"
                )
                try:
                    self._merge_pdfs(sens_paths, merged_sens_path)
                except Exception as error:
                    LOGGER.error(
                        "Could not merge SENS PDFs for %s; skipping them: %s",
                        company_dir.name,
                        error,
                    )
                    continue

                curr_sens_json = self._call_gemini_with_retry(
                    SENSEventsResponse,
                    SENS_PROMPT.format(company=canonical_company),
                    merged_sens_path,
                )
                if curr_sens_json is not None:
                    self.last_extraction_status["sens_documents"].update(
                        str(path.resolve()) for path in sens_paths
                    )
                    sens_records.extend(
                        self._normalise_sens_record(record, canonical_company)
                        for record in curr_sens_json.get("events", [])
                    )

        # Reconciliation is deliberately a separate final batch. Candidate rows
        # retain their source periods until Gemini decides which same-year annual
        # disclosures belong in each final company record.
        curr_company_df = pd.DataFrame(
            self._combine_company_records_with_gemini(company_records)
        )
        curr_sens_df = pd.DataFrame(sens_records)

        if not curr_company_df.empty and "company" in curr_company_df.columns:
            curr_company_df = curr_company_df.sort_values(
                ["company"], kind="stable"
            ).reset_index(drop=True)
        if not curr_sens_df.empty:
            sort_columns = [
                column
                for column in (
                    "company",
                    "announcement_date",
                    "source_document",
                    "title",
                )
                if column in curr_sens_df.columns
            ]
            if sort_columns:
                curr_sens_df = curr_sens_df.sort_values(
                    sort_columns, kind="stable", na_position="last"
                ).reset_index(drop=True)

        successful_documents = {
            Path(path).resolve()
            for paths in self.last_extraction_status.values()
            for path in paths
        }
        self.last_failed_scrapes = self._failed_scrape_keywords(
            source_path,
            attempted_documents - successful_documents,
        )
        if return_failures:
            return (
                curr_company_df,
                curr_sens_df,
                self.get_failed_scrape_keywords(),
            )
        return curr_company_df, curr_sens_df

    @classmethod
    def _failed_scrape_keywords(
        cls, source_dir: Path, failed_paths: set[Path]
    ) -> dict[str, list[str]]:
        """Build deterministic company-to-document-keyword diagnostics."""
        failures: dict[str, set[str]] = {}
        source_dir = source_dir.resolve()
        known_document_types = {
            "annual_report",
            "financial_statements",
            "interim_results",
            "results_presentation",
        }
        for path in sorted(failed_paths, key=lambda item: str(item)):
            try:
                relative = path.resolve().relative_to(source_dir)
            except (OSError, ValueError):
                LOGGER.warning("Ignoring failed extraction outside source: %s", path)
                continue
            if len(relative.parts) < 2:
                continue

            company = cls._canonical_company_name(relative.parts[0])
            if "SENS" in relative.parts[1:-1]:
                keyword = "SENS"
            else:
                prefix = relative.name.split("__", 1)[0]
                if prefix in known_document_types:
                    keyword = prefix.replace("_", " ")
                else:
                    keyword = re.sub(
                        r"[^a-z0-9]+", " ", relative.stem.casefold()
                    ).strip()
            if company and keyword:
                failures.setdefault(company, set()).add(keyword)

        return {
            company: sorted(keywords)
            for company, keywords in sorted(failures.items())
        }

    def score_sens_opportunities(self, sens_df: pd.DataFrame) -> pd.DataFrame:
        """Fill missing SENS opportunity ratings with one Gemini batch call.

        A row is sent only when at least one of the three pillar score columns
        is absent or null. Existing scores are preserved, including when
        Gemini returns a replacement value for them. The input dataframe is
        never modified.
        """
        if not isinstance(sens_df, pd.DataFrame):
            raise TypeError("sens_df must be a pandas DataFrame")

        scored = sens_df.copy(deep=True)
        for column in self.SENS_OPPORTUNITY_SCORE_COLUMNS:
            if column not in scored.columns:
                scored[column] = math.nan

        missing_positions = [
            position
            for position in range(len(scored))
            if any(
                not self._has_value(scored.iloc[position][column])
                for column in self.SENS_OPPORTUNITY_SCORE_COLUMNS
            )
        ]
        if not missing_positions:
            return scored

        pending = scored.iloc[missing_positions].copy()
        pending = pending.drop(columns=["_row_id"], errors="ignore")
        pending.insert(0, "_row_id", missing_positions)
        sens_json = pending.to_json(
            orient="records", date_format="iso", force_ascii=False
        )
        response = self._call_gemini_with_retry(
            SENSOpportunityScoresResponse,
            SENS_OPPORTUNITY_SCORING_PROMPT.format(sens_json=sens_json),
            None,
        )
        if response is None:
            return scored

        expected_positions = set(missing_positions)
        reviewed_positions = set()
        for rating in response.get("scores", []):
            row_id = rating.get("row_id")
            if (
                isinstance(row_id, bool)
                or not isinstance(row_id, Number)
                or not math.isfinite(float(row_id))
                or int(row_id) != row_id
            ):
                row_position = None
            else:
                row_position = int(row_id)
            if (
                row_position not in expected_positions
                or row_position in reviewed_positions
            ):
                LOGGER.warning(
                    "Gemini returned an unknown or duplicate SENS row_id: %s",
                    row_id,
                )
                continue
            reviewed_positions.add(row_position)
            for column in self.SENS_OPPORTUNITY_SCORE_COLUMNS:
                if self._has_value(scored.iloc[row_position][column]):
                    continue
                score = self._bounded_opportunity_score(rating.get(column))
                if score is None:
                    LOGGER.warning(
                        "Gemini returned an invalid %s for SENS row_id %s",
                        column,
                        row_position,
                    )
                    continue
                scored.iat[
                    row_position, scored.columns.get_loc(column)
                ] = score

        missing_reviews = expected_positions - reviewed_positions
        if missing_reviews:
            LOGGER.warning(
                "Gemini did not score SENS row_ids: %s",
                ", ".join(str(row_id) for row_id in sorted(missing_reviews)),
            )
        return scored

    @staticmethod
    def _bounded_opportunity_score(value) -> float | None:
        if isinstance(value, bool) or not isinstance(value, Number):
            return None
        score = float(value)
        if not math.isfinite(score) or not 0 <= score <= 1:
            return None
        return score

    @staticmethod
    def _normalise_company_name(company) -> str:
        if not Data_Processor._has_value(company):
            return ""
        words = re.findall(r"[a-z0-9]+", str(company).casefold())
        legal_suffixes = {
            "group",
            "holding",
            "holdings",
            "inc",
            "incorporated",
            "limited",
            "ltd",
            "nv",
            "plc",
        }
        if len(words) >= 2 and words[-2:] == ["n", "v"]:
            del words[-2:]
        while words and words[-1] in legal_suffixes:
            words.pop()
        return "".join(words)

    @classmethod
    def _jse_ticker_for_company(cls, company) -> str | None:
        company_key = cls._normalise_company_name(company)
        return next(
            (
                ticker
                for name, ticker in cls.JSE_NAMES.items()
                if cls._normalise_company_name(name) == company_key
            ),
            None,
        )

    @staticmethod
    def _parse_date(value):
        if not Data_Processor._has_value(value):
            return pd.NaT
        day_first = bool(
            isinstance(value, str)
            and re.fullmatch(r"\d{1,2}[-/]\d{1,2}[-/]\d{4}", value.strip())
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            return pd.to_datetime(
                value,
                errors="coerce",
                utc=True,
                dayfirst=day_first,
            )

    @staticmethod
    def _reporting_scale(reporting_unit) -> float:
        if not Data_Processor._has_value(reporting_unit):
            return 1.0
        try:
            numeric_unit = float(reporting_unit)
        except (TypeError, ValueError):
            numeric_unit = None
        if numeric_unit in {1.0, 1_000.0, 1_000_000.0, 1_000_000_000.0}:
            return numeric_unit
        unit = str(reporting_unit).strip().casefold()
        compact_unit = re.sub(r"[^a-z0-9]", "", unit)
        if (
            "billion" in unit
            or compact_unit in {"b", "bn", "rbn"}
            or compact_unit.endswith("bn")
        ):
            return 1_000_000_000.0
        if (
            "million" in unit
            or compact_unit in {"m", "mn", "rm"}
            or compact_unit.endswith(("m", "mn"))
        ):
            return 1_000_000.0
        if (
            "thousand" in unit
            or "000" in compact_unit
            or compact_unit.endswith("k")
        ):
            return 1_000.0
        return 1.0

    @classmethod
    def _require_base_units(
        cls,
        dataframe: pd.DataFrame,
        value_fields,
        unit_fields,
        dataframe_name: str,
    ) -> None:
        """Reject legacy scaled values now that extraction returns base units."""
        present_values = set(value_fields).intersection(dataframe.columns)
        present_units = [
            field for field in unit_fields if field in dataframe.columns
        ]
        if not present_values or not present_units:
            return

        for row_index, row in dataframe.iterrows():
            if not any(cls._has_value(row.get(field)) for field in present_values):
                continue
            unit = next(
                (
                    row.get(field)
                    for field in present_units
                    if cls._has_value(row.get(field))
                ),
                None,
            )
            if unit is None:
                continue
            normalized_unit = str(unit).strip().casefold()
            if normalized_unit not in {"1", "1.0", "unit", "units"}:
                raise ValueError(
                    f"{dataframe_name} row {row_index!r} uses {unit!r}; "
                    "monetary values must already be in base 'units'"
                )

    @staticmethod
    def _statement_value(statement, row_names, report_date):
        if not isinstance(statement, pd.DataFrame) or statement.empty:
            return None
        if pd.isna(report_date):
            return None

        normalised_rows = {
            re.sub(r"[^a-z0-9]", "", str(index).casefold()): index
            for index in statement.index
        }
        statement_row = next(
            (
                normalised_rows.get(
                    re.sub(r"[^a-z0-9]", "", name.casefold())
                )
                for name in row_names
                if re.sub(r"[^a-z0-9]", "", name.casefold())
                in normalised_rows
            ),
            None,
        )
        if statement_row is None:
            return None

        dated_columns = []
        for column in statement.columns:
            column_date = Data_Processor._parse_date(column)
            if not pd.isna(column_date):
                dated_columns.append(
                    (abs((column_date - report_date).days), column)
                )
        if not dated_columns:
            return None

        days_apart, matching_column = min(dated_columns, key=lambda item: item[0])
        if days_apart > 7:
            return None

        value = statement.at[statement_row, matching_column]
        if not Data_Processor._has_value(value):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _mapped_statement_value(
        cls, statements, statement_names, row_names, report_date
    ):
        if isinstance(statement_names, str):
            statement_names = (statement_names,)
        for statement_name in statement_names:
            value = cls._statement_value(
                statements.get(statement_name), row_names, report_date
            )
            if value is not None:
                return value
        return None

    @classmethod
    def _set_yfinance_value(
        cls, dataframe, row_index, field, yfinance_value, company, ticker
    ) -> None:
        if not cls._has_value(yfinance_value):
            return

        if field not in dataframe.columns:
            dataframe[field] = pd.NA
        elif (
            isinstance(yfinance_value, (list, tuple, dict, set))
            or field in EXTERNAL_NUMERIC_FIELDS
            and not pd.api.types.is_numeric_dtype(dataframe[field].dtype)
        ):
            # Pandas extension string columns reject list-like or numeric
            # assignments, even when their current value is empty.
            dataframe[field] = dataframe[field].astype(object)

        current_value = dataframe.at[row_index, field]
        values_match = False
        if cls._has_value(current_value):
            try:
                values_match = math.isclose(
                    float(current_value),
                    float(yfinance_value),
                    rel_tol=YFINANCE_NUMERIC_WARNING_REL_TOLERANCE,
                    abs_tol=1e-9,
                )
            except (TypeError, ValueError):
                values_match = (
                    str(current_value).strip().casefold()
                    == str(yfinance_value).strip().casefold()
                )

            if not values_match:
                LOGGER.warning(
                    "%s: %s differs from yfinance %s (%r != %r); using "
                    "the yfinance value",
                    company,
                    field,
                    ticker,
                    current_value,
                    yfinance_value,
                )

        dataframe.at[row_index, field] = yfinance_value

    @staticmethod
    def _load_yfinance_company_data(ticker_symbol):
        ticker = yf.Ticker(ticker_symbol)

        try:
            info = ticker.info or {}
        except Exception as error:
            LOGGER.warning(
                "Could not load yfinance company information for %s: %s",
                ticker_symbol,
                error,
            )
            info = {}
        if not isinstance(info, dict):
            info = {}

        # Yahoo normally exposes cost of revenue in statements, but when only
        # the quote-summary financial data is populated it can still be
        # reconstructed exactly from total revenue and gross profit.
        if not Data_Processor._has_value(info.get("costOfRevenue")):
            total_revenue = Data_Processor._numeric_value(
                info.get("totalRevenue")
            )
            gross_profit = Data_Processor._numeric_value(
                info.get("grossProfits")
            )
            if total_revenue is not None and gross_profit is not None:
                info["costOfRevenue"] = total_revenue - gross_profit

        # FastInfo is sourced independently from ``info`` and is frequently
        # available when Yahoo's larger quote-summary response is incomplete.
        fast_info_fields = {
            "market_cap": "marketCap",
            "last_price": "currentPrice",
            "year_change": "52WeekChange",
        }
        try:
            fast_info = ticker.fast_info
            for fast_name, info_name in fast_info_fields.items():
                if Data_Processor._has_value(info.get(info_name)):
                    continue
                value = fast_info.get(fast_name)
                if isinstance(value, Number) and Data_Processor._has_value(value):
                    info[info_name] = value
            if not Data_Processor._has_value(info.get("currency")):
                fast_currency = fast_info.get("currency")
                if isinstance(fast_currency, str) and fast_currency.strip():
                    info["currency"] = fast_currency
        except Exception as error:
            LOGGER.warning(
                "Could not load yfinance fast information for %s: %s",
                ticker_symbol,
                error,
            )

        # ``currentPrice`` for JSE listings is normally returned in ZAc. A
        # repaired history request performs yfinance's own ZAc-to-ZAR
        # normalisation and also guards against occasional mixed-unit history.
        try:
            price_history = ticker.history(
                period="5d",
                auto_adjust=False,
                repair=True,
            )
            price_metadata = ticker.get_history_metadata(repair=True) or {}
            repaired_currency = Data_Processor._canonical_currency_code(
                price_metadata.get("currency")
            )
            if (
                isinstance(price_history, pd.DataFrame)
                and not price_history.empty
                and "Close" in price_history.columns
                and repaired_currency == "ZAR"
            ):
                closes = pd.to_numeric(
                    price_history["Close"], errors="coerce"
                ).dropna()
                if not closes.empty:
                    info["_zarSharePrice"] = float(closes.iloc[-1])
        except Exception as error:
            LOGGER.warning(
                "Could not load repaired ZAR share price for %s: %s",
                ticker_symbol,
                error,
            )

        # Retain a deterministic fallback when repaired history is unavailable.
        # Do not divide blindly: the quote metadata must explicitly identify
        # cents or rand.
        if not Data_Processor._has_value(info.get("_zarSharePrice")):
            raw_price = Data_Processor._numeric_value(
                info.get("currentPrice", info.get("regularMarketPrice"))
            )
            raw_currency = str(info.get("currency", "")).strip().casefold()
            if raw_price is not None and raw_currency == "zac":
                info["_zarSharePrice"] = float(raw_price) / 100
            elif raw_price is not None and raw_currency == "zar":
                info["_zarSharePrice"] = float(raw_price)

        statements = {}
        statement_getters = {
            "income": ticker.get_income_stmt,
            "balance": ticker.get_balance_sheet,
            "cash_flow": ticker.get_cash_flow,
        }
        for statement_name, getter in statement_getters.items():
            available_statements = []
            for frequency in ("yearly", "quarterly"):
                try:
                    statement = getter(freq=frequency)
                    if isinstance(statement, pd.DataFrame) and not statement.empty:
                        available_statements.append(statement)
                except Exception as error:
                    LOGGER.warning(
                        "Could not load yfinance %s %s statement for %s: %s",
                        frequency,
                        statement_name,
                        ticker_symbol,
                        error,
                    )
            if available_statements:
                statement = pd.concat(available_statements, axis=1)
                statements[statement_name] = statement.loc[
                    :, ~statement.columns.duplicated()
                ]
            else:
                statements[statement_name] = pd.DataFrame()

        major_shareholders = []
        for holder_type, getter_name in (
            ("institutional", "get_institutional_holders"),
            ("mutual-fund", "get_mutualfund_holders"),
        ):
            try:
                holders = getattr(ticker, getter_name)()
            except Exception as error:
                LOGGER.warning(
                    "Could not load yfinance %s holders for %s: %s",
                    holder_type,
                    ticker_symbol,
                    error,
                )
                continue
            if not isinstance(holders, pd.DataFrame) or holders.empty:
                continue
            holder_column = next(
                (
                    column
                    for column in holders.columns
                    if str(column).strip().casefold()
                    in {"holder", "organization", "name"}
                ),
                None,
            )
            if holder_column is not None:
                major_shareholders.extend(holders[holder_column].tolist())
        major_shareholders = Data_Processor._sorted_unique(major_shareholders)
        if major_shareholders:
            info["_majorShareholders"] = major_shareholders

        return info, statements

    def validate_external_data(
        self,
        external_df: pd.DataFrame,
        sens_df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Validate and enrich extracted data with matching yfinance values.

        The argument and return order matches extraction and standardization:
        ``(external_df, sens_df)``. SENS fields are retained because yfinance
        has no equivalent source for corporate
        event values, counterparties, or announcement metadata. Company
        statement values are matched to report dates within seven days. Both
        extracted and yfinance monetary values are expected in base units.
        Annual and quarterly statements,
        quote/fast-info market fields, major-holder tables, info fallbacks, and
        statement-derived working-capital days are all used where they map to
        the external-data schema. Missing values include None, pandas NA/NaN,
        empty strings, and empty collections. Supplied values are replaced;
        numeric differences above five percent and non-numeric mismatches are
        logged first.
        """
        if not isinstance(external_df, pd.DataFrame):
            raise TypeError("external_df must be a pandas DataFrame")
        if not isinstance(sens_df, pd.DataFrame):
            raise TypeError("sens_df must be a pandas DataFrame")
        if "event_value" in external_df.columns and any(
            field in sens_df.columns
            for field in ("reporting_unit", "reporting_currency", "revenue")
        ):
            raise ValueError(
                "validate_external_data expects (external_df, sens_df); the "
                "supplied dataframes appear to be reversed"
            )

        validated_sens_df = sens_df.copy(deep=True)
        validated_expenditure_df = external_df.copy(deep=True)

        if "reporting_currency" in validated_expenditure_df.columns:
            if "original_currency" not in validated_expenditure_df.columns:
                validated_expenditure_df["original_currency"] = (
                    validated_expenditure_df["reporting_currency"].map(
                        self._canonical_currency_code
                    ).astype(object)
                )
            else:
                validated_expenditure_df["original_currency"] = (
                    validated_expenditure_df["original_currency"].astype(object)
                )
                missing_original = validated_expenditure_df[
                    "original_currency"
                ].map(lambda value: not self._has_value(value))
                validated_expenditure_df.loc[
                    missing_original, "original_currency"
                ] = validated_expenditure_df.loc[
                    missing_original, "reporting_currency"
                ].map(self._canonical_currency_code)

        if "company" not in validated_expenditure_df.columns:
            LOGGER.warning(
                "Cannot validate expenditure data without a company column"
            )
            return validated_expenditure_df, validated_sens_df

        self._require_base_units(
            validated_expenditure_df,
            EXTERNAL_MONETARY_FIELDS,
            ("reporting_unit", "unit"),
            "external_df",
        )

        yfinance_cache = {}
        exchange_rate_cache = {}
        for row_index, row in validated_expenditure_df.iterrows():
            company = row.get("company")
            ticker_symbol = self._jse_ticker_for_company(company)
            if ticker_symbol is None:
                LOGGER.warning(
                    "%s is not present in JSE_NAMES; skipping yfinance "
                    "validation",
                    company,
                )
                continue

            if ticker_symbol not in yfinance_cache:
                try:
                    yfinance_cache[ticker_symbol] = (
                        self._load_yfinance_company_data(ticker_symbol)
                    )
                except Exception as error:
                    LOGGER.warning(
                        "Could not initialise yfinance ticker %s: %s",
                        ticker_symbol,
                        error,
                    )
                    yfinance_cache[ticker_symbol] = None
            if yfinance_cache[ticker_symbol] is None:
                continue
            info, statements = yfinance_cache[ticker_symbol]

            financial_currency = self._canonical_currency_code(
                info.get("financialCurrency")
            )
            current_currency = self._canonical_currency_code(
                row.get("reporting_currency")
            )
            original_currency = self._canonical_currency_code(
                row.get("original_currency")
            )
            is_standardized_zar = (
                current_currency == "ZAR"
                and self._canonical_reporting_unit(row.get("reporting_unit"))
                == "units"
                and original_currency not in {None, "ZAR"}
                and self._has_value(row.get("fx_rate_to_zar"))
            )
            if self._has_value(financial_currency):
                self._set_yfinance_value(
                    validated_expenditure_df,
                    row_index,
                    "original_currency",
                    financial_currency,
                    company,
                    ticker_symbol,
                )
                original_currency = financial_currency
                if not is_standardized_zar:
                    self._set_yfinance_value(
                        validated_expenditure_df,
                        row_index,
                        "reporting_currency",
                        financial_currency,
                        company,
                        ticker_symbol,
                    )
                    current_currency = financial_currency

            report_date = self._parse_date(row.get("report_date"))
            reporting_unit = row.get("reporting_unit")
            if not self._has_value(reporting_unit):
                reporting_unit = "units"
                self._set_yfinance_value(
                    validated_expenditure_df,
                    row_index,
                    "reporting_unit",
                    reporting_unit,
                    company,
                    ticker_symbol,
                )
            validation_fx_rate = None
            if is_standardized_zar:
                stored_rate = row.get("fx_rate_to_zar")
                if (
                    self._has_value(stored_rate)
                    and original_currency
                    == self._canonical_currency_code(row.get("original_currency"))
                ):
                    validation_fx_rate = float(stored_rate)
                else:
                    rate_result = self._zar_exchange_rate(
                        original_currency,
                        report_date,
                        exchange_rate_cache,
                    )
                    if rate_result is not None:
                        validation_fx_rate, observed_date = rate_result
                        validated_expenditure_df.at[
                            row_index, "fx_rate_to_zar"
                        ] = validation_fx_rate
                        if "fx_rate_date" not in validated_expenditure_df.columns:
                            validated_expenditure_df["fx_rate_date"] = pd.NA
                        validated_expenditure_df.at[
                            row_index, "fx_rate_date"
                        ] = observed_date

            statement_values = {}
            for field, (
                statement_name, row_names, use_absolute_value
            ) in YFINANCE_STATEMENT_FIELDS.items():
                value = self._mapped_statement_value(
                    statements, statement_name, row_names, report_date
                )
                if value is None:
                    continue
                if use_absolute_value:
                    value = abs(value)
                statement_values[field] = value
                if is_standardized_zar:
                    if validation_fx_rate is None:
                        LOGGER.warning(
                            "%s: cannot validate %s in a standardized ZAR "
                            "row without an exchange rate",
                            company,
                            field,
                        )
                        continue
                    value *= validation_fx_rate
                self._set_yfinance_value(
                    validated_expenditure_df,
                    row_index,
                    field,
                    value,
                    company,
                    ticker_symbol,
                )

            derived_values = {}
            for field, (
                balance_field, flow_field
            ) in YFINANCE_DERIVED_WORKING_CAPITAL_FIELDS.items():
                balance = statement_values.get(balance_field)
                flow = statement_values.get(flow_field)
                if balance is None or flow in (None, 0):
                    continue
                derived_values[field] = abs(float(balance) / float(flow)) * 365

            if all(
                field in derived_values
                for field in ("receivable_days", "payable_days", "inventory_days")
            ):
                derived_values["cash_conversion_cycle"] = (
                    derived_values["inventory_days"]
                    + derived_values["receivable_days"]
                    - derived_values["payable_days"]
                )

            for field, value in derived_values.items():
                self._set_yfinance_value(
                    validated_expenditure_df,
                    row_index,
                    field,
                    value,
                    company,
                    ticker_symbol,
                )

            for field, info_names in YFINANCE_INFO_FIELDS.items():
                if field in statement_values:
                    continue
                value = next(
                    (
                        info.get(info_name)
                        for info_name in info_names
                        if self._has_value(info.get(info_name))
                    ),
                    None,
                )
                if field in EXTERNAL_NUMERIC_FIELDS:
                    value = self._numeric_value(value)
                quote_currency = self._canonical_currency_code(
                    info.get("currency")
                )
                is_zar_quote_field = (
                    field in YFINANCE_ZAR_QUOTE_FIELDS
                    and quote_currency == "ZAR"
                )
                if self._has_value(value) and is_zar_quote_field:
                    if current_currency != "ZAR":
                        rate_result = self._zar_exchange_rate(
                            current_currency,
                            report_date,
                            exchange_rate_cache,
                        )
                        if rate_result is None:
                            LOGGER.warning(
                                "%s: cannot validate ZAR-quoted %s in %s "
                                "without an exchange rate",
                                company,
                                field,
                                current_currency,
                            )
                            continue
                        quote_fx_rate, _ = rate_result
                        value = float(value) / quote_fx_rate
                elif (
                    self._has_value(value)
                    and field in EXTERNAL_MONETARY_FIELDS
                ):
                    if is_standardized_zar:
                        if validation_fx_rate is None:
                            LOGGER.warning(
                                "%s: cannot validate %s in a standardized "
                                "ZAR row without an exchange rate",
                                company,
                                field,
                            )
                            continue
                        value = float(value) * validation_fx_rate
                self._set_yfinance_value(
                    validated_expenditure_df,
                    row_index,
                    field,
                    value,
                    company,
                    ticker_symbol,
                )

        return validated_expenditure_df, validated_sens_df

    @classmethod
    def _history_rate_on_or_before(cls, ticker_symbol, valuation_date):
        """Load the last available Yahoo close on or before a calendar date."""
        target_date = cls._parse_date(valuation_date)
        if pd.isna(target_date):
            return None

        ticker = yf.Ticker(ticker_symbol)
        start_date = (target_date - pd.Timedelta(days=10)).date().isoformat()
        end_date = (target_date + pd.Timedelta(days=1)).date().isoformat()
        history = ticker.history(
            start=start_date,
            end=end_date,
            auto_adjust=False,
        )
        if not isinstance(history, pd.DataFrame) or history.empty:
            return None
        if "Close" not in history.columns:
            return None

        closes = pd.to_numeric(history["Close"], errors="coerce").dropna()
        if closes.empty:
            return None

        history_dates = pd.to_datetime(closes.index, errors="coerce", utc=True)
        eligible = [
            position
            for position, history_date in enumerate(history_dates)
            if not pd.isna(history_date) and history_date.date() <= target_date.date()
        ]
        if not eligible:
            return None

        position = eligible[-1]
        rate = float(closes.iloc[position])
        if not math.isfinite(rate) or rate <= 0:
            return None
        return rate, history_dates[position].date().isoformat()

    @classmethod
    def _zar_exchange_rate(cls, currency, valuation_date, cache):
        """Return one unit of ``currency`` in ZAR and its market date."""
        currency_code = cls._canonical_currency_code(currency)
        rate_date = cls._iso_date(valuation_date)
        if currency_code == "ZAR":
            return 1.0, rate_date
        if rate_date is None and currency_code is not None:
            LOGGER.warning(
                "Cannot convert %s to ZAR without a row date or "
                "fx_as_of_date",
                currency_code,
            )
            return None
        if (
            currency_code is None
            or len(currency_code) != 3
            or not currency_code.isalpha()
        ):
            return None

        cache_key = (currency_code, rate_date)
        if cache_key in cache:
            return cache[cache_key]

        direct_ticker = f"{currency_code}ZAR=X"
        inverse_ticker = f"ZAR{currency_code}=X"
        try:
            result = cls._history_rate_on_or_before(direct_ticker, rate_date)
        except Exception as error:
            LOGGER.warning(
                "Could not load %s exchange rates from yfinance: %s",
                direct_ticker,
                error,
            )
            result = None

        if result is None:
            try:
                inverse_result = cls._history_rate_on_or_before(
                    inverse_ticker, rate_date
                )
            except Exception as error:
                LOGGER.warning(
                    "Could not load %s exchange rates from yfinance: %s",
                    inverse_ticker,
                    error,
                )
                inverse_result = None
            if inverse_result is not None:
                inverse_rate, observed_date = inverse_result
                result = 1.0 / inverse_rate, observed_date

        if result is None:
            LOGGER.warning(
                "No yfinance ZAR exchange rate was available for %s on or "
                "before %s; values remain in %s",
                currency_code,
                rate_date,
                currency_code,
            )
        cache[cache_key] = result
        return result

    def standardize_data(
        self,
        external_df: pd.DataFrame,
        sens_df: pd.DataFrame,
        fx_as_of_date=None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Convert base-unit monetary values to ZAR.

        SENS rates use ``announcement_date`` and external-data rates use
        ``report_date``. ``fx_as_of_date`` is only a deterministic fallback for
        rows whose relevant date is missing. Yahoo's last available close on or
        before that date is used, so weekends and market holidays are handled.

        The input frames are never modified. The argument and return order
        matches ``extract_external_data_from_pdfs``:
        ``(external_df, sens_df)``.
        Inputs are expected to contain base-unit values produced by extraction;
        this function does not expand thousands, millions, or billions.
        Successfully converted rows have currency ``ZAR`` and
        audit columns ``original_currency``, ``fx_rate_to_zar`` and
        ``fx_rate_date``. If no historical rate is available, original values and
        the original currency are retained rather than being mislabeled as ZAR.
        """
        if not isinstance(external_df, pd.DataFrame):
            raise TypeError("external_df must be a pandas DataFrame")
        if not isinstance(sens_df, pd.DataFrame):
            raise TypeError("sens_df must be a pandas DataFrame")

        if (
            "event_value" in external_df.columns
            and "reporting_unit" in sens_df.columns
        ):
            raise ValueError(
                "standardize_data expects (external_df, sens_df); the supplied "
                "dataframes appear to be reversed"
            )

        standardized_sens_df = sens_df.copy(deep=True)
        standardized_external_df = external_df.copy(deep=True)

        self._require_base_units(
            standardized_external_df,
            EXTERNAL_MONETARY_FIELDS,
            ("reporting_unit", "unit"),
            "external_df",
        )
        self._require_base_units(
            standardized_sens_df,
            ("event_value",),
            ("event_unit", "unit"),
            "sens_df",
        )

        fallback_date = self._iso_date(fx_as_of_date)
        if fx_as_of_date is not None and fallback_date is None:
            raise ValueError("fx_as_of_date must be a valid date")
        rate_cache = {}

        for field in EXTERNAL_NUMERIC_FIELDS.intersection(
            standardized_external_df.columns
        ):
            standardized_external_df[field] = pd.to_numeric(
                standardized_external_df[field], errors="coerce"
            ).astype(float)

        if "reporting_currency" in standardized_external_df.columns:
            if "original_currency" not in standardized_external_df.columns:
                standardized_external_df["original_currency"] = (
                    standardized_external_df["reporting_currency"].map(
                        self._canonical_currency_code
                    ).astype(object)
                )
            else:
                standardized_external_df["original_currency"] = (
                    standardized_external_df["original_currency"].astype(object)
                )
            if "fx_rate_to_zar" not in standardized_external_df.columns:
                standardized_external_df["fx_rate_to_zar"] = pd.NA
            if "fx_rate_date" not in standardized_external_df.columns:
                standardized_external_df["fx_rate_date"] = pd.NA

        for row_index, row in standardized_external_df.iterrows():
            if "report_date" in standardized_external_df.columns:
                report_date = self._iso_date(row.get("report_date"))
            else:
                report_date = None

            if "reporting_currency" not in standardized_external_df.columns:
                continue
            currency = self._canonical_currency_code(row.get("reporting_currency"))
            original_currency = self._canonical_currency_code(
                row.get("original_currency")
            )
            if not self._has_value(original_currency):
                original_currency = currency
            standardized_external_df.at[
                row_index, "original_currency"
            ] = original_currency
            standardized_external_df.at[
                row_index, "reporting_currency"
            ] = currency
            relevant_fields = EXTERNAL_MONETARY_FIELDS.intersection(
                standardized_external_df.columns
            )
            if not any(
                self._has_value(standardized_external_df.at[row_index, field])
                for field in relevant_fields
            ):
                continue

            rate_result = self._zar_exchange_rate(
                currency, report_date or fallback_date, rate_cache
            )
            if rate_result is None:
                continue
            rate, observed_date = rate_result
            already_converted = (
                currency == "ZAR"
                and original_currency != "ZAR"
                and self._has_value(row.get("fx_rate_to_zar"))
            )
            for field in relevant_fields:
                value = standardized_external_df.at[row_index, field]
                if self._has_value(value) and not already_converted:
                    standardized_external_df.at[row_index, field] = (
                        float(value) * rate
                    )
            standardized_external_df.at[
                row_index, "reporting_currency"
            ] = "ZAR"
            if not already_converted:
                standardized_external_df.at[row_index, "fx_rate_to_zar"] = rate
                standardized_external_df.at[
                    row_index, "fx_rate_date"
                ] = observed_date

        if "event_value" in standardized_sens_df.columns:
            standardized_sens_df["event_value"] = pd.to_numeric(
                standardized_sens_df["event_value"], errors="coerce"
            ).astype(float)
        if "currency" in standardized_sens_df.columns:
            if "original_currency" not in standardized_sens_df.columns:
                standardized_sens_df["original_currency"] = (
                    standardized_sens_df["currency"].map(
                        self._canonical_currency_code
                    ).astype(object)
                )
            else:
                standardized_sens_df["original_currency"] = (
                    standardized_sens_df["original_currency"].astype(object)
                )
            if "fx_rate_to_zar" not in standardized_sens_df.columns:
                standardized_sens_df["fx_rate_to_zar"] = pd.NA
            if "fx_rate_date" not in standardized_sens_df.columns:
                standardized_sens_df["fx_rate_date"] = pd.NA

        for row_index, row in standardized_sens_df.iterrows():
            if "announcement_date" in standardized_sens_df.columns:
                announcement_date = self._iso_date(row.get("announcement_date"))
            else:
                announcement_date = None

            if "currency" not in standardized_sens_df.columns:
                continue
            currency = self._canonical_currency_code(row.get("currency"))
            original_currency = self._canonical_currency_code(
                row.get("original_currency")
            )
            if not self._has_value(original_currency):
                original_currency = currency
            standardized_sens_df.at[
                row_index, "original_currency"
            ] = original_currency
            standardized_sens_df.at[row_index, "currency"] = currency
            if (
                "event_value" not in standardized_sens_df.columns
                or not self._has_value(
                    standardized_sens_df.at[row_index, "event_value"]
                )
            ):
                continue

            rate_result = self._zar_exchange_rate(
                currency, announcement_date or fallback_date, rate_cache
            )
            if rate_result is None:
                continue
            rate, observed_date = rate_result
            already_converted = (
                currency == "ZAR"
                and original_currency != "ZAR"
                and self._has_value(row.get("fx_rate_to_zar"))
            )
            if not already_converted:
                standardized_sens_df.at[row_index, "event_value"] = (
                    float(standardized_sens_df.at[row_index, "event_value"]) * rate
                )
            standardized_sens_df.at[row_index, "currency"] = "ZAR"
            if not already_converted:
                standardized_sens_df.at[row_index, "fx_rate_to_zar"] = rate
                standardized_sens_df.at[
                    row_index, "fx_rate_date"
                ] = observed_date

        return standardized_external_df, standardized_sens_df

    def standardize_external_data(
        self,
        external_df: pd.DataFrame,
        sens_df: pd.DataFrame,
        fx_as_of_date=None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Compatibility wrapper using the extraction function's return order."""
        return self.standardize_data(
            external_df, sens_df, fx_as_of_date=fx_as_of_date
        )

    def process_data(
        self,
        source_dir=None,
        fx_as_of_date=None,
        current_sens_data=None,
        current_external_data=None,
        json_location=None,
        process_scope="all",
        return_failures: bool = False,
    ):
        """Incrementally extract, fill, and standardize downloaded data.

        Set ``return_failures`` to receive the failed-scrape keyword dictionary
        as a third return value.
        """
        external_df, sens_df = self.prepare_incremental_data(
            current_sens_data=current_sens_data,
            current_external_data=current_external_data,
            source_dir=source_dir,
            json_location=json_location,
        )
        external_df, sens_df = self.process_new_data(
            current_sens_data=sens_df,
            current_external_data=external_df,
            source_dir=source_dir,
            json_location=json_location,
            process_scope=process_scope,
        )
        validated_external, validated_sens = self.validate_external_data(
            external_df, sens_df
        )
        standardized_external, standardized_sens = self.standardize_data(
            validated_external,
            validated_sens,
            fx_as_of_date=fx_as_of_date,
        )
        self.save_current_data(
            standardized_external,
            standardized_sens,
            json_location=json_location,
        )
        if return_failures:
            return (
                standardized_external,
                standardized_sens,
                self.get_failed_scrape_keywords(),
            )
        return standardized_external, standardized_sens
