"""Load normalized Markdown filings from data/markdown into source_documents."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import SourceDocument

# Params: edit these, then run `uv run python -m ingest.load_source_documents`
MARKDOWN_DIR = Path(__file__).resolve().parents[2] / "data" / "markdown"
SKIP_EXISTING = True

COMPANY_NAMES = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation",
    "AMZN": "Amazon.com, Inc.",
    "GOOGL": "Alphabet Inc.",
}


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def parse_datetime_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value).date()


def fiscal_year_from_report_date(report_date: str | None) -> int | None:
    if not report_date:
        return None
    return int(report_date[:4])


def fallback_filing_date(manifest: dict, filing: dict) -> date:
    explicit_filing_date = parse_date(filing.get("filing_date"))
    if explicit_filing_date:
        return explicit_filing_date

    report_date = parse_date(filing.get("report_date"))
    if report_date:
        return report_date

    converted_at = parse_datetime_date(manifest.get("converted_at_utc"))
    if converted_at:
        return converted_at

    generated_at = parse_datetime_date(manifest.get("generated_at_utc"))
    if generated_at:
        return generated_at

    return datetime.now(UTC).date()


def normalize_source_document_fields(
    manifest: dict, filing: dict, markdown_text: str
) -> dict:
    manifest_source = str(manifest.get("source", "")).upper()
    source_local_path = filing.get("source_local_path") or filing.get("local_path", "")

    accession_number = (
        filing.get("accession_number")
        or filing.get("legal_act_id")
        or Path(source_local_path).stem
    )
    if not accession_number:
        raise ValueError("Missing accession identifier in manifest record")

    ticker = filing.get("ticker")
    if not ticker:
        ticker = "LTLAW" if "E-TAR" in manifest_source else "UNKNOWN"

    cik = filing.get("cik")
    if not cik:
        cik = "0000000000"

    company_name = filing.get("company_name") or COMPANY_NAMES.get(ticker)

    form = filing.get("form") or manifest.get("form") or "UNKNOWN"
    if len(form) > 16:
        form = form[:16]

    source_url = filing.get("source_url") or filing.get("asr_source_url") or "unknown"

    primary_document = (
        filing.get("primary_document")
        or filing.get("legal_act_id")
        or Path(source_local_path).name
        or accession_number
    )

    report_date = parse_date(filing.get("report_date"))
    filing_date = fallback_filing_date(manifest, filing)

    return {
        "ticker": ticker,
        "cik": cik,
        "company_name": company_name,
        "form": form,
        "filing_date": filing_date,
        "report_date": report_date,
        "fiscal_year": fiscal_year_from_report_date(filing.get("report_date")),
        "accession_number": accession_number,
        "primary_document": primary_document,
        "source_url": source_url,
        "markdown_content": markdown_text,
        "ingested_at": datetime.now(UTC),
    }


def load_source_documents() -> dict[str, int]:
    manifest_path = MARKDOWN_DIR / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Missing {manifest_path}. Run `uv run data/convert_to_markdown.py` first."
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    filings = manifest.get("filings", [])
    if not filings:
        raise ValueError(f"No filings listed in {manifest_path}")

    engine = create_engine(settings.sqlalchemy_database_url)
    counts = {"inserted": 0, "skipped": 0, "updated": 0}

    with Session(engine) as session:
        for filing in filings:
            accession_number = (
                filing.get("accession_number")
                or filing.get("legal_act_id")
                or Path(filing.get("local_path", "")).stem
            )
            if not accession_number:
                raise ValueError("Manifest record is missing accession identifier")

            existing = session.scalar(
                select(SourceDocument).where(
                    SourceDocument.accession_number == accession_number
                )
            )

            if existing and SKIP_EXISTING:
                print(f"Skipping existing {accession_number}")
                counts["skipped"] += 1
                continue

            markdown_path = MARKDOWN_DIR / filing["local_path"]
            if not markdown_path.is_file():
                raise FileNotFoundError(f"Missing Markdown file: {markdown_path}")

            markdown_text = markdown_path.read_text(encoding="utf-8")
            fields = normalize_source_document_fields(manifest, filing, markdown_text)

            if existing:
                print(f"Updating {accession_number}...")
                for key, value in fields.items():
                    setattr(existing, key, value)
                counts["updated"] += 1
            else:
                print(f"Inserting {accession_number}...")
                session.add(SourceDocument(**fields))
                counts["inserted"] += 1

        session.commit()

    return counts


if __name__ == "__main__":
    result = load_source_documents()
    print(
        "Loaded source documents: "
        f"{result['inserted']} inserted, "
        f"{result['updated']} updated, "
        f"{result['skipped']} skipped"
    )
