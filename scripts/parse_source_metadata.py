"""Parse the EDPB-scraped submission metadata into a ground-truth table.

Usage:
    python scripts/parse_source_metadata.py

data/metadata.html is a single <table class="cols-5"> scraped directly from the EDPB
consultation-feedback page: submission date, submitter type (a controlled 7-category
vocabulary), country, submitter name, and a relative link to the original PDF. Unlike
output/metadata.xlsx (LLM-inferred from the PDF's first pages), every field here is
authoritative - it comes from the consultation platform itself, not a guess - so it takes
priority over the LLM fields for organisation identity, country, and date wherever both exist.

Joins to local PDFs by filename: the scraped link's basename
("feedback_1527_statement-....pdf") is a suffix of the local filename
("10912-feedback_1527_statement-....pdf"), so the join strips the numeric submission_id
prefix rather than matching on the numeric portion of the scraped path (which is a different,
sequential comment id, not the submission_id used elsewhere in this pipeline).

Writes output/metadata_groundtruth.xlsx: submission_id, submission_date, submitter_type,
country, submitted_by, source_url.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from pdf_utils import DATA_DIR, list_pdfs, submission_id_from_filename

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
METADATA_HTML = DATA_DIR / "metadata.html"

# The relative hrefs in metadata.html (e.g. /system/files/consultation_feedback/1527/....pdf)
# need this prefix to become a working link to the original PDF.
BASE_URL = "https://www.edpb.europa.eu"

ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TIME_TITLE_RE = re.compile(r'title="([^"]+)"')
HREF_RE = re.compile(r'href="([^"]+)"')
TAG_RE = re.compile(r"<[^>]+>")


def clean(text: str) -> str:
    return TAG_RE.sub("", text).strip()


def parse_rows(html: str) -> list[dict]:
    rows = [r for r in ROW_RE.findall(html) if "<td" in r]
    parsed = []
    for row in rows:
        tds = TD_RE.findall(row)
        if len(tds) != 5:
            raise ValueError(f"expected 5 columns, got {len(tds)}: {row[:200]}")
        date_match = TIME_TITLE_RE.search(tds[0])
        href_match = HREF_RE.search(tds[4])
        parsed.append({
            "submission_date": date_match.group(1) if date_match else None,
            "submitter_type": clean(tds[1]),
            "country": clean(tds[2]),
            "submitted_by": clean(tds[3]),
            "href": href_match.group(1) if href_match else None,
        })
    return parsed


def main():
    html = METADATA_HTML.read_text(encoding="utf-8")
    rows = parse_rows(html)
    print(f"Parsed {len(rows)} rows from {METADATA_HTML}")

    # Join to local PDFs by filename suffix: the scraped href's basename is the local
    # filename with its numeric "<submission_id>-" prefix stripped.
    local_by_suffix = {p.name.split("-", 1)[1]: p for p in list_pdfs(DATA_DIR)}

    matched, unmatched = [], []
    for row in rows:
        basename = row["href"].rsplit("/", 1)[-1] if row["href"] else None
        pdf_path = local_by_suffix.get(basename)
        if pdf_path is None:
            unmatched.append(row)
            continue
        row["submission_id"] = submission_id_from_filename(pdf_path)
        row["source_url"] = BASE_URL.rstrip("/") + row["href"]
        matched.append(row)

    print(f"Matched {len(matched)}/{len(rows)} rows to local PDFs")
    if unmatched:
        print("UNMATCHED (not written to output):")
        for row in unmatched:
            print(f"  {row['submitted_by']!r} -> {row['href']}")

    df = pd.DataFrame(matched)[
        ["submission_id", "submission_date", "submitter_type", "country", "submitted_by", "source_url"]
    ]
    df["submission_id"] = df["submission_id"].astype(int)
    df = df.sort_values("submission_id")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "metadata_groundtruth.xlsx"
    df.to_excel(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")

    if "__BASE_URL_PLACEHOLDER__" in BASE_URL:
        print("\nWARNING: BASE_URL is still a placeholder - source_url values are not real links yet.")


if __name__ == "__main__":
    main()
