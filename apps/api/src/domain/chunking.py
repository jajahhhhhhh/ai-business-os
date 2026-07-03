"""Thai/English-aware text chunking for KB ingestion (pure, deterministic).

Splitting order: paragraph breaks first, then lines, then sentence-ish
delimiters, then whitespace, then (only for unbroken runs, e.g. long Thai
text with no spaces) hard character slices. A line is never split unless it
alone exceeds the target. Adjacent chunks share an overlap: each chunk after
the first starts with the tail of its predecessor.

TARGET_CHARS = 1800: bge-m3 (and Thai text generally) tokenizes mixed
Thai/English at roughly 3-4 characters per token, so 1800 characters lands
near the 512-token embedding sweet spot without truncation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TARGET_CHARS = 1800
OVERLAP_CHARS = 200

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
# Sentence-ish boundaries: EN terminal punctuation, CJK full stop, Thai
# paiyannoi (ฯ) / mai yamok (ๆ) followed by whitespace, or space clusters —
# Thai delimits phrases with spaces rather than full stops.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?;。ฯๆ])\s+|\s{2,}")
_ANY_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Chunk:
    """One chunk of a document; seq is the 0-based position within it."""

    seq: int
    text: str


def _hard_slices(text: str, target: int) -> list[str]:
    """Last resort for delimiter-free runs: fixed-width character slices."""
    return [text[i : i + target] for i in range(0, len(text), target)]


def _split_line(line: str, target: int) -> list[str]:
    """Split a single line into pieces of at most `target` characters.

    Descends sentence boundaries -> any whitespace -> hard slices, and only
    as far as needed, so a line is never split when it already fits.
    """
    if len(line) <= target:
        return [line]
    pieces: list[str] = []
    for sentence in _SENTENCE_BOUNDARY.split(line):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= target:
            pieces.append(sentence)
            continue
        for word_run in _ANY_WHITESPACE.split(sentence):
            if not word_run:
                continue
            if len(word_run) <= target:
                pieces.append(word_run)
            else:
                pieces.extend(_hard_slices(word_run, target))
    return pieces


def _segments(text: str, target: int) -> list[tuple[str, str]]:
    """Flatten text into (joiner, piece) segments, each piece <= target.

    The joiner is what precedes the piece when it is concatenated after the
    previous piece inside the same chunk: "\\n\\n" between paragraphs, "\\n"
    between lines, " " between sub-line pieces.
    """
    segments: list[tuple[str, str]] = []
    for paragraph in _PARAGRAPH_BREAK.split(text):
        first_line_of_paragraph = True
        for line in paragraph.split("\n"):
            line = line.strip()
            if not line:
                continue
            for index, piece in enumerate(_split_line(line, target)):
                if not segments:
                    joiner = ""
                elif index > 0:
                    joiner = " "
                elif first_line_of_paragraph:
                    joiner = "\n\n"
                else:
                    joiner = "\n"
                segments.append((joiner, piece))
            first_line_of_paragraph = False
    return segments


def _overlap_tail(text: str, overlap: int) -> str:
    """Suffix of `text` (at most `overlap` chars) to prepend to the next chunk.

    Aligned forward to the first whitespace so an English word is not cut in
    half; a delimiter-free Thai run keeps the raw character tail.
    """
    if overlap <= 0 or not text:
        return ""
    raw = text[-overlap:]
    if len(raw) < len(text):  # cut mid-text: drop the partial leading word
        match = _ANY_WHITESPACE.search(raw)
        if match:
            raw = raw[match.end() :]
    return raw.strip()


def chunk_text(
    text: str, target_chars: int = TARGET_CHARS, overlap_chars: int = OVERLAP_CHARS
) -> list[Chunk]:
    """Chunk `text` into pieces of at most `target_chars` characters.

    Deterministic, no empty chunks; each chunk after the first begins with an
    overlap taken verbatim from the end of the previous chunk (capped at half
    the target so overlap can never crowd out new content).
    """
    if target_chars <= 0:
        raise ValueError("target_chars must be positive")
    overlap_chars = max(0, min(overlap_chars, target_chars // 2))

    segments = _segments(text, target_chars)
    if not segments:
        return []

    chunks: list[str] = []
    current = ""
    for joiner, piece in segments:
        if not current:
            current = piece
            continue
        if len(current) + len(joiner) + len(piece) <= target_chars:
            current += joiner + piece
            continue
        chunks.append(current)
        tail = _overlap_tail(current, overlap_chars)
        # Overlap is best-effort: dropped when it would push past the target.
        if tail and len(tail) + 1 + len(piece) <= target_chars:
            current = tail + " " + piece
        else:
            current = piece
    if current:
        chunks.append(current)

    return [Chunk(seq=seq, text=body) for seq, body in enumerate(chunks)]
