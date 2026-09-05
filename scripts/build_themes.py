"""Build a multi-level theme hierarchy over the canonical codebook using Leiden.

Usage:
    python scripts/build_themes.py [--resolutions 2 6] [--knn 15] [--force]

Rather than seeking one "correct" partition, this runs Leiden on the same kNN graph of canonical
code embeddings at several resolutions: a low resolution gives broad level-1 themes, a higher one
gives level-2 subthemes, and the canonical codes themselves are level 3. Levels are nested by
majority containment so the result reads as a tree.

Reads  output/codes.parquet, output/codebook.xlsx, output/metadata.xlsx
Writes output/themes.xlsx  (3 sheets: Theme Summary, Subthemes, Codes - see write_theme_tables)
       output/codes.xlsx   (flat paragraph x code table for reading)
       output/theme_tree.json  (consumed by build_explorer.py)

To only regenerate themes.xlsx/codes.xlsx from an already-computed output/codes_themed.parquet
(e.g. after changing the summary layout, without re-running Leiden/LLM naming), run:
    python -c "import pandas as pd; from build_themes import write_theme_tables, OUTPUT_DIR; \
               write_theme_tables(pd.read_parquet(OUTPUT_DIR / 'codes_themed.parquet'))"

To only regenerate theme_tree.json from an already-computed output/codes_themed.parquet
(e.g. after changing the quote fields or grouping logic, without re-running Leiden/LLM naming), run:
    python -c "import json, pandas as pd; from build_themes import build_theme_tree, OUTPUT_DIR; \
               (OUTPUT_DIR / 'theme_tree.json').write_text(json.dumps(build_theme_tree(pd.read_parquet(OUTPUT_DIR / 'codes_themed.parquet')), ensure_ascii=False), encoding='utf-8')"
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import anthropic
import numpy as np
import pandas as pd
from pydantic import BaseModel
from tqdm import tqdm

from cluster_utils import cached_array, leiden_partition

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
CACHE_DIR = ROOT / "cache"
NAMING_CACHE = CACHE_DIR / "theme_names"
MODEL = "claude-sonnet-5"
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"

STANCE_ORDER = ["support", "oppose", "request_clarification", "propose_change", "concern", "other"]


class ThemeName(BaseModel):
    theme_name: str


NAMING_PROMPT = """These are issue codes extracted from responses to the EDPB's public \
consultation on Guidelines 1/2026 (GDPR and scientific research). They were clustered together \
as one {level}.

Give ONE short title (3-8 words, English, title case) naming what this group is about. Name the \
shared subject matter, not any position taken on it. Be specific to these codes - avoid generic \
titles like "Data Protection Issues" or "General Comments".

Codes:
{codes}"""


def embed_canonical_codes(codes: list[str]) -> np.ndarray:
    def compute():
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(EMBEDDING_MODEL)
        return model.encode(
            [f"query: {c}" for c in codes],
            show_progress_bar=True,
            normalize_embeddings=True,
            batch_size=64,
        )

    return cached_array(CACHE_DIR, "canonical_code_embeddings", codes, compute)


def group_cache_key(codes: list[str]) -> str:
    """Content-derived cache key - see build_codebook.py's group_cache_key for why a Leiden
    group's positional id must never be used as a cache key: it is reassigned from scratch on
    every run, so a stale name from an unrelated group can silently be served for a same-id
    group with completely different members."""
    digest = hashlib.sha256("\n".join(sorted(codes)).encode("utf-8")).hexdigest()
    return digest[:16]


def name_group(client: anthropic.Anthropic, codes: list[str], level: str, force: bool) -> str:
    cache_path = NAMING_CACHE / f"{group_cache_key(codes)}.json"
    if cache_path.exists() and not force:
        return json.loads(cache_path.read_text())["theme_name"]

    listed = "\n".join(f"- {c}" for c in sorted(codes)[:60])
    response = client.messages.parse(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": NAMING_PROMPT.format(level=level, codes=listed)}],
        output_format=ThemeName,
    )
    name = response.parsed_output.theme_name.strip()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"theme_name": name}, ensure_ascii=False))
    return name


def _stance_pivot(df: pd.DataFrame, index_cols: list[str]) -> pd.DataFrame:
    """n_paragraphs / n_submissions plus one column per stance, for the given grouping."""
    stance_counts = (
        df.pivot_table(index=index_cols, columns="stance", values="code_id", aggfunc="count", fill_value=0)
        .reset_index()
    )
    for s in STANCE_ORDER:
        if s not in stance_counts.columns:
            stance_counts[s] = 0
    base = (
        df.groupby(index_cols)
        .agg(n_paragraphs=("paragraph_id", "nunique"), n_submissions=("submission_id", "nunique"))
        .reset_index()
    )
    return base.merge(stance_counts, on=index_cols, how="left")


def _autosize(writer: pd.ExcelWriter, sheet_name: str, df: pd.DataFrame):
    ws = writer.sheets[sheet_name]
    for i, col in enumerate(df.columns, start=1):
        width = min(max(len(str(col)), df[col].astype(str).str.len().max() if len(df) else 0) + 2, 60)
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width


def write_theme_tables(codes_df: pd.DataFrame):
    """Write codes.xlsx (flat paragraph x code detail) and themes.xlsx (a 3-sheet workbook:
    a short theme-level summary meant to be readable in one glance, a subtheme-level rollup for
    the next level of drill-down, and the full canonical-code-level detail as the last sheet).

    Callable standalone on a saved output/codes_themed.parquet - see this module's docstring -
    so the summary layout can be iterated on without re-running Leiden/LLM naming.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    flat_cols = [
        "paragraph_id", "submission_id", "organisation_name", "organisation_type", "country",
        "submission_date", "submitted_by", "source_url",
        "theme", "subtheme", "canonical_code", "code", "stance", "claim", "target",
        "language", "text",
    ]
    flat_cols = [c for c in flat_cols if c in codes_df.columns]
    codes_df[flat_cols].sort_values(["theme", "subtheme", "canonical_code"]).to_excel(
        OUTPUT_DIR / "codes.xlsx", index=False
    )

    theme_summary = _stance_pivot(codes_df, ["theme"]).sort_values("n_submissions", ascending=False)
    theme_summary.insert(
        1, "pct_of_submissions",
        (100 * theme_summary["n_submissions"] / codes_df["submission_id"].nunique()).round(0).astype(int),
    )

    subtheme_summary = _stance_pivot(codes_df, ["theme", "subtheme"])
    theme_order = {t: i for i, t in enumerate(theme_summary["theme"])}
    subtheme_summary = subtheme_summary.assign(_t=subtheme_summary["theme"].map(theme_order)).sort_values(
        ["_t", "n_submissions"], ascending=[True, False]
    ).drop(columns="_t")

    code_detail = _stance_pivot(codes_df, ["theme", "subtheme", "canonical_code"])
    code_detail = code_detail.assign(_t=code_detail["theme"].map(theme_order)).sort_values(
        ["_t", "subtheme", "n_submissions"], ascending=[True, True, False]
    ).drop(columns="_t")

    stance_cols = [s for s in STANCE_ORDER]
    theme_summary = theme_summary[["theme", "pct_of_submissions", "n_submissions", "n_paragraphs", *stance_cols]]
    subtheme_summary = subtheme_summary[["theme", "subtheme", "n_submissions", "n_paragraphs", *stance_cols]]
    code_detail = code_detail[["theme", "subtheme", "canonical_code", "n_submissions", "n_paragraphs", *stance_cols]]

    with pd.ExcelWriter(OUTPUT_DIR / "themes.xlsx", engine="openpyxl") as writer:
        theme_summary.to_excel(writer, sheet_name="Theme Summary", index=False)
        subtheme_summary.to_excel(writer, sheet_name="Subthemes", index=False)
        code_detail.to_excel(writer, sheet_name="Codes", index=False)
        for name, df in [("Theme Summary", theme_summary), ("Subthemes", subtheme_summary), ("Codes", code_detail)]:
            _autosize(writer, name, df)


def nest_by_containment(child_membership: list[int], parent_membership: list[int]) -> dict[int, int]:
    """Map each child community to the parent community holding most of its members."""
    buckets: dict[int, list[int]] = {}
    for child, parent in zip(child_membership, parent_membership):
        buckets.setdefault(child, []).append(parent)
    return {child: Counter(parents).most_common(1)[0][0] for child, parents in buckets.items()}


def build_theme_tree(codes_df: pd.DataFrame) -> list:
    """Nested theme -> subtheme -> canonical-code -> quotes tree for the explorer.

    Callable standalone on a saved output/codes_themed.parquet - see this module's docstring -
    so theme_tree.json can be regenerated without re-running Leiden/LLM naming.
    """
    tree = []
    for theme, theme_rows in codes_df.groupby("theme"):
        subthemes = []
        for subtheme, sub_rows in theme_rows.groupby("subtheme"):
            leaves = []
            for code, code_rows in sub_rows.groupby("canonical_code"):
                # All distinct paragraphs, not a sample - the explorer's "n submissions" stat
                # must match how many quotes a reader can actually open. Observed max is 52
                # paragraphs for one code, so this safety cap is generous headroom, not a
                # real-world limit.
                quotes = (
                    code_rows.drop_duplicates("paragraph_id")
                    .head(300)[[
                        "paragraph_id", "submission_id", "organisation_name", "organisation_type",
                        "country", "submission_date", "submitted_by", "source_url", "stance",
                        "claim", "text",
                    ]]
                    .to_dict("records")
                )
                leaves.append({
                    "code": code,
                    "n_paragraphs": int(code_rows["paragraph_id"].nunique()),
                    "n_submissions": int(code_rows["submission_id"].nunique()),
                    "stances": code_rows["stance"].value_counts().to_dict(),
                    "organisations": sorted(code_rows["organisation_name"].dropna().unique().tolist())[:40],
                    "countries": sorted(code_rows["country"].dropna().unique().tolist()),
                    "targets": sorted(code_rows["target"].dropna().unique().tolist())[:25],
                    "quotes": [
                        {k: ("" if pd.isna(v) else str(v)) for k, v in q.items()} for q in quotes
                    ],
                })
            leaves.sort(key=lambda x: -x["n_submissions"])
            subthemes.append({
                "subtheme": subtheme,
                "n_paragraphs": int(sub_rows["paragraph_id"].nunique()),
                "n_submissions": int(sub_rows["submission_id"].nunique()),
                "stances": sub_rows["stance"].value_counts().to_dict(),
                "codes": leaves,
            })
        subthemes.sort(key=lambda x: -x["n_submissions"])
        tree.append({
            "theme": theme,
            "n_paragraphs": int(theme_rows["paragraph_id"].nunique()),
            "n_submissions": int(theme_rows["submission_id"].nunique()),
            "stances": theme_rows["stance"].value_counts().to_dict(),
            "subthemes": subthemes,
        })
    tree.sort(key=lambda x: -x["n_submissions"])
    return tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolutions", type=float, nargs=2, default=[2.0, 6.0],
                        metavar=("LEVEL1", "LEVEL2"),
                        help="Leiden resolutions for broad themes and subthemes. Note: like "
                        "build_codebook.py's --resolution, these are NOT scale-invariant - they "
                        "were swept and validated on this corpus's ~565 canonical codes; "
                        "re-sweep (see cluster_utils.leiden_partition) if the codebook size "
                        "changes substantially.")
    parser.add_argument("--knn", type=int, default=15)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    codes_df = pd.read_parquet(OUTPUT_DIR / "codes.parquet")
    canonical = sorted(codes_df["canonical_code"].dropna().unique())
    print(f"{len(codes_df)} code rows over {len(canonical)} canonical codes")

    embeddings = embed_canonical_codes(canonical)

    res1, res2 = args.resolutions
    level1 = leiden_partition(embeddings, k=args.knn, resolution=res1)
    level2 = leiden_partition(embeddings, k=args.knn, resolution=res2)
    print(f"Level 1 (res={res1}): {len(set(level1))} themes")
    print(f"Level 2 (res={res2}): {len(set(level2))} subthemes")

    sub_to_theme = nest_by_containment(level2, level1)

    code_to_l1 = dict(zip(canonical, level1))
    code_to_l2 = dict(zip(canonical, level2))
    codes_df["theme_id"] = codes_df["canonical_code"].map(code_to_l1)
    codes_df["subtheme_id"] = codes_df["canonical_code"].map(code_to_l2)

    # Name every community from its member codes.
    client = anthropic.Anthropic(max_retries=5)
    l1_members: dict[int, list[str]] = {}
    l2_members: dict[int, list[str]] = {}
    for code, a, b in zip(canonical, level1, level2):
        l1_members.setdefault(a, []).append(code)
        l2_members.setdefault(b, []).append(code)

    theme_names, subtheme_names = {}, {}
    for tid, members in tqdm(sorted(l1_members.items()), desc="Naming themes"):
        theme_names[tid] = name_group(client, members, "broad theme", args.force)
    for sid, members in tqdm(sorted(l2_members.items()), desc="Naming subthemes"):
        subtheme_names[sid] = name_group(client, members, "subtheme", args.force)

    codes_df["theme"] = codes_df["theme_id"].map(theme_names)
    codes_df["subtheme"] = codes_df["subtheme_id"].map(subtheme_names)

    # Join respondent metadata for reading and for the explorer's facets. organisation_name
    # comes from the LLM read of the actual PDF (metadata.xlsx) - kept as the primary display
    # identity, since the EDPB platform's own "submitted by" field is the contact person who
    # filled the form, not the institution (e.g. "Sofie Andersen" for an Aarhus Universitet
    # submission). organisation_type, country, submission_date, submitted_by (the contact name,
    # kept as a separate field), and source_url come from the platform's own ground-truth export
    # (metadata_groundtruth.xlsx) - authoritative, not a guess.
    codes_df["submission_id"] = codes_df["submission_id"].astype(str)

    llm_meta_path = OUTPUT_DIR / "metadata.xlsx"
    if llm_meta_path.exists():
        llm_meta = pd.read_excel(llm_meta_path)[["submission_id", "organisation_name"]]
        llm_meta["submission_id"] = llm_meta["submission_id"].astype(str)
        codes_df = codes_df.merge(llm_meta, on="submission_id", how="left")

    gt_meta_path = OUTPUT_DIR / "metadata_groundtruth.xlsx"
    if gt_meta_path.exists():
        gt_meta = pd.read_excel(gt_meta_path)[
            ["submission_id", "submitter_type", "country", "submission_date", "submitted_by", "source_url"]
        ].rename(columns={"submitter_type": "organisation_type"})
        gt_meta["submission_id"] = gt_meta["submission_id"].astype(str)
        codes_df = codes_df.merge(gt_meta, on="submission_id", how="left")

    # Attach the source paragraph text so quotes are readable without a second join.
    paragraphs = pd.read_parquet(OUTPUT_DIR / "paragraphs.parquet")[["paragraph_id", "text", "language"]]
    codes_df = codes_df.merge(paragraphs, on="paragraph_id", how="left")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    codes_df.to_parquet(OUTPUT_DIR / "codes_themed.parquet", index=False)

    write_theme_tables(codes_df)

    tree = build_theme_tree(codes_df)
    (OUTPUT_DIR / "theme_tree.json").write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")

    print(f"\nWrote themes.xlsx, codes.xlsx, theme_tree.json")
    print(f"{len(tree)} themes, {sum(len(t['subthemes']) for t in tree)} subthemes, "
          f"{len(canonical)} canonical codes")
    print("\nTop themes by number of submissions raising them:")
    for t in tree[:12]:
        print(f"  {t['n_submissions']:3d} submissions  {t['theme']}")


if __name__ == "__main__":
    main()
