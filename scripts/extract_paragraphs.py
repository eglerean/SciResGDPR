"""Extract paragraph-level text units from each PDF for downstream clustering.

Usage:
    python scripts/extract_paragraphs.py

Writes output/paragraphs.parquet: one row per paragraph/heading unit, with columns
paragraph_id, submission_id, order_in_doc, unit_type, text, language, n_chars.

Deterministic and cheap (no LLM calls) - safe to rerun any time extraction logic changes,
independent of the embedding/clustering step in cluster_themes.py.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from langdetect import DetectorFactory, LangDetectException, detect
from tqdm import tqdm

from pdf_utils import DATA_DIR, extract_text_blocks, is_boilerplate, list_pdfs, submission_id_from_filename

DetectorFactory.seed = 0  # deterministic langdetect

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

MIN_PARAGRAPH_CHARS = 40  # shorter blocks are treated as headings, not arguments
HEADING_MAX_CHARS = 120


def classify_unit(text: str) -> str:
    single_line = "\n" not in text.strip()
    if len(text) < MIN_PARAGRAPH_CHARS:
        return "fragment"
    if single_line and len(text) <= HEADING_MAX_CHARS and not text.strip().endswith((".", ",", ";", ":")):
        return "heading"
    return "paragraph"


def detect_language(text: str) -> str:
    try:
        return detect(text)
    except LangDetectException:
        return "unknown"


def paragraphs_for_pdf(path: Path) -> list[dict]:
    submission_id = submission_id_from_filename(path)
    blocks = extract_text_blocks(path)

    rows = []
    order = 0
    pending_heading = None
    for block in blocks:
        text = block.text.strip()
        if not text or is_boilerplate(text):
            continue

        unit_type = classify_unit(text)

        if unit_type == "fragment":
            # Merge short fragments into the next real paragraph as a heading-ish prefix.
            pending_heading = f"{pending_heading} {text}".strip() if pending_heading else text
            continue

        if unit_type == "heading":
            pending_heading = f"{pending_heading} {text}".strip() if pending_heading else text
            continue

        # unit_type == "paragraph"
        full_text = f"{pending_heading}: {text}" if pending_heading else text
        pending_heading = None

        rows.append(
            {
                "submission_id": submission_id,
                "order_in_doc": order,
                "unit_type": unit_type,
                "text": full_text,
                "language": detect_language(text),
                "n_chars": len(full_text),
            }
        )
        order += 1

    return rows


def main():
    pdfs = list_pdfs(DATA_DIR)

    all_rows = []
    for path in tqdm(pdfs, desc="Extracting paragraphs"):
        try:
            all_rows.extend(paragraphs_for_pdf(path))
        except Exception as e:
            print(f"FAILED on {path.name}: {e}")

    df = pd.DataFrame(all_rows)
    df.insert(0, "paragraph_id", [f"{row.submission_id}-{row.order_in_doc:04d}" for row in df.itertuples()])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "paragraphs.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Wrote {len(df)} paragraph units from {len(pdfs)} PDFs to {out_path}")
    print(df["unit_type"].value_counts())
    print(df["language"].value_counts())


if __name__ == "__main__":
    main()
