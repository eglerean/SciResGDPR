"""Estimate each submission's dominant language and export a metadata xlsx.

Language is estimated from output/paragraphs.parquet, which has a per-paragraph
langdetect language code plus character count for every submission. The dominant
language is the one with the most characters (not just the most paragraphs), so a
submission with a short quoted passage or letterhead in another language is still
correctly labelled by its main written language.

Two PDFs (10735, 10890) have no extractable text layer (scanned/image-only); for
those, language was confirmed by visually inspecting rendered page images.

Reads: output/paragraphs.parquet, output/metadata_groundtruth.xlsx, output/metadata.xlsx
Writes: output/submission_languages.xlsx
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

LANGUAGE_NAMES = {
    "en": "English", "it": "Italian", "fr": "French", "de": "German",
    "es": "Spanish", "pt": "Portuguese", "da": "Danish", "nl": "Dutch",
    "sv": "Swedish", "fi": "Finnish", "pl": "Polish", "el": "Greek",
    "cs": "Czech", "sk": "Slovak", "ro": "Romanian", "hu": "Hungarian",
    "no": "Norwegian", "hr": "Croatian", "sl": "Slovenian", "et": "Estonian",
    "lv": "Latvian", "lt": "Lithuanian", "bg": "Bulgarian", "ca": "Catalan",
    "tr": "Turkish", "id": "Indonesian", "unknown": "Unknown",
}

# Confirmed by rendering the pages to images and reading them directly, since these
# two PDFs have no extractable text layer for langdetect to work with.
NO_TEXT_LAYER_LANGUAGE = {
    10735: "English",  # "what-edpb-guidelines-needs-to-fix" - op-ed style PDF, text rendered as image
    10890: "English",  # Farmindustria submission, scanned/flattened PDF
}


def main():
    par = pd.read_parquet(OUTPUT_DIR / "paragraphs.parquet")
    par["submission_id"] = par["submission_id"].astype(int)

    agg = par.groupby(["submission_id", "language"])["n_chars"].sum().reset_index()
    totals = agg.groupby("submission_id")["n_chars"].sum().rename("total_chars")
    agg = agg.merge(totals, on="submission_id")
    agg["share"] = agg["n_chars"] / agg["total_chars"]

    dominant = (
        agg.sort_values(["submission_id", "n_chars"], ascending=[True, False])
        .groupby("submission_id")
        .first()
        .reset_index()
    )
    dominant["language"] = dominant["language"].map(lambda c: LANGUAGE_NAMES.get(c, c))
    dominant["language_share"] = dominant["share"].round(2)
    dominant = dominant[["submission_id", "language", "language_share"]]

    groundtruth = pd.read_excel(OUTPUT_DIR / "metadata_groundtruth.xlsx")[
        ["submission_id", "submitted_by", "submitter_type", "country", "submission_date"]
    ]
    page_counts = pd.read_excel(OUTPUT_DIR / "metadata.xlsx")[["submission_id", "filename", "page_count"]]

    df = page_counts.merge(groundtruth, on="submission_id", how="left").merge(dominant, on="submission_id", how="left")

    missing = df["language"].isna()
    for sid, lang in NO_TEXT_LAYER_LANGUAGE.items():
        df.loc[df["submission_id"] == sid, "language"] = lang
    df.loc[df["submission_id"].isin(NO_TEXT_LAYER_LANGUAGE), "language_share"] = pd.NA

    df["notes"] = ""
    no_text_mask = df["submission_id"].isin(NO_TEXT_LAYER_LANGUAGE)
    df.loc[no_text_mask, "notes"] = (
        "No extractable text layer (scanned/image PDF); language confirmed by visual inspection."
    )
    mixed_mask = (~no_text_mask) & (df["language_share"] < 0.85)
    df.loc[mixed_mask, "notes"] = "Document contains a substantial secondary-language passage; label reflects majority language."

    df = df.rename(columns={
        "submission_id": "document_id",
        "submitted_by": "submitted_by",
        "submitter_type": "submitter_type",
    })
    df = df[[
        "document_id", "filename", "submitted_by", "submitter_type", "country",
        "submission_date", "page_count", "language", "language_share", "notes",
    ]]
    df = df.sort_values("document_id")

    out_path = OUTPUT_DIR / "submission_languages.xlsx"
    df.to_excel(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")
    print(df["language"].value_counts())


if __name__ == "__main__":
    main()
