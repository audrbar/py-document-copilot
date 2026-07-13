# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "docling==2.96.0",
# ]
# ///
from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from docling.document_converter import DocumentConverter

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ingest.sec_tables import extract_sec_tables, tables_to_json, tables_to_markdown


# Params: edit these, then run `uv run data/convert_to_markdown.py`
INPUT_DIR = Path(__file__).resolve().parent / "downloads"
OUTPUT_DIR = Path(__file__).resolve().parent / "markdown"
CLEAR_OUTPUT_DIR = False
SKIP_EXISTING = True


def resolve_input_dir() -> Path:
    default_dir = INPUT_DIR
    acts_dir = Path(__file__).resolve().parent / "downloads_acts"

    if (default_dir / "manifest.json").is_file():
        return default_dir
    if (acts_dir / "manifest.json").is_file():
        return acts_dir

    return default_dir


def convert_downloads_to_markdown() -> dict:
    input_dir = resolve_input_dir()
    manifest_path = input_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Missing {manifest_path}. Run `uv run data/download.py` or `uv run data/downloadAct.py` first. "
            "If you are in the data folder, use `uv run convert_to_markdown.py`."
        )

    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    filings = source_manifest.get("filings", []) or source_manifest.get("acts", [])
    if not filings:
        raise ValueError(f"No records listed in {manifest_path}")

    if CLEAR_OUTPUT_DIR and OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    converter = DocumentConverter()
    source = source_manifest.get("source", "")
    use_sec_tables = source.upper().startswith("SEC")
    manifest = {
        "source": source_manifest.get("source", "unknown"),
        "converted_at_utc": datetime.now(UTC).isoformat(),
        "form": source_manifest.get("form", "unknown"),
        "converted_count": 0,
        "filings": [],
    }

    for filing in filings:
        source_relative = filing["local_path"]
        source_path = input_dir / source_relative
        if not source_path.is_file():
            raise FileNotFoundError(f"Missing source file: {source_path}")

        md_relative = str(Path(source_relative).with_suffix(".md"))
        md_path = OUTPUT_DIR / md_relative
        md_path.parent.mkdir(parents=True, exist_ok=True)
        tables_json_path = md_path.with_suffix(".tables.json")
        tables = []
        if use_sec_tables and source_path.suffix.lower() in {".html", ".htm"}:
            source_text = source_path.read_text(encoding="utf-8")
            tables = extract_sec_tables(source_text)

        if SKIP_EXISTING and md_path.exists():
            print(f"Skipping existing {md_relative}")
            if tables and "# Normalized Tables" not in md_path.read_text(
                encoding="utf-8"
            ):
                with md_path.open("a", encoding="utf-8") as output:
                    output.write(
                        f"\n\n# Normalized Tables\n\n{tables_to_markdown(tables)}"
                    )
            if tables and not tables_json_path.exists():
                tables_json_path.write_text(
                    json.dumps(tables_to_json(tables), indent=2) + "\n",
                    encoding="utf-8",
                )
        else:
            print(f"Converting {source_relative}...")
            result = converter.convert(source_path)
            markdown = result.document.export_to_markdown()
            if tables:
                markdown = (
                    f"{markdown}\n\n# Normalized Tables\n\n{tables_to_markdown(tables)}"
                )
            md_path.write_text(
                markdown,
                encoding="utf-8",
            )
            if tables:
                tables_json_path.write_text(
                    json.dumps(tables_to_json(tables), indent=2) + "\n",
                    encoding="utf-8",
                )

        manifest_filing = {
            **filing,
            "source_local_path": source_relative,
            "local_path": md_relative,
        }
        if tables_json_path.exists():
            manifest_filing["tables_local_path"] = str(
                Path(md_relative).with_suffix(".tables.json")
            )
        manifest["filings"].append(manifest_filing)
        manifest["converted_count"] += 1

    output_manifest_path = OUTPUT_DIR / "manifest.json"
    output_manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    result = convert_downloads_to_markdown()
    input_dir = resolve_input_dir()
    print(
        f"Converted {result['converted_count']} filing(s) from {input_dir} to {OUTPUT_DIR}"
    )
    print(f"Manifest: {OUTPUT_DIR / 'manifest.json'}")
