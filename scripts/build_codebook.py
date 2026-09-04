"""Consolidate raw open-coding output into a canonical codebook.

Usage:
    python scripts/build_codebook.py [--resolution R] [--knn K] [--force]

Pass 1 (extract_codes.py) produces near-duplicate codes for the same issue, e.g.
"proportionality of ex ante access controls" / "proportionality of ex ante access limitations".
This pass embeds the distinct code strings, builds a kNN graph, runs Leiden at a HIGH resolution
(so it merges only near-duplicates, not distinct issues), and asks the LLM to name each group.

Reads  output/codes_raw.parquet
Writes output/codes.parquet   (raw rows + canonical_code_id / canonical_code)
       output/codebook.xlsx   (canonical code, merged variants, coverage counts)
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
NAMING_CACHE = CACHE_DIR / "codebook_names"
MODEL = "claude-sonnet-5"
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"


class CanonicalName(BaseModel):
    canonical_code: str


NAMING_PROMPT = """These phrases were produced by open coding of responses to a public \
consultation on GDPR and scientific research. They were grouped together as near-duplicates \
naming the same underlying issue.

Give ONE canonical short noun phrase (2-6 words, English, lowercase) that best names the shared \
issue. Name the issue, not any position taken on it. Prefer the wording closest to the group's \
common meaning rather than inventing new terminology.

Phrases:
{phrases}"""


def embed_codes(codes: list[str]) -> np.ndarray:
    def compute():
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(EMBEDDING_MODEL)
        # e5 models expect a task prefix; "query: " is the documented default for short text.
        return model.encode(
            [f"query: {c}" for c in codes],
            show_progress_bar=True,
            normalize_embeddings=True,
            batch_size=64,
        )

    return cached_array(CACHE_DIR, "code_embeddings", codes, compute)


def group_cache_key(phrases: list[str]) -> str:
    """Content-derived cache key. Leiden's group ids are just positional integers that are
    reassigned from scratch on every run - reusing them as a cache key (as an earlier version
    of this script did) causes a group from one resolution/run to silently load the cached name
    of an unrelated group from a previous run that happened to get the same integer id. Hashing
    the group's actual member phrases ties the cache to content, not position."""
    digest = hashlib.sha256("\n".join(sorted(phrases)).encode("utf-8")).hexdigest()
    return digest[:16]


def name_group(client: anthropic.Anthropic, phrases: list[str], force: bool) -> str:
    # A group with one member needs no LLM call - its only phrase is already canonical.
    if len(phrases) == 1:
        return phrases[0]

    cache_path = NAMING_CACHE / f"{group_cache_key(phrases)}.json"
    if cache_path.exists() and not force:
        return json.loads(cache_path.read_text())["canonical_code"]

    listed = "\n".join(f"- {p}" for p in sorted(phrases)[:40])
    response = client.messages.parse(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": NAMING_PROMPT.format(phrases=listed)}],
        output_format=CanonicalName,
    )
    name = response.parsed_output.canonical_code.strip().lower()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"canonical_code": name}, ensure_ascii=False))
    return name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", type=float, default=80.0,
                        help="Leiden resolution; HIGH so only near-duplicates merge. Note: this "
                        "value is NOT scale-invariant - it was swept and validated on this "
                        "corpus's ~5k distinct raw codes (see conversation/commit history); "
                        "re-sweep if the corpus size changes substantially.")
    parser.add_argument("--knn", type=int, default=10)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    raw = pd.read_parquet(OUTPUT_DIR / "codes_raw.parquet")
    distinct = sorted(raw["code"].dropna().unique())
    print(f"{len(raw)} raw code rows, {len(distinct)} distinct code strings")

    embeddings = embed_codes(distinct)
    membership = leiden_partition(embeddings, k=args.knn, resolution=args.resolution)
    n_groups = len(set(membership))
    print(f"Leiden merged them into {n_groups} groups (resolution={args.resolution})")

    groups: dict[int, list[str]] = {}
    for code, gid in zip(distinct, membership):
        groups.setdefault(gid, []).append(code)

    client = anthropic.Anthropic(max_retries=5)
    names = {}
    for gid, phrases in tqdm(sorted(groups.items()), desc="Naming canonical codes"):
        try:
            names[gid] = name_group(client, phrases, args.force)
        except Exception as e:
            print(f"FAILED naming group {gid}: {e}")
            names[gid] = sorted(phrases)[0]  # fall back to a member phrase

    code_to_group = {code: gid for code, gid in zip(distinct, membership)}
    raw["canonical_code_id"] = raw["code"].map(code_to_group)
    raw["canonical_code"] = raw["canonical_code_id"].map(names)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw.to_parquet(OUTPUT_DIR / "codes.parquet", index=False)

    codebook = (
        raw.groupby(["canonical_code_id", "canonical_code"])
        .agg(
            n_code_rows=("code_id", "count"),
            n_paragraphs=("paragraph_id", "nunique"),
            n_submissions=("submission_id", "nunique"),
        )
        .reset_index()
        .sort_values("n_submissions", ascending=False)
    )
    codebook["variants"] = codebook["canonical_code_id"].map(
        lambda gid: "; ".join(sorted(groups[gid])[:25])
    )
    codebook["n_variants"] = codebook["canonical_code_id"].map(lambda gid: len(groups[gid]))
    codebook.to_excel(OUTPUT_DIR / "codebook.xlsx", index=False)

    print(f"\nWrote codebook.xlsx: {len(codebook)} canonical codes")
    print(codebook.head(15).to_string(index=False, max_colwidth=60))


if __name__ == "__main__":
    main()
