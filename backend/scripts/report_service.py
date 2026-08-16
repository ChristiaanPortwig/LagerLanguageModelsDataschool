"""Persist downloadable client briefing reports and invalidate stale artifacts."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


class ReportService:
    """Create print-ready HTML reports tied to an exact client-data fingerprint."""

    _lock = threading.RLock()

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir).resolve()
        self.reports_dir = self.data_dir / "reports"
        self.manifest_path = self.data_dir / "json" / "report_manifest.json"
        self.relationship_path = self.data_dir / "json" / "relationship_managers.json"
        self.default_relationship_path = (
            Path(__file__).resolve().parents[1] / "config" / "relationship_managers.json"
        )
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)

    def relationship_directory(self) -> dict[str, Any]:
        payload = self._read_json(
            self.relationship_path,
            self._read_json(self.default_relationship_path, {}),
        )
        assignments = payload.get("assignments", {}) if isinstance(payload, dict) else {}
        return {
            "directory_name": payload.get("directory_name", "Relationship directory"),
            "is_mock": bool(payload.get("is_mock", False)),
            "assignments": assignments if isinstance(assignments, dict) else {},
        }

    def relationship_manager(self, entity_id: str) -> dict[str, Any]:
        directory = self.relationship_directory()
        manager = directory["assignments"].get(str(entity_id), {})
        if not isinstance(manager, dict):
            manager = {}
        return {
            "employee_id": manager.get("employee_id"),
            "name": manager.get("name") or "Unassigned",
            "title": manager.get("title") or "Relationship manager",
            "email": manager.get("email"),
            "directory_name": directory["directory_name"],
            "is_mock": directory["is_mock"],
        }

    def enrich_relationship(self, client: dict[str, Any]) -> dict[str, Any]:
        return {
            **client,
            "relationship_manager": self.relationship_manager(client.get("entity_id", "")),
        }

    def status(self, client: dict[str, Any]) -> dict[str, Any]:
        """Return report availability, deleting an artifact whose source data changed."""
        with self._lock:
            entity_id = str(client.get("entity_id", ""))
            manifest = self._manifest()
            entry = manifest.get(entity_id)
            if not isinstance(entry, dict):
                return self._empty_status(entity_id)
            path = self.reports_dir / str(entry.get("filename", ""))
            current_fingerprint = self.source_fingerprint(client)
            if (
                not path.is_file()
                or entry.get("source_fingerprint") != current_fingerprint
            ):
                self._delete_entry(entity_id, manifest, path)
                return self._empty_status(entity_id)
            return {
                "available": True,
                "generated_at": entry.get("generated_at"),
                "filename": path.name,
                "download_url": f"/api/clients/{entity_id}/report/download",
            }

    def generate(self, client: dict[str, Any], narrative: str) -> dict[str, Any]:
        with self._lock:
            entity_id = str(client["entity_id"])
            generated_at = datetime.now(timezone.utc).isoformat()
            filename = self._filename(client)
            target = self.reports_dir / filename
            report_html = self._render_report(client, narrative, generated_at)
            self._atomic_text(target, report_html)

            manifest = self._manifest()
            old_entry = manifest.get(entity_id)
            if isinstance(old_entry, dict):
                old_path = self.reports_dir / str(old_entry.get("filename", ""))
                if old_path != target and old_path.is_file():
                    old_path.unlink()
            manifest[entity_id] = {
                "filename": filename,
                "generated_at": generated_at,
                "source_fingerprint": self.source_fingerprint(client),
            }
            self._write_manifest(manifest)
            return self.status(client)

    def download_path(self, client: dict[str, Any]) -> Path | None:
        status = self.status(client)
        if not status["available"]:
            return None
        return self.reports_dir / status["filename"]

    def invalidate_stale(self, clients: list[dict[str, Any]]) -> list[str]:
        """Delete reports invalidated by newly aggregated client or manager data."""
        invalidated = []
        for client in clients:
            enriched = self.enrich_relationship(client)
            entity_id = str(enriched.get("entity_id", ""))
            manifest = self._manifest()
            existed = entity_id in manifest
            status = self.status(enriched)
            if existed and not status["available"]:
                invalidated.append(entity_id)
        return invalidated

    @staticmethod
    def source_fingerprint(client: dict[str, Any]) -> str:
        source = {
            key: value
            for key, value in client.items()
            if key not in {"report"}
        }
        canonical = json.dumps(
            source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _render_report(
        self,
        client: dict[str, Any],
        narrative: str,
        generated_at: str,
    ) -> str:
        manager = client.get("relationship_manager", {})
        paragraphs = [
            f"<p>{html.escape(paragraph.strip())}</p>"
            for paragraph in re.split(r"\n\s*\n", narrative)
            if paragraph.strip()
        ]
        timing = client.get("timing_intelligence", {}) or {}
        payment = timing.get("payment_timing", {}) or {}
        engagement = timing.get("engagement_prediction", {}) or {}
        relationship_note = "Mock relationship directory" if manager.get("is_mock") else "Internal relationship directory"
        formula_page = self._render_formula_page(client)
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(client['entity_name'])} briefing report</title>
<style>
  @page {{ size: A4; margin: 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; color: #111827; font: 14px/1.55 Arial, sans-serif; background: #eef2f6; }}
  .page {{ width: 210mm; min-height: 297mm; margin: 16px auto; padding: 18mm; background: white; page-break-after: always; }}
  .page:last-child {{ page-break-after: auto; }}
  .brand {{ color: #005199; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }}
  h1 {{ margin: 8px 0 4px; font-size: 28px; }}
  h2 {{ margin: 26px 0 10px; color: #005199; font-size: 18px; }}
  h3 {{ margin: 18px 0 7px; font-size: 14px; }}
  .muted {{ color: #667085; }}
  .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin: 20px 0; }}
  .card {{ padding: 12px; border: 1px solid #d8dee8; border-radius: 6px; }}
  .label {{ color: #667085; font-size: 11px; text-transform: uppercase; }}
  .value {{ margin-top: 3px; font-size: 16px; font-weight: 700; }}
  .narrative {{ padding: 16px; border-left: 4px solid #005199; background: #f2f7fb; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  th, td {{ padding: 7px; border: 1px solid #d8dee8; text-align: left; vertical-align: top; }}
  th {{ background: #f2f4f7; }}
  code {{ color: #344054; white-space: normal; word-break: break-word; }}
  footer {{ margin-top: 28px; color: #667085; font-size: 10px; }}
  @media print {{ body {{ background: white; }} .page {{ margin: 0; box-shadow: none; }} }}
</style>
</head>
<body>
<section class="page">
  <div class="brand">Syn Bank · Client briefing</div>
  <h1>{html.escape(client['entity_name'])}</h1>
  <div class="muted">{html.escape(str(client.get('sector', '')))} · {html.escape(str(client.get('entity_id', '')))}</div>
  <div class="grid">
    <div class="card"><div class="label">Relationship manager</div><div class="value">{html.escape(str(manager.get('name', 'Unassigned')))}</div><div class="muted">{html.escape(str(manager.get('title', '')))} · {html.escape(str(manager.get('email') or 'No email recorded'))}</div></div>
    <div class="card"><div class="label">Opportunity score</div><div class="value">{self._number(client.get('opportunity_score'), 1)}</div></div>
    <div class="card"><div class="label">Estimated wallet</div><div class="value">{self._zar(client.get('estimated_total_wallet_zar'))}</div></div>
    <div class="card"><div class="label">Wallet gap</div><div class="value">{self._zar(client.get('wallet_gap_zar'))}</div></div>
    <div class="card"><div class="label">Next predicted payment</div><div class="value">{html.escape(str(payment.get('predicted_payment_date') or 'Not available'))}</div></div>
    <div class="card"><div class="label">Recommended engagement</div><div class="value">{html.escape('Engage now' if engagement.get('engage_now') else str(engagement.get('recommended_engagement_date') or 'Not available'))}</div></div>
  </div>
  <h2>Gemini briefing</h2>
  <div class="narrative">{''.join(paragraphs)}</div>
  <h2>Recommended coverage action</h2>
  <p>{html.escape(str(engagement.get('recommended_action') or 'Use the latest client evidence to plan proactive engagement.'))}</p>
  <footer>Generated {html.escape(generated_at)} · {html.escape(relationship_note)} · Confidential</footer>
</section>
{formula_page}
</body>
</html>
"""

    def _render_formula_page(self, client: dict[str, Any]) -> str:
        wallet = client.get("wallet_calculation", {}) or {}
        score = client.get("score_calculation", {}) or {}
        weights = score.get("weights", {}) or {}
        pillar_rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(name).replace('_', ' ').title())}</td>"
            f"<td><code>{html.escape(str(detail.get('formula') or 'Not available'))}</code></td>"
            f"<td>{self._zar(detail.get('value'))}</td>"
            "</tr>"
            for name, detail in (wallet.get("pillars", {}) or {}).items()
        )
        product_rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(name).replace('_', ' ').title())}</td>"
            f"<td>{html.escape(str(detail.get('tier') or 'Unavailable'))}</td>"
            f"<td><code>{html.escape(str(detail.get('formula') or 'Missing required inputs'))}</code></td>"
            f"<td>{html.escape(', '.join(str(key).replace('_', ' ') for key in (detail.get('inputs', {}) or {})) or '—')}</td>"
            f"<td>{self._zar(detail.get('value'))}</td>"
            "</tr>"
            for name, detail in (wallet.get("products", {}) or {}).items()
        )
        return f"""<section class="page">
  <div class="brand">Syn Bank · Methodology appendix</div>
  <h1>Formulas used</h1>
  <p class="muted">Auditable formulas and inputs used for this client report.</p>
  <h2>Opportunity score</h2>
  <p><code>{html.escape(str(score.get('formula') or 'Not available'))}</code></p>
  <p>Gap weight: {self._number(weights.get('gap_weight'), 2)} · SENS weight: {self._number(weights.get('sens_weight'), 2)} · Relationship weight: {self._number(weights.get('relationship_weight'), 2)}</p>
  <h2>Wallet pillars</h2>
  <table><thead><tr><th>Pillar</th><th>Formula</th><th>Result</th></tr></thead><tbody>{pillar_rows or '<tr><td colspan="3">No pillar formulas available.</td></tr>'}</tbody></table>
  <h2>Product formulas</h2>
  <table><thead><tr><th>Product</th><th>Tier</th><th>Formula</th><th>Inputs</th><th>Result</th></tr></thead><tbody>{product_rows or '<tr><td colspan="5">No product formulas available.</td></tr>'}</tbody></table>
  <footer>Formula appendix for {html.escape(str(client.get('entity_name', '')))} · Confidential</footer>
</section>"""

    def _delete_entry(self, entity_id: str, manifest: dict, path: Path) -> None:
        if path.is_file() and path.parent == self.reports_dir:
            path.unlink()
        manifest.pop(entity_id, None)
        self._write_manifest(manifest)

    def _manifest(self) -> dict[str, Any]:
        payload = self._read_json(self.manifest_path, {})
        return payload if isinstance(payload, dict) else {}

    def _write_manifest(self, payload: dict[str, Any]) -> None:
        self._atomic_text(
            self.manifest_path,
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        )

    @staticmethod
    def _read_json(path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _atomic_text(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            output.write(value)
            temporary = Path(output.name)
        os.replace(temporary, path)

    @staticmethod
    def _filename(client: dict[str, Any]) -> str:
        entity_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(client["entity_id"]))
        company = re.sub(r"[^A-Za-z0-9_-]+", "_", str(client["entity_name"])).strip("_")
        return f"{entity_id}-{company}-briefing.html"

    @staticmethod
    def _empty_status(entity_id: str) -> dict[str, Any]:
        return {
            "available": False,
            "generated_at": None,
            "filename": None,
            "download_url": f"/api/clients/{entity_id}/report/download",
        }

    @staticmethod
    def _number(value, decimals: int) -> str:
        try:
            return f"{float(value):,.{decimals}f}"
        except (TypeError, ValueError):
            return "Not available"

    @classmethod
    def _zar(cls, value) -> str:
        number = cls._number(value, 0)
        return "Not available" if number == "Not available" else f"R{number}"
