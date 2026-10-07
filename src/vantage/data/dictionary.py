"""Optional data dictionary (YAML) describing column meanings, relationships and
gotchas. The schema tells the model *what exists*; the dictionary tells it *what
things mean* - which sharply improves SQL accuracy. Entirely optional: a foreign
database with no dictionary still works from introspected names alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_dictionary(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def format_dictionary(data: dict[str, Any]) -> str:
    """Render the dictionary into a compact block for the LLM prompt."""
    if not data:
        return ""
    lines: list[str] = []

    for table, meta in (data.get("tables") or {}).items():
        meta = meta or {}
        desc = meta.get("description", "")
        grain = meta.get("grain")
        header = f"- {table}: {desc}"
        if grain:
            header += f" (grain: {grain})"
        lines.append(header)
        for col, col_desc in (meta.get("columns") or {}).items():
            lines.append(f"    - {col}: {col_desc}")

    relationships = data.get("relationships") or []
    if relationships:
        lines.append("Relationships:")
        lines.extend(f"    - {rel}" for rel in relationships)

    notes = data.get("notes") or []
    if notes:
        lines.append("Query notes:")
        lines.extend(f"    - {note}" for note in notes)

    return "\n".join(lines)
