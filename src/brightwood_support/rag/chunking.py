"""Split markdown help articles into retrievable chunks.

One section (a heading and its text) is one chunk, so a retrieved chunk is a
complete rule. Very long sections are split on paragraph boundaries.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    id: str       # "<doc>#<heading-slug>", e.g. "auto_collision#deductible"
    doc: str      # file name without extension
    heading: str  # the section heading
    text: str     # the section text, without the heading line


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _split_long(text: str, max_words: int) -> list[str]:
    """Split on blank lines so no piece is much longer than max_words."""
    pieces: list[str] = []
    current: list[str] = []
    count = 0
    for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
        words = len(para.split())
        if current and count + words > max_words:
            pieces.append("\n\n".join(current))
            current, count = [], 0
        current.append(para)
        count += words
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def chunk_markdown(doc: str, text: str, max_words: int = 120) -> list[Chunk]:
    """Turn one markdown document into chunks, one per non-empty section."""
    sections: list[tuple[str, list[str]]] = []
    heading = "intro"
    body: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            sections.append((heading, body))
            heading, body = match.group(2).strip(), []
        else:
            body.append(line)
    sections.append((heading, body))

    chunks: list[Chunk] = []
    for heading, lines in sections:
        section_text = "\n".join(lines).strip()
        if not section_text:
            continue  # title-only or empty sections carry no rule
        pieces = _split_long(section_text, max_words)
        for n, piece in enumerate(pieces):
            suffix = "" if n == 0 else f"-{n + 1}"
            chunks.append(
                Chunk(
                    id=f"{doc}#{slug(heading)}{suffix}",
                    doc=doc,
                    heading=heading,
                    text=piece,
                )
            )
    return chunks


def load_corpus(folder: str | Path, max_words: int = 120) -> list[Chunk]:
    """Chunk every .md file in a folder, in a stable (sorted) order."""
    chunks: list[Chunk] = []
    for path in sorted(Path(folder).glob("*.md")):
        chunks.extend(chunk_markdown(path.stem, path.read_text(encoding="utf-8"), max_words))
    return chunks
