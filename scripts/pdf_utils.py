"""Shared PDF text-extraction helpers used by extract_metadata.py and extract_paragraphs.py."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SUBMISSION_ID_RE = re.compile(r"^(\d+)-")

# Lines that are almost certainly boilerplate (salutations/signature blocks), not argument text.
BOILERPLATE_PATTERNS = [
    re.compile(r"^\s*(dear|to the attention of|alla cortese attenzione)\b", re.I),
    re.compile(r"^\s*(yours (sincerely|faithfully)|best regards|kind regards|sincerely)\s*,?\s*$", re.I),
    re.compile(r"^\s*(cordialement|cordiali saluti|met vriendelijke groet)\s*,?\s*$", re.I),
    re.compile(r"^\s*page\s+\d+\s*(of|/)\s*\d+\s*$", re.I),
    re.compile(r"^\s*\d+\s*\(\s*\d+\s*\)\s*$"),  # "1 (6)" style page markers
]


@dataclass
class TextBlock:
    page: int
    order: int
    text: str
    bbox: tuple


def list_pdfs(data_dir: Path = DATA_DIR) -> list[Path]:
    return sorted(data_dir.glob("*.pdf"))


def submission_id_from_filename(path: Path) -> str:
    match = SUBMISSION_ID_RE.match(path.name)
    if not match:
        raise ValueError(f"Filename does not start with a numeric submission id: {path.name}")
    return match.group(1)


def extract_first_pages_text(path: Path, max_pages: int = 2) -> str:
    """Plain text of the first N pages, for metadata extraction."""
    with fitz.open(path) as doc:
        pages = doc[: min(max_pages, doc.page_count)]
        return "\n".join(page.get_text("text") for page in pages)


def extract_full_text(path: Path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text("text") for page in doc)


def extract_text_blocks(path: Path) -> list[TextBlock]:
    """Text blocks per page in reading order, as given by PyMuPDF's block layout analysis.

    A PyMuPDF "block" roughly corresponds to a paragraph (contiguous lines grouped by
    layout), which is a much better paragraph-boundary signal than blank-line splitting.
    """
    blocks: list[TextBlock] = []
    with fitz.open(path) as doc:
        for page_num, page in enumerate(doc):
            raw_blocks = page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, block_type)
            for order, b in enumerate(raw_blocks):
                text = b[4].strip()
                if not text:
                    continue
                if b[6] != 0:  # skip non-text (image) blocks
                    continue
                blocks.append(TextBlock(page=page_num, order=order, text=text, bbox=tuple(b[:4])))
    return blocks


def is_boilerplate(text: str) -> bool:
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return True
    # A block that's just a handful of very short lines (address/letterhead/signature blocks).
    if len(lines) <= 4 and all(len(l.strip()) < 60 for l in lines):
        for pattern in BOILERPLATE_PATTERNS:
            if pattern.search(text):
                return True
    for pattern in BOILERPLATE_PATTERNS:
        if pattern.match(text.strip()):
            return True
    return False


def page_count(path: Path) -> int:
    with fitz.open(path) as doc:
        return doc.page_count
