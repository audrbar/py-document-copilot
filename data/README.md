# Data

Local data artifacts for development live here.

- `downloads/` holds raw source files fetched from SEC EDGAR, grouped by year.
- `downloads_acts/` holds raw legal act DOCX files fetched from E-TAR.
- `markdown/` holds Docling-converted Markdown exports with the same year layout and manifest.
- Downloaded and converted payloads are gitignored because the corpus can get large.
- Fetch a sample corpus with `uv run data/download.py`
- Fetch legal acts in parallel with `uv run data/downloadAct.py`
- Convert HTML filings to Markdown with `uv run data/convert_to_markdown.py`
  - For legal acts, set `INPUT_DIR = Path(__file__).resolve().parent / "downloads_acts"`
