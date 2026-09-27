"""Keyword-based work classification.

Notes are split into activity lines (bullets). Each line is matched against the
active classification rules; the highest-priority matching keyword wins (ties
go to the longer keyword). An entry's hours are split evenly across its lines,
which makes category hours an estimate derived from what was written.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.init_db import UNCATEGORIZED
from backend.models import ClassificationRule, WorkCategory

WEAK_PRIORITY = 40  # generic words like "update"/"sheet" defer to a matching heading
BULLET = re.compile(r"^\s*(?:[-–—•*·▪►]|\d+[.)]|[a-z][.)])\s*", re.I)


@dataclass
class Rule:
    keyword: str
    category_id: int
    priority: int
    pattern: re.Pattern


@dataclass
class SplitNotes:
    title: str | None
    activities: list[str]


def normalize_activity(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:500]


def split_notes(notes: str | None) -> SplitNotes:
    """Split notes into an optional title and a list of activity lines.

    "Co-ordination task\\n-SO Release\\n-Kanban checking" ->
        title="Co-ordination task", activities=["SO Release", "Kanban checking"]
    """
    if not notes:
        return SplitNotes(None, [])
    lines = [ln.strip() for ln in notes.split("\n") if ln.strip()]
    bullet_idx = [i for i, ln in enumerate(lines) if BULLET.match(ln)]
    if not bullet_idx:
        # No bullets: one line = one activity; several lines = several activities
        if len(lines) == 1:
            return SplitNotes(None, lines)
        parts = [p.strip() for p in re.split(r"[;\n]", notes) if p.strip()]
        return SplitNotes(None, parts)
    title_lines = lines[: bullet_idx[0]]
    activities: list[str] = []
    for ln in lines[bullet_idx[0]:]:
        stripped = BULLET.sub("", ln).strip()
        if BULLET.match(ln) or not activities:
            if stripped:
                activities.append(stripped)
        else:  # continuation of previous bullet
            activities[-1] = f"{activities[-1]} {stripped}"
    title = " ".join(title_lines).strip() or None
    return SplitNotes(title, activities)


class Classifier:
    def __init__(self, db: Session):
        self.rules: list[Rule] = []
        for r in db.scalars(select(ClassificationRule).where(ClassificationRule.active.is_(True))):
            kw = r.keyword.strip().lower()
            if not kw:
                continue
            # word boundaries, flexible spacing, optional plural ("drawing" matches "drawings")
            pattern = re.compile(r"(?<![a-z0-9])" + re.escape(kw).replace(r"\ ", r"[\s\-_]*") + r"(?:s|es)?(?![a-z0-9])", re.I)
            self.rules.append(Rule(kw, r.category_id, r.priority, pattern))
        self.rules.sort(key=lambda r: (-r.priority, -len(r.keyword)))
        uncategorized = db.scalar(select(WorkCategory).where(WorkCategory.name == UNCATEGORIZED))
        self.uncategorized_id = uncategorized.id if uncategorized else None

    def classify(self, text: str | None) -> tuple[int | None, str | None]:
        """Return (category_id, matched_keyword); uncategorized when nothing matches."""
        cat, kw, _ = self.classify_full(text)
        return cat, kw

    def classify_full(self, text: str | None) -> tuple[int | None, str | None, int]:
        """Like classify(), also returning the winning rule's priority (-1 when nothing matched)."""
        if text:
            for rule in self.rules:  # already sorted: first match wins
                if rule.pattern.search(text):
                    return rule.category_id, rule.keyword, rule.priority
        return self.uncategorized_id, None, -1
