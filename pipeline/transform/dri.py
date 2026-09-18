"""Parse snapshotted DRI / NY Forward round pages into award rows.

Two page layouts exist on ny.gov: newer rounds group communities under an ``<h2>`` per
region with the community name in ``<p><strong>Name</strong></p>``; round one lists
``Region – Community`` links. Both are handled. The award amount is read from the page when
a ``$N million`` figure sits in the community's own paragraphs, otherwise the program's
standard award applies and the row says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
REGION_NAMES = {
    "Capital Region",
    "Central New York",
    "Finger Lakes",
    "Long Island",
    "Mid-Hudson",
    "Mohawk Valley",
    "New York City",
    "North Country",
    "Southern Tier",
    "Western New York",
}
MILLION = re.compile(r"\$\s?(\d+(?:\.\d+)?)\s*million", re.IGNORECASE)
# Award sizes the two programs have actually paid. Any other "$N million" on a page is a
# project total or a private-investment figure, not the award.
AWARD_SIZES = {2_250_000, 4_500_000, 10_000_000, 20_000_000}
NOT_A_COMMUNITY = re.compile(r"press release|application|plan\b|brochure|guidebook", re.IGNORECASE)


@dataclass
class Award:
    program: str
    round: int
    region: str
    community: str
    amount: int | None
    amount_source: str
    source_key: str = ""


@dataclass
class _Block:
    tag: str
    text: str
    strong_only: bool


class _Collector(HTMLParser):
    """Flattens the page into (tag, text, strong_only) blocks for h2, p and a elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self._stack: list[list[str]] = []
        self._tags: list[str] = []
        self._strong_depth = 0
        self._strong_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h2", "h3", "p", "li"}:
            self._stack.append([])
            self._tags.append(tag)
            self._strong_text = []
        if tag in {"strong", "b"} and self._stack:
            self._strong_depth += 1
        if tag == "br" and self._stack:
            self._stack[-1].append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"strong", "b"} and self._strong_depth:
            self._strong_depth -= 1
        if tag in {"h2", "h3", "p", "li"} and self._stack and self._tags[-1] == tag:
            parts = self._stack.pop()
            self._tags.pop()
            text = re.sub(r"[ \t]+", " ", "".join(parts)).strip()
            strong = re.sub(r"\s+", " ", "".join(self._strong_text)).strip()
            self.blocks.append(_Block(tag, text, strong_only=bool(text) and text == strong))
            self._strong_text = []

    def handle_data(self, data: str) -> None:
        if self._stack:
            self._stack[-1].append(data)
            if self._strong_depth:
                self._strong_text.append(data)


def round_number(slug_or_title: str) -> int:
    text = slug_or_title.lower()
    match = re.search(r"round[-\s]+(\d+|[a-z]+)", text)
    if not match:
        raise ValueError(f"no round number in {slug_or_title!r}")
    token = match.group(1)
    return int(token) if token.isdigit() else WORD_NUMBERS[token]


def _looks_like_community(text: str) -> bool:
    return (
        0 < len(text) <= 70
        and "." not in text
        and text not in REGION_NAMES
        and not NOT_A_COMMUNITY.search(text)
    )


def parse_round_page(
    html: str, *, program: str, round_no: int, standard_award: int, source_key: str = ""
) -> list[Award]:
    collector = _Collector()
    collector.feed(html)
    blocks = collector.blocks
    awards: list[Award] = []

    # Layout A: h2 region headings, then <p><strong>Community</strong></p> blocks.
    region = ""
    current: Award | None = None
    for block in blocks:
        if block.tag == "h2" and block.text in REGION_NAMES:
            region = block.text
            current = None
            continue
        if not region:
            continue
        if block.tag in {"p", "h3"} and block.strong_only and _looks_like_community(block.text):
            current = Award(
                program, round_no, region, block.text, standard_award, "program_standard"
            )
            current.source_key = source_key
            awards.append(current)
            continue
        if current is not None and block.tag == "p":
            for found in MILLION.finditer(block.text):
                amount = int(round(float(found.group(1)) * 1_000_000))
                if amount in AWARD_SIZES and current.amount_source == "program_standard":
                    current.amount = amount
                    current.amount_source = "page"
                    break
    if awards:
        return awards

    # Layout B: "Region – Community" lines (round one).
    pattern = re.compile(
        r"^(" + "|".join(map(re.escape, sorted(REGION_NAMES))) + r")\s*[–—-]\s*(.+)$"
    )
    for block in blocks:
        for line in block.text.split("\n"):
            match = pattern.match(line.strip())
            if match:
                awards.append(
                    Award(
                        program,
                        round_no,
                        match.group(1),
                        match.group(2).strip(),
                        standard_award,
                        "program_standard",
                        source_key,
                    )
                )
    return awards
