# EDPB Draft Guidelines 1/2026 — Consultation Explorer

This repository analyses the 132 written submissions to the EDPB's public consultation on
**Draft Guidelines 1/2026 (GDPR and scientific research)**. An LLM reads every paragraph of every
submission, names the individual arguments it raises, and those arguments are clustered (not the
raw text) into a browsable hierarchy of **themes → subthemes → issues**, each with a
support/oppose/concern stance breakdown and quotes linked back to the original PDF.

The pipeline turns the raw PDFs in `data/` into the static site published in `docs/` (served by
GitHub Pages):

- `docs/index.html` — the theme explorer (landing page)
- `docs/dashboard.html` — a one-page stance overview across all themes
- `docs/methods.html` — how this was built and its limitations (hand-written)

Since the themes are extracted with an LLM, the results are useful for exploring the submissions
quickly but don't match a proper human-led thematic analysis.

## Data

`data/` is git-ignored — the raw submissions aren't checked into this repo, so a fresh clone
starts with an empty pipeline. To reproduce the analysis from scratch, populate `data/` with:

- `data/<submission_id>-<slug>.pdf` — one PDF per submission, filename starting with a numeric
  ID followed by a hyphen (e.g. `10912-feedback_1527_statement-postl-...pdf`). The leading
  `\d+-` is required — `scripts/pdf_utils.py` parses the submission ID from it.
- `data/metadata.html` — a saved copy of the `<table class="cols-5">` fragment from the EDPB's
  public consultation-feedback page, listing each submission's date, submitter type, country,
  submitter name, and a link to its PDF.

If you only want to rebuild the published site from the existing analysis rather than rerun the
LLM steps, you can skip `data/` entirely: `output/*.parquet`/`*.xlsx` are committed, so you can
jump straight to steps 7–8 below.

## Setup

Requires [conda](https://docs.conda.io) or [mamba](https://mamba.readthedocs.io). The project
environment lives in-repo at `./env` (gitignored) rather than in the usual conda envs directory.

```bash
mamba create python=3.11 -p ./env
./env/bin/pip install \
    anthropic pandas numpy pymupdf langdetect leidenalg igraph \
    scikit-learn sentence-transformers torch tqdm pydantic openpyxl plotly
```

Then run scripts with `./env/bin/python scripts/<script>.py`, or activate the environment first:

```bash
mamba activate ./env
python scripts/<script>.py
```

### LLM API key

The extraction and naming steps call the Claude API via the `anthropic` SDK, which picks up
credentials from the `ANTHROPIC_API_KEY` environment variable automatically. Put your key in a
file (already gitignored) and export it before running any script that needs it:

```bash
echo "sk-ant-..." > ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY=$(cat ANTHROPIC_API_KEY)
```

## Pipeline

Run from the repository root, in this order. Every LLM-backed step caches its raw responses
under `cache/`, so a rerun without `--force` only calls the API for new/changed input.

| # | Script | Needs API key? | Reads | Writes |
|---|--------|:---:|-------|--------|
| 1 | `extract_paragraphs.py` | no | `data/*.pdf` | `output/paragraphs.parquet` — one row per paragraph/heading unit |
| 2 | `extract_metadata.py` | yes | `data/*.pdf` | `output/metadata.xlsx` — org, country, authors per submission (LLM-inferred) |
| 3 | `parse_source_metadata.py` | no | `data/metadata.html` + `data/*.pdf` filenames | `output/metadata_groundtruth.xlsx` — authoritative submission date/type/country scraped from the EDPB site |
| 4 | `extract_codes.py` | yes | `output/paragraphs.parquet` | `output/codes_raw.parquet` — 0-5 short atomic codes + stance per paragraph |
| 5 | `build_codebook.py` | yes | `output/codes_raw.parquet` | `output/codes.parquet`, `output/codebook.xlsx` — near-duplicate codes merged into a canonical codebook |
| 6 | `build_themes.py` | yes | `output/codes.parquet`, `output/codebook.xlsx`, `output/metadata.xlsx` | `output/themes.xlsx`, `output/codes.xlsx`, `output/theme_tree.json` — multi-level theme hierarchy |
| 7 | `build_explorer.py` | no | `output/theme_tree.json` | `docs/index.html` |
| 8 | `build_dashboard.py` | no | `output/themes.xlsx` | `docs/dashboard.html` |
| 9 | `build_language_metadata.py` | no | `output/paragraphs.parquet`, `output/metadata_groundtruth.xlsx`, `output/metadata.xlsx` | `output/submission_languages.xlsx` — each submission's dominant language (by character share) plus a `notes` column flagging mixed-language documents |

```bash
python scripts/extract_paragraphs.py
python scripts/extract_metadata.py
python scripts/parse_source_metadata.py
python scripts/build_language_metadata.py
python scripts/extract_codes.py
python scripts/build_codebook.py
python scripts/build_themes.py
python scripts/build_explorer.py
python scripts/build_dashboard.py
```

Step 9 only needs steps 1–3's output (paragraph text plus both metadata tables), so it's placed
there in the run order, but it doesn't feed into steps 4–8 — it's a standalone manual-QC report,
not a pipeline dependency. See "Manual quality control" below for how to use it.

Steps 2, 4, 5, 6 call the Claude API (`MODEL = "claude-sonnet-5"`) and require
`ANTHROPIC_API_KEY`. `MODEL` is a literal repeated separately in each of those four scripts,
not a shared config value — change it in all four if you switch models. Steps 5 and 6 also embed
text locally with `sentence-transformers` (`intfloat/multilingual-e5-large`) and run Leiden
clustering — no API key needed for that part, but the model download and clustering can be slow
on first run.

Most scripts accept `--force` to ignore the cache and reprocess everything, and some accept
`--limit N` (process only the first N items, for a quick smoke test) — see each script's
module docstring (`python scripts/<script>.py --help`) for its exact options.

`docs/methods.html` is written by hand, not generated by a script.

## Reusing this pipeline for another consultation

The code is written for this one consultation, not as a generic tool — reusing it for a
different (or future) public consultation means finding and rewriting the parts below, not just
re-running the same scripts on new PDFs:

- **Filename convention.** `SUBMISSION_ID_RE = r"^(\d+)-"` in `scripts/pdf_utils.py` parses the
  submission ID from the filename prefix — update it to match however the new source names its
  downloaded files.
- **Source-site scraping.** `parse_source_metadata.py` hardcodes the EDPB's site
  (`BASE_URL = "https://www.edpb.europa.eu"`), the exact `<table class="cols-5">` layout of its
  feedback page, and a filename-suffix join trick that only works because of how EDPB names its
  linked PDFs. For a consultation hosted elsewhere, expect to rewrite this script, not just tweak
  a constant.
- **LLM prompts.** Every prompt names this specific consultation and must be rewritten for a new
  topic: the system prompt in `extract_metadata.py`, `SYSTEM_PROMPT` (including the stance
  definitions) in `extract_codes.py`, the naming prompt in `build_codebook.py`, and
  `NAMING_PROMPT` in `build_themes.py`.
- **Hardcoded submission count.** The figure "132" is written directly into page copy rather than
  computed — `build_explorer.py` (title, subtitle, meta description) and `site_header.py`
  (builder note) all need updating for a corpus of a different size.
- **Branding and URLs.** `site_header.py`'s `BASE_URL` (the GitHub Pages URL used for canonical/
  social-preview links) and its eyebrow/`og:site_name` text are specific to this repo and topic.
  `build_explorer.py` and `build_dashboard.py` also have a `LINKEDIN_URL` placeholder — both
  print a build-time warning if it's never been filled in, so watch for that warning on a fresh
  fork.
- **Controlled vocabularies.** `ORG_TYPES` in `extract_metadata.py` and `STANCES` in
  `extract_codes.py` are usable defaults but were chosen for this consultation's submitter mix
  and argument framing — review whether they still fit before reusing them as-is.
- **Clustering parameters.** The Leiden `--resolution`/`--knn` defaults in `build_codebook.py`
  and `build_themes.py` were hand-tuned by inspecting this corpus's embeddings; they are not
  expected to generalize to a different corpus. Re-tune them and inspect the result (see
  "Manual quality control" below) rather than trusting the defaults.
- **`docs/methods.html`** is hand-written prose describing this run, not a template — a new
  consultation needs its own methods page written by hand.

## Manual quality control

The pipeline is LLM-heavy and needs human verification before its output is trusted or
published. What to check, roughly in the order you'd hit it:

- **Language detection.** After step 9, review `output/submission_languages.xlsx`: check any row
  whose `notes` column flags it as mixed-language (`language_share < 0.85`), and manually confirm
  the language of any submission with little or no extractable text (a scanned/image-only PDF) by
  rendering its pages and reading them, then recording the result in `NO_TEXT_LAYER_LANGUAGE` in
  `build_language_metadata.py`. This isn't theoretical: the first language count reported for
  this consultation (21, from raw per-paragraph `langdetect` codes, mostly single-paragraph
  misdetections) was wrong, and this per-submission, character-weighted check is what produced
  the corrected figure (6).
- **Non-English coding quality is unverified.** The LLM codes non-English paragraphs directly, in
  the source language; nobody has had a bilingual reviewer independently check those codes for
  accuracy. Spot-check a sample of non-English paragraphs against their codes before treating
  them as equally reliable as the English ones.
- **Duplicate names in the codebook.** The LLM naming pass in `build_codebook.py` can give
  identical names to genuinely distinct merged code clusters — skim `output/codebook.xlsx` for
  repeated names and confirm they're not masking different issues.
- **Clustering resolution is hand-tuned, not principled.** After rerunning on new data, inspect
  cluster sizes in `output/theme_tree.json`/`output/codebook.xlsx` for obvious over- or
  under-merging and adjust `--resolution`/`--knn` — don't assume the checked-in defaults transfer.
- **Stance counts are descriptive, not a vote.** Submissions to a public consultation aren't a
  representative sample and don't carry equal weight — don't present stance tallies as if they
  were poll results.
- **Reruns aren't guaranteed identical.** LLM output isn't deterministic across calls; the
  `cache/` directory (git-ignored) is what makes a specific published run reproducible.
  Regenerating from scratch without that cache may shift exact wording or cluster boundaries even
  when the overall conclusions hold.
- **Before publishing a fork:** confirm `LINKEDIN_URL` and `BASE_URL` have been updated (the
  build scripts warn if `LINKEDIN_URL` is still a placeholder), and avoid committing Excel lock
  files (`~$*.xlsx`) that Excel/LibreOffice leave behind while a workbook is open.
