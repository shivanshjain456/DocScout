"""Regulatory taxonomy and ontology loader (FEAT-002).

Provides access to canonical regulatory terminology, statutory hierarchy structures,
and domain classifications across RBI, SEBI, and PMLA frameworks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def load_taxonomy_data(custom_path: Path | str | None = None) -> dict[str, Any]:
    """Load taxonomy definition file if present, returning empty dictionary otherwise."""
    if custom_path is not None:
        p = Path(custom_path)
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)  # type: ignore[no-any-return]
            except Exception as exc:
                logger.warning("taxonomy_load_failed", path=str(p), error=str(exc))
                return {}

    # Check root workspace path if available
    default_tax_path = Path(__file__).resolve().parents[3] / "do not commit!" / "term-taxonomy.json"
    if default_tax_path.exists():
        try:
            with open(default_tax_path, encoding="utf-8") as f:
                return json.load(f)  # type: ignore[no-any-return]
        except Exception as exc:
            logger.debug("default_taxonomy_not_loaded", error=str(exc))

    return {}
