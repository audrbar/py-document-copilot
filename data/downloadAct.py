# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "certifi>=2024.0.0",
# ]
# ///
from __future__ import annotations

import json
import re
import ssl
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin
from urllib import error, request

import certifi


# Params: edit these, then run `uv run data/downloadAct.py`
USER_AGENT = "Document Copilot your.email@example.com"
LEGAL_ACT_IDS = ["TAR.F4CA26A706AF", "10b83000a53b11e8acb39f2e6db7935b"]
OUTPUT_DIR = Path(__file__).resolve().parent / "downloads_acts"
CLEAR_OUTPUT_DIR = True
MAX_WORKERS = 8
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 2
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
BASE_URL = "https://www.e-tar.lt"


def build_act_url(legal_act_id: str) -> str:
    return f"https://www.e-tar.lt/portal/lt/legalAct/{legal_act_id}/asr"


def get_bytes(url: str, *, accept: str) -> bytes:
    req = request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": USER_AGENT,
        },
    )
    with request.urlopen(
        req,
        timeout=REQUEST_TIMEOUT_SECONDS,
        context=SSL_CONTEXT,
    ) as response:
        return response.read()


def extract_docx_url(asr_html: str, legal_act_id: str) -> str | None:
    escaped_id = re.escape(legal_act_id)

    docx_pattern = re.compile(
        rf'href=["\'](?P<url>/rs/actualedition/{escaped_id}/[^"\']+/format/MSO2010_DOCX/?)["\']',
        re.IGNORECASE,
    )
    match = docx_pattern.search(asr_html)
    if match:
        return urljoin(BASE_URL, match.group("url"))

    iframe_pattern = re.compile(
        rf'src=["\'](?P<src>/rs/actualedition/{escaped_id}/(?P<edition>[^/"\']+)/?)["\']',
        re.IGNORECASE,
    )
    iframe_match = iframe_pattern.search(asr_html)
    if iframe_match:
        edition = iframe_match.group("edition")
        return (
            f"{BASE_URL}/rs/actualedition/{legal_act_id}/{edition}/format/MSO2010_DOCX/"
        )

    return None


def normalize_ids(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []

    for raw_id in ids:
        legal_act_id = raw_id.strip()
        if not legal_act_id:
            continue
        if legal_act_id in seen:
            continue
        seen.add(legal_act_id)
        normalized.append(legal_act_id)

    return normalized


def download_act(legal_act_id: str) -> dict[str, str]:
    asr_url = build_act_url(legal_act_id)
    target_relative = Path("acts") / f"{legal_act_id}.docx"
    target_path = OUTPUT_DIR / target_relative
    target_path.parent.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    for _ in range(MAX_RETRIES + 1):
        try:
            asr_bytes = get_bytes(
                asr_url,
                accept="text/html,application/xhtml+xml,application/xml",
            )
            asr_html = asr_bytes.decode("utf-8", errors="replace")
            docx_url = extract_docx_url(asr_html, legal_act_id)
            if not docx_url:
                raise RuntimeError(
                    f"Could not locate DOCX URL in ASR page for legalActId={legal_act_id}"
                )

            docx_bytes = get_bytes(
                docx_url,
                accept="application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/octet-stream,*/*",
            )
            target_path.write_bytes(docx_bytes)

            return {
                "legal_act_id": legal_act_id,
                "source_url": docx_url,
                "asr_source_url": asr_url,
                "local_path": str(target_relative),
            }
        except (error.HTTPError, error.URLError, TimeoutError, OSError) as exc:
            last_error = exc

    if last_error is None:
        raise RuntimeError(f"Unknown error downloading legalActId={legal_act_id}")
    raise RuntimeError(f"Failed legalActId={legal_act_id}: {last_error}")


def download_acts() -> dict:
    legal_act_ids = normalize_ids(LEGAL_ACT_IDS)
    if not legal_act_ids:
        raise ValueError("LEGAL_ACT_IDS is empty. Add at least one legalActId.")

    if CLEAR_OUTPUT_DIR and OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = {
        "source": "E-TAR",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "form": "LEGAL-ACT",
        "downloaded_count": 0,
        "failed_count": 0,
        "filings": [],
        "failures": [],
    }

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(download_act, legal_act_id): legal_act_id
            for legal_act_id in legal_act_ids
        }

        for future in as_completed(future_map):
            legal_act_id = future_map[future]
            try:
                entry = future.result()
                manifest["filings"].append(entry)
                manifest["downloaded_count"] += 1
                print(f"Downloaded legalActId={legal_act_id}")
            except Exception as exc:
                manifest["failed_count"] += 1
                manifest["failures"].append(
                    {
                        "legal_act_id": legal_act_id,
                        "error": str(exc),
                    }
                )
                print(f"Failed legalActId={legal_act_id}: {exc}")

    manifest["filings"].sort(key=lambda item: item["legal_act_id"])
    manifest["failures"].sort(key=lambda item: item["legal_act_id"])

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return manifest


if __name__ == "__main__":
    result = download_acts()
    print(f"Downloaded {result['downloaded_count']} act(s) to {OUTPUT_DIR}")
    if result["failed_count"]:
        print(
            f"Failed {result['failed_count']} act(s). Check {OUTPUT_DIR / 'manifest.json'}"
        )
    print(f"Manifest: {OUTPUT_DIR / 'manifest.json'}")
