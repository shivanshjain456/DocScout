"""Regulatory taxonomy and ontology loader (FEAT-002, FEAT-007).

Provides access to canonical regulatory terminology, statutory hierarchy structures,
domain classifications across RBI, SEBI, and PMLA frameworks, and definition dictionaries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_CACHED_DICTIONARY: dict[str, dict[str, Any]] | None = None


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


def get_taxonomy_dictionary() -> dict[str, dict[str, Any]]:
    """Return dictionary of terms and entities for dynamic UI definition tooltips (FEAT-007)."""
    global _CACHED_DICTIONARY
    if _CACHED_DICTIONARY is not None:
        return _CACHED_DICTIONARY

    dictionary: dict[str, dict[str, Any]] = {}

    # 1. Load from lexicon.json if present
    lex_path = Path(__file__).resolve().parents[3] / "do not commit!" / "lexicon.json"
    if lex_path.exists():
        try:
            with open(lex_path, encoding="utf-8") as f:
                data = json.load(f)
            for t in data.get("terms", []):
                tid = t.get("id")
                term_name = t.get("term")
                if not tid or not term_name:
                    continue
                dictionary[tid] = {
                    "id": tid,
                    "term": term_name,
                    "definition": t.get("definition", ""),
                    "layer": t.get("layer", ""),
                    "source": t.get("source", ""),
                    "aliases": t.get("acronyms", []),
                    "related": t.get("related", [])[:5],
                }
        except Exception as exc:
            logger.warning("lexicon_load_failed", error=str(exc))

    # 2. Enrich with statutory entities from FEAT-002
    try:
        from app.retrieval.entity_linker import STATUTORY_ENTITIES

        for entity in STATUTORY_ENTITIES:
            eid = entity.entity_id
            if eid not in dictionary:
                dictionary[eid] = {
                    "id": eid,
                    "term": entity.canonical_name,
                    "definition": (
                        f"Canonical {entity.canonical_name} classified under statutory "
                        f"{entity.statutory_source} framework."
                    ),
                    "layer": "physical-and-regulated",
                    "source": entity.statutory_source,
                    "aliases": list(entity.aliases),
                    "related": list(entity.parent_ids + entity.child_ids)[:5],
                }
    except Exception as exc:
        logger.warning("statutory_entities_enrich_failed", error=str(exc))

    _CACHED_DICTIONARY = dictionary
    return dictionary
