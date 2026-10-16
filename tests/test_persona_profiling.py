"""Tests for Persona-Tailored Query Profiling (FEAT-020).

Verifies canonical profiles, shorthand aliases, heuristic query intent inference,
retrieval configuration adaptation, API endpoint integration, cache isolation,
and Prometheus metrics instrumentation.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api import metrics
from app.api.app import _config_for, app
from app.api.models import SearchRequest
from app.api.security import load_keys
from app.retrieval.persona import PersonaProfiler, get_default_persona_profiler
from app.retrieval.types import MetadataFilter, RetrievalConfig
from tests.conftest import PRIMARY_KEY, ROTATION_KEY, auth


@pytest.fixture
def profiler() -> PersonaProfiler:
    return get_default_persona_profiler()


def test_canonical_profiles_registered(profiler: PersonaProfiler) -> None:
    """Verify all 4 canonical personas exist with expected baseline settings."""
    profiles = profiler.list_profiles()
    assert len(profiles) == 4
    profile_ids = {p.id for p in profiles}
    assert profile_ids == {
        "fintech_developer",
        "statutory_auditor",
        "risk_officer",
        "compliance_officer",
    }

    # Fintech Developer
    dev = profiler.get_profile("fintech_developer")
    assert dev is not None
    assert dev.name == "Fintech Developer"
    assert dev.weight_dense == 1.0
    assert dev.weight_lexical == 1.0
    assert dev.default_expansion_mode == "synonym"
    assert dev.default_difficulty_band == "intermediate"
    assert "delivery-and-platform" in dev.preferred_layers

    # Statutory Auditor
    auditor = profiler.get_profile("statutory_auditor")
    assert auditor is not None
    assert auditor.name == "Statutory Auditor"
    assert auditor.weight_dense == 0.7
    assert auditor.weight_lexical == 1.5
    assert auditor.default_expansion_mode == "none"
    assert auditor.default_difficulty_band == "expert"
    assert "quality-and-verification" in auditor.preferred_layers

    # Risk Officer
    risk = profiler.get_profile("risk_officer")
    assert risk is not None
    assert risk.name == "Chief Risk Officer"
    assert risk.weight_dense == 1.2
    assert risk.weight_lexical == 0.8
    assert risk.centrality_weight == 0.25
    assert risk.default_expansion_mode == "hyde"
    assert risk.default_difficulty_band == "advanced"

    # Compliance Officer
    comp = profiler.get_profile("compliance_officer")
    assert comp is not None
    assert comp.name == "Compliance Officer"
    assert comp.weight_dense == 1.0
    assert comp.weight_lexical == 1.2
    assert comp.default_expansion_mode == "combined"
    assert comp.auto_constrain_tags is True


def test_alias_resolution(profiler: PersonaProfiler) -> None:
    """Verify shorthand user input strings map to canonical IDs correctly."""
    # Aliases
    assert profiler.resolve_persona_id("dev") == "fintech_developer"
    assert profiler.resolve_persona_id("developer") == "fintech_developer"
    assert profiler.resolve_persona_id("software_engineer") == "fintech_developer"
    assert profiler.resolve_persona_id("auditor") == "statutory_auditor"
    assert profiler.resolve_persona_id("audit") == "statutory_auditor"
    assert profiler.resolve_persona_id("chartered_accountant") == "statutory_auditor"
    assert profiler.resolve_persona_id("cro") == "risk_officer"
    assert profiler.resolve_persona_id("risk") == "risk_officer"
    assert profiler.resolve_persona_id("chief_risk_officer") == "risk_officer"
    assert profiler.resolve_persona_id("compliance") == "compliance_officer"
    assert profiler.resolve_persona_id("cco") == "compliance_officer"

    # None / Empty / General
    assert profiler.resolve_persona_id(None) is None
    assert profiler.resolve_persona_id("") is None
    assert profiler.resolve_persona_id("   ") is None
    assert profiler.resolve_persona_id("general") is None
    assert profiler.resolve_persona_id("none") is None
    assert profiler.resolve_persona_id("default") is None

    # Unknown
    assert profiler.resolve_persona_id("unknown_persona_xyz") is None


def test_query_keyword_inference(profiler: PersonaProfiler) -> None:
    """Verify heuristic keyword inference matches characteristic queries."""
    # Developer cues
    assert (
        profiler.infer_persona("REST API endpoint payload schema for tokenisation webhook")
        == "fintech_developer"
    )

    # Auditor cues
    assert (
        profiler.infer_persona("Section 45 penal provisions fine for contravention inspection")
        == "statutory_auditor"
    )

    # Risk Officer cues
    assert (
        profiler.infer_persona("Capital adequacy CRAR LCR stress test systemic risk")
        == "risk_officer"
    )

    # Compliance Officer cues
    assert (
        profiler.infer_persona("Master Direction KYC AML due diligence reporting timeline")
        == "compliance_officer"
    )

    # Non-matching / Empty
    assert profiler.infer_persona("What is the general concept?") is None
    assert profiler.infer_persona("") is None


def test_apply_to_config_defaults(profiler: PersonaProfiler) -> None:
    """Verify applying a persona adapts RetrievalConfig parameters."""
    base_config = RetrievalConfig(
        name="test_base",
        mode="hybrid",
        k_dense=20,
        k_lexical=20,
        k_final=5,
        weight_dense=1.0,
        weight_lexical=1.0,
        difficulty_band=None,
        expansion_mode="none",
        expand_query=False,
    )

    adapted, profile = profiler.apply_to_config("statutory_auditor", base_config)
    assert profile is not None
    assert profile.id == "statutory_auditor"
    assert adapted.name == "test_base:statutory_auditor"
    assert adapted.weight_dense == 0.7
    assert adapted.weight_lexical == 1.5
    assert adapted.rrf_k == 50
    assert adapted.centrality_weight == 0.05
    assert adapted.difficulty_band == "expert"
    assert adapted.filter is not None
    assert adapted.filter.taxonomy_layers == [
        "physical-and-regulated",
        "quality-and-verification",
    ]


def test_apply_to_config_explicit_overrides(profiler: PersonaProfiler) -> None:
    """Verify explicit request parameters take precedence over persona defaults."""
    base_config = RetrievalConfig(
        name="test_base",
        mode="hybrid",
        k_dense=20,
        k_lexical=20,
        k_final=5,
        difficulty_band=None,
    )

    # Explicit difficulty overrides profile's default
    adapted, profile = profiler.apply_to_config(
        "risk_officer",
        base_config,
        explicit_difficulty="beginner",
        explicit_expansion="synonym",
        explicit_auto_tags=True,
    )
    assert profile is not None
    assert profile.id == "risk_officer"
    assert adapted.difficulty_band == "beginner"  # Overridden from 'advanced'
    assert adapted.expansion_mode == "synonym"  # Overridden from 'hyde'
    assert adapted.auto_constrain_tags is True


def test_apply_to_config_existing_filter(profiler: PersonaProfiler) -> None:
    """Verify applying persona preserves existing filter attributes and adds layers."""
    existing_filter = MetadataFilter(source="RBI", tags=["kyc"])
    base_config = RetrievalConfig(
        name="test_base",
        filter=existing_filter,
    )

    adapted, _ = profiler.apply_to_config("fintech_developer", base_config)
    assert adapted.filter is not None
    assert adapted.filter.source == "RBI"
    assert adapted.filter.tags == ["kyc"]
    assert adapted.filter.taxonomy_layers == [
        "architecture-and-data",
        "delivery-and-platform",
        "product-and-interface",
    ]


def test_apply_to_config_none(profiler: PersonaProfiler) -> None:
    """Verify applying None persona leaves configuration untouched."""
    base_config = RetrievalConfig(name="original")
    adapted, profile = profiler.apply_to_config(None, base_config)
    assert profile is None
    assert adapted == base_config


def test_config_for_persona_resolution() -> None:
    """Verify _config_for in app.py integrates with PersonaProfiler correctly."""
    req_dev = SearchRequest(query="test query", persona="fintech_developer")
    cfg_dev, prof_dev = _config_for(req_dev)
    assert prof_dev is not None
    assert prof_dev.id == "fintech_developer"
    assert cfg_dev.weight_dense == 1.0
    assert cfg_dev.weight_lexical == 1.0

    req_aud = SearchRequest(query="test query", persona="statutory_auditor")
    cfg_aud, prof_aud = _config_for(req_aud)
    assert prof_aud is not None
    assert prof_aud.id == "statutory_auditor"
    assert cfg_aud.weight_dense == 0.7
    assert cfg_aud.weight_lexical == 1.5

    req_none = SearchRequest(query="test query", persona=None)
    cfg_none, prof_none = _config_for(req_none)
    assert prof_none is None
    assert cfg_none.name == "hybrid-rrf"


def test_api_list_personas_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify GET /v1/search/personas endpoint authentication and data structure."""
    monkeypatch.setenv("DOCSCOUT_API_KEY", f"{PRIMARY_KEY},{ROTATION_KEY}")
    app.state.api_keys = load_keys()
    client = TestClient(app)

    # 401 without auth
    resp_unauth = client.get("/v1/search/personas")
    assert resp_unauth.status_code == 401

    # 200 with auth
    headers = auth(PRIMARY_KEY)
    resp = client.get("/v1/search/personas", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["total"] == 4
    assert len(data["personas"]) == 4
    ids = [p["id"] for p in data["personas"]]
    assert "fintech_developer" in ids
    assert "statutory_auditor" in ids
    assert "risk_officer" in ids
    assert "compliance_officer" in ids

    # Validate detailed structure of first persona
    p0 = data["personas"][0]
    for key in (
        "id",
        "name",
        "title",
        "description",
        "target_audience",
        "weight_dense",
        "weight_lexical",
        "rrf_k",
        "default_expansion_mode",
        "centrality_weight",
        "preferred_layers",
        "auto_constrain_tags",
    ):
        assert key in p0


def test_live_search_endpoint_with_persona(
    client: TestClient, app_conn: psycopg.Connection[Any]
) -> None:
    """If live DB is running, POST /v1/search accepts persona and applies tuned profile."""
    headers = auth(PRIMARY_KEY)

    # Search with persona="statutory_auditor"
    before = metrics.PERSONA_QUERIES_TOTAL.labels(persona_id="statutory_auditor")._value.get()
    req = {
        "query": "Section 45-IA net owned fund statutory requirement",
        "persona": "statutory_auditor",
        "k": 3,
        "use_cache": False,
    }
    resp = client.post("/v1/search", json=req, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["persona"] == "statutory_auditor"
    assert data["persona_applied"] is not None
    assert data["persona_applied"]["id"] == "statutory_auditor"
    assert data["persona_applied"]["weight_lexical"] == 1.5

    after = metrics.PERSONA_QUERIES_TOTAL.labels(persona_id="statutory_auditor")._value.get()
    assert after == before + 1


def test_live_search_cache_isolation_by_persona(
    client: TestClient, app_conn: psycopg.Connection[Any]
) -> None:
    """If live DB is running, identical queries under different personas isolate cache entries."""
    headers = auth(PRIMARY_KEY)
    query_text = "capital adequacy liquidity framework"

    # Search 1: Risk Officer
    req1 = {"query": query_text, "persona": "risk_officer", "k": 2, "use_cache": True}
    resp1 = client.post("/v1/search", json=req1, headers=headers)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["persona"] == "risk_officer"
    assert data1["persona_applied"]["id"] == "risk_officer"

    # Search 2: Fintech Developer (same query, cache enabled)
    req2 = {"query": query_text, "persona": "fintech_developer", "k": 2, "use_cache": True}
    resp2 = client.post("/v1/search", json=req2, headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["persona"] == "fintech_developer"
    assert data2["persona_applied"]["id"] == "fintech_developer"
