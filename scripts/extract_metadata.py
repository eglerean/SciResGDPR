"""Extract submission metadata (org, country, authors, ...) from each PDF via Claude,
and write it to output/metadata.xlsx.

Usage:
    python scripts/extract_metadata.py [--limit N] [--force]

Requires ANTHROPIC_API_KEY (or another credential source the Anthropic SDK can find).
Raw LLM responses are cached under cache/metadata_raw/<submission_id>.json so reruns
are free unless --force is passed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal, Optional

import anthropic
import pandas as pd
from pydantic import BaseModel
from tqdm import tqdm

from pdf_utils import DATA_DIR, extract_first_pages_text, list_pdfs, page_count, submission_id_from_filename

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
CACHE_DIR = ROOT / "cache" / "metadata_raw"
MODEL = "claude-sonnet-5"  # structured extraction from short text doesn't need Opus-tier

ORG_TYPES = [
    "university",
    "hospital_or_healthcare",
    "company",
    "industry_association",
    "ngo_or_civil_society",
    "national_dpa",
    "government_or_public_authority",
    "research_institute",
    "individual",
    "other",
]


class SubmissionMetadata(BaseModel):
    organisation_name: str
    organisation_type: Literal[tuple(ORG_TYPES)]  # type: ignore[valid-type]
    country: str
    authors: list[str]
    author_role: Optional[str]
    submission_date: Optional[str]
    language: str
    topic_summary: str


EXTRACTION_PROMPT = """The following is the first page(s) of a PDF submission responding to the \
EDPB's (European Data Protection Board) public consultation on Draft Guidelines 1/2026 on the \
GDPR and scientific research. Extract the submission's metadata.

- organisation_name: the submitting organisation's name, or the individual's name if this is a \
personal submission (not an organisation).
- organisation_type: best-fit category for the submitter.
- country: the country the submitter is based in (best guess from address/context if not explicit).
- authors: named individual author(s)/signatories, if any (empty list if none named).
- author_role: the named author's job title/role, if stated (null otherwise).
- submission_date: the date of the submission as written in the document (null if absent).
- language: the language the document is written in (e.g. "English", "Italian", "Danish").
- topic_summary: one sentence summarizing what this submission focuses on/asks for.

Document text:
---
{text}
---"""


def extract_one(client: anthropic.Anthropic, path: Path, force: bool) -> dict:
    submission_id = submission_id_from_filename(path)
    cache_path = CACHE_DIR / f"{submission_id}.json"

    if cache_path.exists() and not force:
        raw = json.loads(cache_path.read_text())
    else:
        text = extract_first_pages_text(path, max_pages=2)
        response = client.messages.parse(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(text=text)}],
            output_format=SubmissionMetadata,
        )
        raw = response.parsed_output.model_dump()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False))

    raw["submission_id"] = submission_id
    raw["filename"] = path.name
    raw["page_count"] = page_count(path)
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N PDFs (for testing)")
    parser.add_argument("--force", action="store_true", help="Re-call the API even if a cached response exists")
    args = parser.parse_args()

    pdfs = list_pdfs(DATA_DIR)
    if args.limit:
        pdfs = pdfs[: args.limit]

    client = anthropic.Anthropic()

    rows = []
    for path in tqdm(pdfs, desc="Extracting metadata"):
        try:
            rows.append(extract_one(client, path, args.force))
        except Exception as e:
            print(f"FAILED on {path.name}: {e}")
            rows.append({"submission_id": submission_id_from_filename(path), "filename": path.name, "error": str(e)})

    df = pd.DataFrame(rows)
    id_cols = ["submission_id", "filename", "organisation_name", "organisation_type", "country"]
    other_cols = [c for c in df.columns if c not in id_cols]
    df = df[id_cols + other_cols]
    df["submission_id"] = df["submission_id"].astype(int)
    df = df.sort_values("submission_id")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "metadata.xlsx"
    df.to_excel(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")


if __name__ == "__main__":
    main()
