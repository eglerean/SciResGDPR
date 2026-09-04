"""LLM open coding: turn each paragraph into 0-5 short atomic codes with a stance.

Usage:
    python scripts/extract_codes.py [--limit N] [--batch-size N] [--force]

This is pass 1 of the code-level theme pipeline. Instead of clustering 500-word paragraphs
(which mixes several arguments together and groups by shared legal vocabulary), we ask the
model to name the individual issues each paragraph raises. Those short codes are what later
gets embedded and clustered.

Reads  output/paragraphs.parquet
Writes output/codes_raw.parquet   (one row per paragraph x code)
       cache/codes_raw/<batch>.json  raw responses, so reruns are free
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal, Optional

import anthropic
import pandas as pd
from pydantic import BaseModel
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
CACHE_DIR = ROOT / "cache" / "codes_raw"
MODEL = "claude-sonnet-5"

STANCES = ["support", "oppose", "request_clarification", "propose_change", "concern", "other"]


class Code(BaseModel):
    code: str
    stance: Literal[tuple(STANCES)]  # type: ignore[valid-type]
    claim: str
    target: Optional[str]


class ParagraphCoding(BaseModel):
    index: int
    is_substantive: bool
    codes: list[Code]


class BatchCoding(BaseModel):
    paragraphs: list[ParagraphCoding]


SYSTEM_PROMPT = """You are performing qualitative open coding on responses to the EDPB's public \
consultation on Draft Guidelines 1/2026 (GDPR and scientific research). You will be given \
numbered paragraphs extracted from submissions. Code each one.

For each paragraph, return:

- index: the paragraph's number, exactly as given.
- is_substantive: true only if the paragraph makes an actual argument, criticism, request or \
proposal about the Guidelines. Set it to FALSE for letterheads, addresses, author names and job \
titles, dates, salutations, signature blocks, page headers/footers, tables of contents, document \
titles, and pure courtesy framing such as "we welcome the opportunity to comment" or "please find \
our response attached". Non-substantive paragraphs must have an empty codes list.
- codes: 1-5 atomic codes for a substantive paragraph, empty otherwise. A paragraph that raises \
several distinct issues MUST get one code per issue - do not force it into a single code.

Each code has:
- code: a short noun phrase (2-6 words) naming ONE issue, e.g. "fees for data access", \
"broad consent validity", "joint controllership in clinical trials". ALWAYS WRITE THE CODE IN \
ENGLISH even when the paragraph is in another language. Name the ISSUE, not the position taken \
on it - the stance field carries the position. Prefer wording that another submission raising \
the same issue would also produce, so codes merge across documents.
- stance: the submitter's position on that issue.
    support               - endorses the Guidelines' approach
    oppose                - disagrees with or rejects it
    request_clarification - asks the EDPB to clarify or define something
    propose_change        - proposes specific new/amended text or an addition
    concern               - flags a risk or adverse consequence without outright opposing
    other                 - none of the above (e.g. purely descriptive context)
- claim: one sentence stating the submitter's actual position on this issue, in English.
- target: the specific provision referenced, e.g. "para 137", "Article 89(1)", "Recital 159", \
or null if none is cited."""


def build_user_message(batch: pd.DataFrame) -> str:
    parts = []
    for i, row in enumerate(batch.itertuples()):
        parts.append(f"--- Paragraph {i} ---\n{row.text}")
    return "\n\n".join(parts)


def code_batch(client: anthropic.Anthropic, batch: pd.DataFrame, batch_key: str, force: bool) -> list[dict]:
    cache_path = CACHE_DIR / f"{batch_key}.json"
    if cache_path.exists() and not force:
        payload = json.loads(cache_path.read_text())
    else:
        # Adaptive thinking's token spend varies run to run (observed ~6.8k-7.3k on this
        # corpus) and occasionally lands close enough to max_tokens that the JSON gets cut
        # off mid-string - retrying with fresh sampling reliably resolves it.
        last_error = None
        payload = None
        for attempt in range(3):
            try:
                response = client.messages.parse(
                    model=MODEL,
                    max_tokens=16000,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": build_user_message(batch)}],
                    output_format=BatchCoding,
                )
                if response.parsed_output is None:
                    raise ValueError(f"parsed_output is None (stop_reason={response.stop_reason})")
                payload = response.parsed_output.model_dump()
                break
            except Exception as e:
                last_error = e
        if payload is None:
            raise last_error
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    paragraph_ids = batch["paragraph_id"].tolist()
    submission_ids = batch["submission_id"].tolist()

    rows = []
    for coding in payload["paragraphs"]:
        idx = coding["index"]
        if not 0 <= idx < len(paragraph_ids):
            # Model echoed an index outside the batch; skip rather than mis-attribute a code.
            print(f"  WARN batch {batch_key}: out-of-range index {idx}, skipped")
            continue
        for code in coding["codes"]:
            rows.append({
                "paragraph_id": paragraph_ids[idx],
                "submission_id": submission_ids[idx],
                "code": code["code"].strip().lower(),
                "stance": code["stance"],
                "claim": code["claim"],
                "target": code["target"],
            })
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only code the first N paragraphs (testing)")
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--workers", type=int, default=8, help="Concurrent API requests")
    parser.add_argument("--force", action="store_true", help="Ignore cached batch responses")
    args = parser.parse_args()

    df = pd.read_parquet(OUTPUT_DIR / "paragraphs.parquet")
    df = df[df["unit_type"] == "paragraph"].reset_index(drop=True)
    if args.limit:
        df = df.head(args.limit)

    client = anthropic.Anthropic(max_retries=5)

    batches = [df.iloc[i:i + args.batch_size] for i in range(0, len(df), args.batch_size)]
    # Key on the paragraph ids so cached batches stay valid if --limit/order changes.
    keyed = [(f"{b['paragraph_id'].iloc[0]}_{b['paragraph_id'].iloc[-1]}", b) for b in batches]

    all_rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(code_batch, client, batch, key, args.force): key
            for key, batch in keyed
        }
        for future in tqdm(as_completed(futures), total=len(futures), desc="Coding paragraphs"):
            key = futures[future]
            try:
                all_rows.extend(future.result())
            except Exception as e:
                print(f"FAILED batch {key}: {e}")

    # Batches complete out of order under concurrency; sort so output/code_ids are reproducible.
    codes = pd.DataFrame(all_rows).sort_values(["paragraph_id", "code"]).reset_index(drop=True)
    codes.insert(0, "code_id", range(len(codes)))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "codes_raw.parquet"
    codes.to_parquet(out_path, index=False)

    n_coded = codes["paragraph_id"].nunique()
    print(f"\nWrote {len(codes)} codes over {n_coded} paragraphs to {out_path}")
    print(f"Paragraphs with >=1 code: {n_coded}/{len(df)} ({100 * n_coded / len(df):.1f}%)")
    print(f"Distinct raw code strings: {codes['code'].nunique()}")
    print(codes["stance"].value_counts())


if __name__ == "__main__":
    main()
