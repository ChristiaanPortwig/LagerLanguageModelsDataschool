"""Application-facing orchestration for collection, processing and aggregation."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from backend.scripts.calculate_client_score import calculate_client_score
from backend.scripts.data_aggregation import (
    build_client_wallet_baseline,
    convert_client_table_to_dashboard_schema,
    derive_opportunity_flags,
    find_cross_ledger_overlaps,
    save_dashboard_clients_to_json,
)
from backend.scripts.data_collection import DataCollector
from backend.scripts.data_processing import Data_Processor
from backend.scripts.payment_cycles_timing import build_client_timing_intelligence
from backend.scripts.wallet_size import calculate_total_wallet_size


LOGGER = logging.getLogger(__name__)
PILLARS = (
    "transactional_banking",
    "global_markets",
    "investment_banking",
)
SCORE_COLUMNS = tuple(f"{pillar}_opportunity_score" for pillar in PILLARS)
DEFAULT_SCORE_WEIGHTS = {
    "gap_weight": 0.50,
    "sens_weight": 0.40,
    "relationship_weight": 0.10,
}
DEFAULT_SENS_HALF_LIFE_DAYS = 90.0


class PipelineBusyError(RuntimeError):
    """Raised when another pipeline or manual update is already running."""


class PipelineService:
    """Run every data mutation through one lock and one atomic output writer."""

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(
            data_dir
            or os.getenv("APP_DATA_DIR")
            or Path(__file__).resolve().parents[2] / "data"
        ).resolve()
        self.json_dir = self.data_dir / "json"
        self.downloads_dir = self.data_dir / "downloads"
        self.client_path = self.data_dir / "client_data.json"
        self.status_path = self.json_dir / "pipeline_status.json"
        self.details_path = self.json_dir / "calculation_details.json"
        self.timing_path = self.json_dir / "client_timing_intelligence.json"
        self.baseline_path = self.json_dir / "client_baseline.json"
        self.config_path = self.json_dir / "pipeline_config.json"
        self._lock = threading.Lock()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.json_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        payload = self._read_json(self.status_path, {})
        return {
            "state": "idle",
            "last_started_at": None,
            "last_completed_at": None,
            "last_scope": None,
            "new_documents": [],
            "document_issues": [],
            "processing_failures": {},
            "sens_scoring": {
                "state": "not_required",
                "rows_submitted": 0,
                "rows_remaining": 0,
            },
            "error": None,
            **(payload if isinstance(payload, dict) else {}),
            "running": self._lock.locked(),
        }

    def run(self, scope: str = "sens", *, scrape: bool = True) -> dict[str, Any]:
        if scope not in {"sens", "all"}:
            raise ValueError("scope must be either 'sens' or 'all'")
        if not self._lock.acquire(blocking=False):
            raise PipelineBusyError("A pipeline update is already running")

        started = self._now()
        status = {
            **self.status(),
            "state": "running",
            "last_started_at": started,
            "last_scope": scope,
            "processing_failures": {},
            "sens_scoring": {
                "state": "not_required",
                "rows_submitted": 0,
                "rows_remaining": 0,
            },
            "error": None,
        }
        self._write_json(self.status_path, status)
        try:
            if scrape and not os.getenv("GEMINI_API_KEY"):
                status["sens_scoring"]["state"] = "failed"
                raise RuntimeError(
                    "GEMINI_API_KEY is required before scraping because newly "
                    "collected SENS documents must be processed immediately"
                )
            collector = DataCollector()
            processor = Data_Processor()
            external, sens = processor.prepare_incremental_data(
                source_dir=self.downloads_dir,
                json_location=self.json_dir,
            )
            document_issues = []
            if scrape:
                collection_result = collector.collect_data(
                    scrape_scope=scope,
                    save_location=self.downloads_dir,
                )
                if scope == "all" and isinstance(collection_result, list):
                    document_issues = collection_result

            external, sens, failures = processor.process_new_data(
                current_sens_data=sens,
                current_external_data=external,
                source_dir=self.downloads_dir,
                json_location=self.json_dir,
                process_scope=scope,
                return_failures=True,
            )
            status["processing_failures"] = failures
            failed_sens_companies = sorted(
                company
                for company, keywords in failures.items()
                if any(str(keyword).casefold() == "sens" for keyword in keywords)
            )
            if failed_sens_companies:
                status["sens_scoring"]["state"] = "failed"
                raise RuntimeError(
                    "Gemini SENS extraction failed for: "
                    + ", ".join(failed_sens_companies)
                )

            # Score SENS immediately after extraction. Do not proceed to
            # standardisation, aggregation, or frontend publication until
            # every event has all three Gemini opportunity scores.
            unscored_sens_rows = self._unscored_sens_row_count(sens)
            if unscored_sens_rows and not os.getenv("GEMINI_API_KEY"):
                status["sens_scoring"]["state"] = "failed"
                raise RuntimeError(
                    f"{unscored_sens_rows} SENS rows require Gemini scoring, but "
                    "GEMINI_API_KEY is not configured"
                )
            if unscored_sens_rows:
                status["sens_scoring"] = {
                    "state": "running",
                    "rows_submitted": unscored_sens_rows,
                    "rows_remaining": unscored_sens_rows,
                }
                self._write_json(self.status_path, status)
                sens = processor.score_sens_opportunities(sens)
                remaining_sens_rows = self._unscored_sens_row_count(sens)
                if remaining_sens_rows:
                    raise RuntimeError(
                        "Gemini SENS scoring was incomplete: "
                        f"{remaining_sens_rows} of {unscored_sens_rows} submitted rows "
                        "still have missing opportunity scores"
                    )
            status["sens_scoring"] = {
                "state": "complete",
                "rows_submitted": unscored_sens_rows,
                "rows_remaining": 0,
            }
            processed_paths = sorted(
                str(path)
                for paths in processor.last_extraction_status.values()
                for path in paths
            )

            # Standardisation is idempotent once the FX audit columns exist. It
            # also repairs older checkpoints created before those columns were
            # introduced.
            if processed_paths or not self._is_standardized(external, sens):
                external, sens = processor.validate_external_data(external, sens)
                external, sens = processor.standardize_data(external, sens)

            processor.save_current_data(external, sens, json_location=self.json_dir)
            records = self.aggregate(external, sens)

            status.update({
                "state": "idle",
                "last_completed_at": self._now(),
                "new_documents": processed_paths,
                "new_data_found": bool(processed_paths),
                "document_issues": document_issues,
                "processing_failures": failures,
                "client_count": len(records),
            })
            self._write_json(self.status_path, status)
            return status
        except Exception as error:
            LOGGER.exception("Pipeline run failed")
            if status.get("sens_scoring", {}).get("state") == "running":
                status["sens_scoring"] = {
                    **status["sens_scoring"],
                    "state": "failed",
                }
            status.update({
                "state": "failed",
                "last_completed_at": self._now(),
                "error": str(error),
            })
            self._write_json(self.status_path, status)
            raise
        finally:
            self._lock.release()

    def aggregate(
        self,
        external: pd.DataFrame | None = None,
        sens: pd.DataFrame | None = None,
    ) -> list[dict[str, Any]]:
        """Rebuild ``client_data.json`` and its audit sidecar."""
        processor = Data_Processor()
        if external is None:
            external = processor._read_dataframe(
                self.json_dir / processor.EXTERNAL_DATA_FILE
            )
        if sens is None:
            sens = processor._read_dataframe(self.json_dir / processor.SENS_DATA_FILE)
        if external.empty:
            raise ValueError("No processed company data is available")

        baseline = self._load_or_build_baseline()
        wallet, details, missing = self._calculate_wallet(external, sens)
        decayed_sens = self._decayed_sens_for_scoring(processor, sens)
        weights = self.score_weights()
        scores = calculate_client_score(
            baseline,
            decayed_sens,
            wallet,
            **weights,
        )
        merged = baseline.merge(
            wallet.reset_index(),
            left_on="entity_name",
            right_on="company",
            how="left",
        ).merge(
            scores.drop(columns=["entity_name"], errors="ignore"),
            on="entity_id",
            how="left",
        )
        records = convert_client_table_to_dashboard_schema(
            merged,
            calculation_details=details,
            missing_data=missing,
            score_weights=weights,
            opportunity_flags=derive_opportunity_flags(
                baseline,
                external,
                sens,
            ),
        )
        timing_payload = self.timing_intelligence()
        timing_by_entity = {
            str(item.get("entity_id")): item
            for item in timing_payload.get("clients", [])
        }
        for record in records:
            record["timing_intelligence"] = timing_by_entity.get(record["entity_id"])
        save_dashboard_clients_to_json(records, self.client_path)
        self._write_json(
            self.details_path,
            {
                "generated_at": self._now(),
                "score_weights": weights,
                "wallet": details,
                "missing_data_keywords": missing,
                "timing_generated_at": timing_payload.get("generated_at"),
            },
        )
        return records

    def timing_intelligence(
        self,
        *,
        force: bool = False,
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        """Return cached timing intelligence, refreshing when a contact date arrives."""
        reference = pd.Timestamp(reference_date or self._business_date()).normalize()
        signature = self._ledger_signature()
        gemini_requested = bool(os.getenv("GEMINI_API_KEY"))
        cached = self._read_json(self.timing_path, {})
        cache_matches = (
            isinstance(cached, dict)
            and cached.get("source_signature") == signature
            and cached.get("gemini_requested") == gemini_requested
            and isinstance(cached.get("clients"), list)
            and bool(cached.get("clients"))
        )
        if cache_matches and not force and not self._timing_refresh_due(cached, reference):
            return cached

        records = build_client_timing_intelligence(
            self.data_dir,
            reference_date=reference,
        )
        eligible = [
            item for item in records
            if item.get("payment_timing", {}).get("predicted_payment_date")
        ]
        gemini_count = sum(
            item.get("engagement_prediction", {}).get("generated_by") == "gemini"
            for item in eligible
        )
        if not eligible:
            prediction_mode = "not_applicable"
        elif gemini_count == len(eligible):
            prediction_mode = "gemini"
        elif gemini_count:
            prediction_mode = "gemini_partial"
        else:
            prediction_mode = "rules_fallback"
        payload = {
            "generated_at": self._now(),
            "generated_for_date": reference.date().isoformat(),
            "prediction_mode": prediction_mode,
            "gemini_requested": gemini_requested,
            "source_signature": signature,
            "clients": records,
        }
        self._write_json(self.timing_path, payload)
        return payload

    @staticmethod
    def _timing_refresh_due(payload: dict[str, Any], reference: pd.Timestamp) -> bool:
        """Refresh once per date when a cached engagement or payment date is reached."""
        generated_for = pd.to_datetime(payload.get("generated_for_date"), errors="coerce")
        if not pd.isna(generated_for) and generated_for.normalize() >= reference:
            return False
        for client in payload.get("clients", []):
            engagement = client.get("engagement_prediction", {}).get(
                "recommended_engagement_date"
            )
            payment = client.get("payment_timing", {}).get("predicted_payment_date")
            for candidate in (engagement, payment):
                parsed = pd.to_datetime(candidate, errors="coerce")
                if not pd.isna(parsed) and parsed.normalize() <= reference:
                    return True
        return False

    @staticmethod
    def _business_date():
        timezone_name = os.getenv("TIMING_TIMEZONE", "Africa/Johannesburg")
        try:
            business_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            business_timezone = timezone.utc
        return datetime.now(business_timezone).date()

    def missing_data(self) -> dict[str, Any]:
        details = self._read_json(self.details_path, {})
        clients = self._read_json(self.client_path, [])
        return {
            "documents": self._missing_documents(),
            "wallet_fields": [
                {
                    "entity_id": client.get("entity_id"),
                    "company": client.get("entity_name"),
                    **client.get("missing_data", {}),
                }
                for client in clients
                if client.get("missing_data", {}).get("fields")
            ],
            "last_pipeline_issues": self.status().get("document_issues", []),
            "sens_scoring": self.status().get("sens_scoring", {}),
            "generated_at": details.get("generated_at"),
        }

    @staticmethod
    def _unscored_sens_row_count(sens: pd.DataFrame) -> int:
        if not isinstance(sens, pd.DataFrame) or sens.empty:
            return 0
        missing = pd.Series(False, index=sens.index)
        for column in SCORE_COLUMNS:
            if column not in sens:
                return len(sens)
            missing |= pd.to_numeric(sens[column], errors="coerce").isna()
        return int(missing.sum())

    def update_external_fields(self, company: str, values: dict[str, Any]) -> list:
        if not values:
            raise ValueError("values must contain at least one field")
        if not self._lock.acquire(blocking=False):
            raise PipelineBusyError("A pipeline update is already running")
        try:
            processor = Data_Processor()
            external_path = self.json_dir / processor.EXTERNAL_DATA_FILE
            external = processor._read_dataframe(external_path)
            sens = processor._read_dataframe(self.json_dir / processor.SENS_DATA_FILE)
            if "company" not in external:
                raise ValueError("Processed company data has no company column")
            mask = external["company"].astype(str).str.casefold() == company.casefold()
            if not mask.any():
                raise KeyError(company)
            row_index = external.loc[mask].index[-1]
            protected = {
                "company", "report_date", "reporting_currency", "reporting_unit",
                "source_document", "original_currency", "fx_rate_to_zar", "fx_rate_date",
            }
            invalid = sorted(protected.intersection(values))
            if invalid:
                raise ValueError("Cannot update protected fields: " + ", ".join(invalid))
            for field, value in values.items():
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or float(value) < 0
                ):
                    raise ValueError(f"{field} must be a non-negative finite number or null")
                if field not in external.columns:
                    external[field] = pd.NA
                external.at[row_index, field] = value
            processor.save_current_data(external, sens, json_location=self.json_dir)
            return self.aggregate(external, sens)
        finally:
            self._lock.release()

    def update_opportunity_scores(
        self, record_id: str, values: dict[str, float]
    ) -> list:
        if not values:
            raise ValueError("At least one opportunity score is required")
        unknown = sorted(set(values).difference(SCORE_COLUMNS))
        if unknown:
            raise ValueError("Unknown score fields: " + ", ".join(unknown))
        if not self._lock.acquire(blocking=False):
            raise PipelineBusyError("A pipeline update is already running")
        try:
            processor = Data_Processor()
            external = processor._read_dataframe(
                self.json_dir / processor.EXTERNAL_DATA_FILE
            )
            sens = processor._read_dataframe(self.json_dir / processor.SENS_DATA_FILE)
            matches = [
                index for index, row in sens.iterrows()
                if self.opportunity_record_id(row) == record_id
            ]
            if not matches:
                raise KeyError(record_id)
            for field, value in values.items():
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or not 0 <= float(value) <= 1
                ):
                    raise ValueError(f"{field} must be between 0 and 1")
                if field not in sens.columns:
                    sens[field] = pd.NA
                sens.loc[matches, field] = float(value)
            processor.save_current_data(external, sens, json_location=self.json_dir)
            return self.aggregate(external, sens)
        finally:
            self._lock.release()

    def update_scoring_settings(self, values: dict[str, float]) -> list:
        if not self._lock.acquire(blocking=False):
            raise PipelineBusyError("A pipeline update is already running")
        try:
            valid_settings = {*DEFAULT_SCORE_WEIGHTS, "sens_half_life_days"}
            unknown = sorted(set(values).difference(valid_settings))
            if unknown:
                raise ValueError("Unknown scoring settings: " + ", ".join(unknown))
            weight_updates = {
                key: value for key, value in values.items() if key in DEFAULT_SCORE_WEIGHTS
            }
            weights = {**self.score_weights(), **weight_updates}
            if set(weights) != set(DEFAULT_SCORE_WEIGHTS):
                raise ValueError(
                    "Only gap_weight, sens_weight and relationship_weight are valid"
                )
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
                for value in weights.values()
            ) or not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
                raise ValueError("Scoring weights must be non-negative and sum to 1")

            half_life_days = values.get(
                "sens_half_life_days", self.sens_half_life_days()
            )
            if (
                isinstance(half_life_days, bool)
                or not isinstance(half_life_days, (int, float))
                or not math.isfinite(float(half_life_days))
                or float(half_life_days) <= 0
            ):
                raise ValueError("sens_half_life_days must be a positive finite number")

            self._write_json(
                self.config_path,
                {
                    "score_weights": weights,
                    "sens_half_life_days": float(half_life_days),
                },
            )
            return self.aggregate()
        finally:
            self._lock.release()

    def update_score_weights(self, values: dict[str, float]) -> list:
        """Backward-compatible wrapper for callers that only update weights."""
        return self.update_scoring_settings(values)

    def score_weights(self) -> dict[str, float]:
        config = self._read_json(self.config_path, {})
        return {**DEFAULT_SCORE_WEIGHTS, **config.get("score_weights", {})}

    def sens_half_life_days(self) -> float:
        config = self._read_json(self.config_path, {})
        return float(config.get("sens_half_life_days", DEFAULT_SENS_HALF_LIFE_DAYS))

    def formulas(self) -> dict[str, Any]:
        return {
            "score_weights": self.score_weights(),
            "opportunity_pillar": (
                "gap_weight * normalized_wallet_gap + sens_weight * "
                "normalized_decayed_sens + relationship_weight * "
                "percentile_rank(current_wallet_share)"
            ),
            "opportunity_total": (
                "sum(pillar_wallet_gap * pillar_score) / sum(pillar_wallet_gap)"
            ),
            "sens_decay": "score * 2 ** (-age_days / half_life_days)",
            "sens_half_life_days": self.sens_half_life_days(),
            "wallet": self._read_json(self.details_path, {}).get("wallet", {}),
        }

    @classmethod
    def opportunity_record_id(cls, row: pd.Series | dict) -> str:
        parts = [
            str(row.get(field, ""))
            for field in ("company", "announcement_date", "title", "source_document")
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]

    def _calculate_wallet(self, external, sens):
        try:
            return calculate_total_wallet_size(
                external,
                sens,
                return_calculation_details=True,
                return_missing_data=True,
            )
        except ValueError as error:
            if "currency" not in str(error):
                raise
            LOGGER.warning(
                "SENS currency data is not standardized; excluding events from "
                "wallet arithmetic until the next successful processing run"
            )
            return calculate_total_wallet_size(
                external,
                return_calculation_details=True,
                return_missing_data=True,
            )

    def _decayed_sens_for_scoring(self, processor, sens):
        scored = sens.copy(deep=True)
        if "company" not in scored:
            scored["company"] = pd.Series(dtype=object)
        if "announcement_date" not in scored:
            scored["announcement_date"] = pd.Series(dtype=object)
        for column in SCORE_COLUMNS:
            if column not in scored:
                scored[column] = 0.0
            scored[column] = pd.to_numeric(scored[column], errors="coerce").fillna(0.0)
        return processor.apply_sens_score_decay(
            scored, half_life_days=self.sens_half_life_days()
        )

    def _load_or_build_baseline(self) -> pd.DataFrame:
        signature = self._ledger_signature()
        cached = self._read_json(self.baseline_path, {})
        cached_records = cached.get("records")
        if cached.get("source_signature") == signature and cached_records:
            cached_frame = pd.DataFrame(cached_records)
            required_flag_columns = {
                "cross_border_outbound_total_zar",
                "import_trade_finance_total_zar",
            }
            if required_flag_columns.issubset(cached_frame.columns):
                return cached_frame

        # Existing dashboard data is an exact persisted projection of the
        # baseline and avoids loading multi-gigabyte ledgers on first upgrade.
        existing = self._read_json(self.client_path, [])
        has_flag_inputs = bool(existing) and all(
            "cross_border_outbound_total_zar" in row
            and "import_trade_finance_total_zar" in row
            for row in existing
        )
        baseline = self._baseline_from_dashboard(existing) if has_flag_inputs else pd.DataFrame()
        if baseline.empty:
            required = [
                self.data_dir / "transactional_banking.csv",
                self.data_dir / "cross_border_payments.csv",
                self.data_dir / "trade_finance.csv",
            ]
            missing = [str(path) for path in required if not path.exists()]
            if missing:
                raise FileNotFoundError("Missing ledger files: " + ", ".join(missing))
            transactional = pd.read_csv(required[0])
            cross_border = pd.read_csv(required[1])
            trade_finance = pd.read_csv(required[2])
            overlap = find_cross_ledger_overlaps(
                cross_border, transactional, day_tolerance=3,
                amount_tolerance_pct=2,
            )
            baseline = build_client_wallet_baseline(
                transactional, cross_border, trade_finance, overlap
            )
        self._write_json(
            self.baseline_path,
            {"source_signature": signature, "records": self._records(baseline)},
        )
        return baseline

    @staticmethod
    def _baseline_from_dashboard(records) -> pd.DataFrame:
        if not isinstance(records, list) or not records:
            return pd.DataFrame()
        output = []
        for row in records:
            aliases = {
                "txn_banking_total_zar": ("syn_txn_banking_total_zar", "syn_txt_banking_total_zar"),
                "cross_border_total_zar": ("syn_global_markets_total_zar",),
                "trade_finance_total_zar": ("syn_trade_finance_total_zar", "syn_trade_finace_total_zar"),
                "lending_signal_total_zar": ("syn_lending_ib_total_zar",),
                "cross_border_outbound_total_zar": ("cross_border_outbound_total_zar",),
                "import_trade_finance_total_zar": ("import_trade_finance_total_zar",),
            }
            values = {}
            for target, sources in aliases.items():
                values[target] = next(
                    (row.get(source) for source in sources if row.get(source) is not None),
                    0.0,
                )
            if not all(row.get(key) for key in ("entity_id", "entity_name", "sector")):
                continue
            output.append({
                "entity_id": row["entity_id"],
                "entity_name": row["entity_name"],
                "sector": row["sector"],
                **values,
                "lending_signal_txn_count": 0,
                "syn_bank_observed_total_zar": sum(
                    values[key]
                    for key in (
                        "txn_banking_total_zar",
                        "cross_border_total_zar",
                        "trade_finance_total_zar",
                        "lending_signal_total_zar",
                    )
                ),
            })
        return pd.DataFrame(output)

    def _ledger_signature(self):
        return {
            path.name: {"size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}
            for path in (
                self.data_dir / "transactional_banking.csv",
                self.data_dir / "cross_border_payments.csv",
                self.data_dir / "trade_finance.csv",
            )
            if path.exists()
        }

    def _missing_opportunity_scores(self):
        sens = Data_Processor._read_dataframe(
            self.json_dir / Data_Processor.SENS_DATA_FILE
        )
        missing_by_id = {}
        for _, row in sens.iterrows():
            fields = [
                column for column in SCORE_COLUMNS
                if column not in sens.columns or pd.isna(row.get(column))
            ]
            if fields:
                record_id = self.opportunity_record_id(row)
                record = missing_by_id.setdefault(record_id, {
                    "record_id": record_id,
                    "company": row.get("company"),
                    "announcement_date": self._json_scalar(row.get("announcement_date")),
                    "title": row.get("title"),
                    "missing_fields": set(),
                })
                record["missing_fields"].update(fields)
        return [
            {**record, "missing_fields": sorted(record["missing_fields"])}
            for record in missing_by_id.values()
        ]

    def _missing_documents(self):
        current_year = datetime.now(timezone.utc).year
        output = []
        for company in DataCollector.INVESTOR_URLS:
            folder = self.downloads_dir / re.sub(r"[^A-Za-z0-9]+", "_", company).strip("_")
            names = [path.name.casefold() for path in folder.glob("*.pdf")] if folder.exists() else []
            for document_type in DataCollector.KEYWORDS:
                token = document_type.casefold()
                recent = any(
                    name.startswith(token + "__")
                    and any(str(year) in name for year in (current_year, current_year - 1))
                    for name in names
                )
                if not recent:
                    output.append({
                        "company": company,
                        "document_type": document_type,
                        "reason": "No current or previous-year PDF is present",
                    })
        return output

    @staticmethod
    def _is_standardized(external, sens):
        external_ok = external.empty or (
            "reporting_currency" in external
            and external["reporting_currency"].dropna().astype(str).str.upper().eq("ZAR").all()
        )
        sens_ok = sens.empty or (
            "currency" in sens
            and sens.loc[sens.get("event_value", pd.Series(index=sens.index)).notna(), "currency"]
            .dropna().astype(str).str.upper().eq("ZAR").all()
        )
        return external_ok and sens_ok

    @staticmethod
    def _records(dataframe):
        return json.loads(dataframe.to_json(orient="records", date_format="iso"))

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _json_scalar(value):
        if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if hasattr(value, "item"):
            return value.item()
        return value

    @staticmethod
    def _read_json(path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _write_json(path: Path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        os.replace(temporary, path)
