import ast
import logging
import math
import re
import time
import unicodedata
import warnings
from numbers import Number
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import yfinance as yf
from pypdf import PdfWriter

from ..config.gemini_structured_schemas import (
    CompanyLevelExtDataCombinationResponse,
    CompanyLevelExtDataResponse,
    SENSEventsResponse,
)
from ..config.prompts import (
    COMPANY_LEVEL_COMBINATION_PROMPT,
    COMPANY_LEVEL_PROMPT,
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
    "share_price": ("currentPrice", "regularMarketPrice"),
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

    def __init__(self):
        self.gemini_client = Gemini_Client()

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

    def extract_external_data_from_pdfs(self, source_dir = Path(__file__).resolve().parents[2] / 'data' / 'downloads') -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Extracts external data from the pdfs in each company directory in the source directory.

        Params:
            source_dir: str - The root source directory. Assumes structure from data_collection.py,
            where there is a SENS subdirectory in ever company's directory. This is set to
            data/downloads by default

        Returns:
            (curr_company_lvl_df, cur_sens_df)
        """

        company_dirs = sorted(
            path for path in Path(source_dir).iterdir() if path.is_dir()
        )
        company_records = []
        sens_records = []

        for company_dir in company_dirs:
            canonical_company = self._canonical_company_name(company_dir.name)
            # Non-SENS documents must be processed independently so that Gemini
            # cannot combine or confuse values from different reporting periods.
            for document_path in sorted(company_dir.glob("*.pdf")):
                curr_company_lvl_json = self._call_gemini_with_retry(
                    CompanyLevelExtDataResponse,
                    COMPANY_LEVEL_PROMPT.format(company=canonical_company),
                    document_path,
                )
                if curr_company_lvl_json is not None:
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

        return curr_company_df, curr_sens_df

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
                    rel_tol=1e-9,
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
        except Exception as error:
            LOGGER.warning(
                "Could not load yfinance fast information for %s: %s",
                ticker_symbol,
                error,
            )

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
        empty strings, and empty collections; supplied mismatches are replaced
        after a warning.
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
                if self._has_value(value) and field in EXTERNAL_MONETARY_FIELDS:
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

    def process_data(self, source_dir=None, fx_as_of_date=None):
        """Run extraction, yfinance validation, and ZAR conversion."""
        if source_dir is None:
            external_df, sens_df = self.extract_external_data_from_pdfs()
        else:
            external_df, sens_df = self.extract_external_data_from_pdfs(source_dir)
        validated_external, validated_sens = self.validate_external_data(
            external_df, sens_df
        )
        standardized_external, standardized_sens = self.standardize_data(
            validated_external,
            validated_sens,
            fx_as_of_date=fx_as_of_date,
        )
        return standardized_external, standardized_sens
