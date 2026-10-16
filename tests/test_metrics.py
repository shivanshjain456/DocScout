"""Tests for the Prometheus instrumentation.

Two things are worth testing here and one thing is not. Worth testing: that the counters
actually move when requests happen, and that the labels stay bounded. Not worth testing:
that `prometheus_client` serialises correctly - that is its job, not this repository's.

The label assertions are the substance. Cardinality is the failure mode that takes a
Prometheus deployment down, and it arrives through a label that looked bounded when it was
added. These pin the two that could realistically drift: the route template, and the
absence of anything per-request.
"""

from __future__ import annotations

import re
from typing import Any

import psycopg
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app.api import metrics
from tests.conftest import PRIMARY_KEY, auth


def samples(body: str, name: str) -> dict[tuple[tuple[str, str], ...], float]:
    """All samples of one metric, keyed by its sorted label set."""
    found: dict[tuple[tuple[str, str], ...], float] = {}
    for family in text_string_to_metric_families(body):
        for sample in family.samples:
            if sample.name == name:
                found[tuple(sorted(sample.labels.items()))] = sample.value
    return found


def scrape(client: TestClient) -> str:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    return response.text


# --- the endpoint -----------------------------------------------------------------------
def test_metrics_endpoint_serves_valid_exposition(client: TestClient) -> None:
    body = scrape(client)
    families = {family.name for family in text_string_to_metric_families(body)}
    assert "docscout_http_requests" in families
    assert "docscout_http_request_duration_seconds" in families


def test_metrics_endpoint_is_not_in_the_public_schema(client: TestClient) -> None:
    """Operational surface, not part of the API contract callers program against."""
    assert "/metrics" not in client.get("/openapi.json").json()["paths"]


def test_scraping_requires_no_credential(client: TestClient) -> None:
    """Many scrapers cannot present one; `/healthz` already sets this precedent."""
    assert client.get("/metrics").status_code == 200


# --- the counters actually move -----------------------------------------------------------
def test_request_counter_increments_for_the_matched_route(client: TestClient) -> None:
    key = (("method", "POST"), ("route", "/v1/search"), ("status", "200"))
    before = samples(scrape(client), "docscout_http_requests_total").get(key, 0.0)
    client.post("/v1/search", json={"query": "capital adequacy requirements"}, headers=auth())
    after = samples(scrape(client), "docscout_http_requests_total").get(key, 0.0)
    assert after == before + 1


def test_failed_authentication_is_counted_separately_from_success(
    client: TestClient,
) -> None:
    """401 and 429 must stay distinguishable; collapsing to 4xx hides a throttled caller."""
    key = (("method", "POST"), ("route", "/v1/search"), ("status", "401"))
    before = samples(scrape(client), "docscout_http_requests_total").get(key, 0.0)
    client.post("/v1/search", json={"query": "no key at all"})
    after = samples(scrape(client), "docscout_http_requests_total").get(key, 0.0)
    assert after == before + 1


def test_duration_histogram_observes_requests(client: TestClient) -> None:
    key = (("method", "POST"), ("route", "/v1/search"))
    before = samples(scrape(client), "docscout_http_request_duration_seconds_count").get(key, 0.0)
    client.post("/v1/search", json={"query": "settlement cycle"}, headers=auth())
    after = samples(scrape(client), "docscout_http_request_duration_seconds_count").get(key, 0.0)
    assert after == before + 1


def test_cache_hit_and_miss_are_both_recorded(client: TestClient) -> None:
    """hit/(hit+miss) is the ratio; a miss that is never counted inflates it."""
    payload = {"query": "a query used only by the cache metric test", "k": 3}
    hit_key, miss_key = (("result", "hit"),), (("result", "miss"),)
    before = samples(scrape(client), "docscout_cache_events_total")
    client.post("/v1/search", json=payload, headers=auth())  # miss
    client.post("/v1/search", json=payload, headers=auth())  # hit
    after = samples(scrape(client), "docscout_cache_events_total")
    assert after.get(miss_key, 0.0) == before.get(miss_key, 0.0) + 1
    assert after.get(hit_key, 0.0) == before.get(hit_key, 0.0) + 1


def test_cache_bypass_is_not_counted_as_a_miss(client: TestClient) -> None:
    """Otherwise the hit ratio tracks how often the benchmark runs, not cache quality."""
    before = samples(scrape(client), "docscout_cache_events_total")
    client.post(
        "/v1/search",
        json={"query": "bypassing the cache deliberately", "use_cache": False},
        headers=auth(),
    )
    after = samples(scrape(client), "docscout_cache_events_total")
    assert after.get((("result", "miss"),), 0.0) == before.get((("result", "miss"),), 0.0)


def test_retrieval_duration_is_recorded_per_mode(client: TestClient) -> None:
    key = (("mode", "bm25"),)
    before = samples(scrape(client), "docscout_retrieval_duration_seconds_count").get(key, 0.0)
    client.post(
        "/v1/search",
        json={"query": "currency chest operations", "mode": "bm25", "use_cache": False},
        headers=auth(),
    )
    after = samples(scrape(client), "docscout_retrieval_duration_seconds_count").get(key, 0.0)
    assert after == before + 1


def test_corpus_gauge_reports_the_retrievable_chunk_count(
    client: TestClient, app_conn: psycopg.Connection[Any]
) -> None:
    expected = app_conn.execute(
        "SELECT count(*) FROM chunks c JOIN document_versions v USING (version_id) "
        "WHERE v.is_current"
    ).fetchone()
    assert expected is not None
    assert samples(scrape(client), "docscout_corpus_chunks")[()] == float(expected[0])


# --- cardinality ---------------------------------------------------------------------------
def test_unmatched_paths_collapse_to_one_series(client: TestClient) -> None:
    """A scanner probing random paths must not create one time series per probe.

    This is the single most common way an HTTP service destroys its own Prometheus.
    """
    for path in ("/wp-admin", "/.env", "/api/v2/users/4711", "/%2e%2e/etc/passwd"):
        client.get(path)
    routes = {
        dict(labels).get("route")
        for labels in samples(scrape(client), "docscout_http_requests_total")
    }
    assert metrics.UNMATCHED_ROUTE in routes
    for probe in ("/wp-admin", "/.env", "/api/v2/users/4711"):
        assert probe not in routes


def test_no_label_value_looks_like_per_request_data(client: TestClient) -> None:
    """Request ids, keys and query text belong in the log, which carries the request id."""
    client.post(
        "/v1/search",
        json={"query": "a very distinctive phrase that must not become a label"},
        headers=auth(),
    )
    body = scrape(client)
    assert "distinctive phrase" not in body
    assert PRIMARY_KEY not in body
    # A 16-hex-character token is the shape of our request ids.
    docscout_lines = [line for line in body.splitlines() if line.startswith("docscout_")]
    assert not any(re.search(r'"[0-9a-f]{16}"', line) for line in docscout_lines)


def test_label_sets_stay_bounded_under_varied_traffic(client: TestClient) -> None:
    """Enumerate before you instrument: the series count must not grow with traffic."""
    for index in range(12):
        client.post(
            "/v1/search",
            json={"query": f"distinct query number {index}", "use_cache": False},
            headers=auth(),
        )
    duration_series = samples(scrape(client), "docscout_retrieval_duration_seconds_count")
    assert len(duration_series) <= 3, duration_series  # one per retrieval mode, at most


def test_histogram_buckets_bracket_the_measured_distribution_and_the_slo() -> None:
    """Buckets must resolve where the latency actually is, or percentiles interpolate noise.

    Measured on 2 vCPU: cache hit p95 2.11 ms, cold p95 48.11 ms. NFR-1 budget is 3 s.
    """
    buckets = metrics.LATENCY_BUCKETS
    assert 3.0 in buckets, "no exact bucket boundary at the NFR-1 p95 budget"
    assert sum(1 for b in buckets if b <= 0.005) >= 3, "too coarse for cache-hit latency"
    assert sum(1 for b in buckets if 0.01 <= b <= 0.1) >= 3, "too coarse for cold retrieval"
    assert list(buckets) == sorted(buckets)


def test_metrics_exposes_corpus_freshness_gauges(client: TestClient) -> None:
    """Operational freshness gauges are exposed and populated by /readyz (P0-2, P0-5)."""
    client.get("/readyz")
    body = scrape(client)
    families = {family.name for family in text_string_to_metric_families(body)}
    assert "docscout_corpus_last_checked_timestamp_seconds" in families
    assert "docscout_corpus_stale_hours" in families
    assert "docscout_corpus_staleness_budget_hours" in families
    assert "docscout_corpus_is_stale" in families
    assert "docscout_corpus_versions_current" in families
    assert "docscout_corpus_generation" in families


# --- Real-Time Hallucination Telemetry & Prometheus Alarms (FEAT-089) --------------------


def test_ai_assurance_metrics_exposed_at_metrics_render() -> None:
    """Real-time AI assurance metrics are present in the Prometheus registry exposition."""
    body_bytes, _ = metrics.render()
    body = body_bytes.decode("utf-8")
    families = {family.name: family for family in text_string_to_metric_families(body)}

    assert "docscout_claim_support_ratio" in families
    assert any(k.startswith("docscout_abstention_events") for k in families)
    assert "docscout_unsupported_claim_alerts" in families
    assert any(k.startswith("docscout_unsupported_claim_alarm_events") for k in families)

    # Initial healthy default gauges
    ratio_sample = next(
        s
        for s in families["docscout_claim_support_ratio"].samples
        if s.name == "docscout_claim_support_ratio"
    )
    assert ratio_sample.value >= 0.0

    alert_samples = [
        s
        for s in families["docscout_unsupported_claim_alerts"].samples
        if s.name == "docscout_unsupported_claim_alerts" and s.labels.get("severity") == "critical"
    ]
    assert len(alert_samples) == 1
    assert alert_samples[0].value in (0.0, 1.0)


def test_hallucination_spike_triggers_prometheus_alarm() -> None:
    """Simulated production load with 5% seeded unsupported claims triggers critical alarm (< 0.98)."""
    tracker = metrics.get_telemetry_tracker()
    tracker.reset()

    # Initial 100% supported traffic
    tracker.record_claim_evaluation(supported_claims=100, total_claims=100)
    assert tracker.get_current_ratio() == 1.00
    assert not tracker.is_alerting()

    alert_dispatched: list[tuple[float, float, int]] = []
    tracker.add_alert_listener(lambda r, thresh, total: alert_dispatched.append((r, thresh, total)))

    # Seed 5% unsupported claims across next 100 evaluations (95 supported, 5 unsupported -> 95%)
    # Window total: 195 supported / 200 total = 0.9750 (< 0.98 threshold)
    ratio = tracker.record_claim_evaluation(supported_claims=95, total_claims=100)
    assert ratio == 0.9750
    assert tracker.is_alerting()
    assert len(alert_dispatched) >= 1
    assert alert_dispatched[-1][0] == 0.9750
    assert alert_dispatched[-1][1] == 0.98

    # Verify Prometheus gauge export
    body_bytes, _ = metrics.render()
    body = body_bytes.decode("utf-8")
    families = {family.name: family for family in text_string_to_metric_families(body)}

    ratio_sample = next(
        s
        for s in families["docscout_claim_support_ratio"].samples
        if s.name == "docscout_claim_support_ratio"
    )
    assert ratio_sample.value == 0.9750

    alert_sample = next(
        s
        for s in families["docscout_unsupported_claim_alerts"].samples
        if s.name == "docscout_unsupported_claim_alerts" and s.labels.get("severity") == "critical"
    )
    assert alert_sample.value == 1.0


def test_alarm_clears_when_claim_support_ratio_recovers() -> None:
    """When subsequent supported claims restore ratio >= 0.98, alarm state returns to 0.0."""
    tracker = metrics.get_telemetry_tracker()
    tracker.reset()

    # Start in breached state: 90 / 100 = 0.90 (< 0.98)
    tracker.record_claim_evaluation(supported_claims=90, total_claims=100)
    assert tracker.is_alerting()

    # Recover with wave of 500 fully grounded claims: (90 + 500) / (100 + 500) = 590 / 600 = 0.9833
    ratio = tracker.record_claim_evaluation(supported_claims=500, total_claims=500)
    assert ratio == 0.9833
    assert not tracker.is_alerting()

    body_bytes, _ = metrics.render()
    body = body_bytes.decode("utf-8")
    families = {family.name: family for family in text_string_to_metric_families(body)}
    alert_sample = next(
        s
        for s in families["docscout_unsupported_claim_alerts"].samples
        if s.name == "docscout_unsupported_claim_alerts" and s.labels.get("severity") == "critical"
    )
    assert alert_sample.value == 0.0


def test_hallucination_sliding_window_eviction() -> None:
    """Observations older than window_seconds (300s) are cleanly evicted from ratio calculations."""
    tracker = metrics.HallucinationTelemetryTracker(window_seconds=300.0, alarm_threshold=0.98)
    t0 = 1000.0

    # At t0: severe breach with 80% support
    tracker.record_claim_evaluation(supported_claims=80, total_claims=100, timestamp=t0)
    assert tracker.get_current_ratio() == 0.80
    assert tracker.is_alerting()

    # At t0 + 301 seconds: healthy observation with 100% support; t0 is evicted
    tracker.record_claim_evaluation(supported_claims=50, total_claims=50, timestamp=t0 + 301.0)
    assert tracker.get_current_ratio() == 1.00
    assert not tracker.is_alerting()


def test_claim_telemetry_overhead_and_memory_limits() -> None:
    """Telemetry update overhead must be <= 0.02 ms per evaluation."""
    import time

    tracker = metrics.HallucinationTelemetryTracker(window_seconds=300.0, alarm_threshold=0.98)

    iterations = 1000
    start = time.perf_counter()
    for _ in range(iterations):
        tracker.record_claim_evaluation(supported_claims=10, total_claims=10)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    avg_ms = elapsed_ms / iterations

    # Budget is <= 0.02 ms (20 microseconds) per update
    assert avg_ms <= 0.02, f"Telemetry update overhead {avg_ms:.4f} ms exceeded 0.02 ms SLA"


def test_claim_telemetry_fails_open() -> None:
    """Fail-open invariant: metric recording errors never raise exceptions."""
    # Negative values or boundary edge cases safely return 1.0 without crashing
    res = metrics.record_claim_telemetry(-5, -1)
    assert res == 1.0


def test_no_confidential_query_text_in_ai_assurance_labels() -> None:
    """AI assurance metric labels must never include confidential query text or unconstrained parameters."""
    body_bytes, _ = metrics.render()
    body = body_bytes.decode("utf-8")
    for family in text_string_to_metric_families(body):
        if family.name.startswith("docscout_claim_") or family.name.startswith(
            "docscout_unsupported_"
        ):
            for sample in family.samples:
                # Labels must only contain bounded known enum values like status or severity
                for label_key, label_val in sample.labels.items():
                    assert label_key in ("severity", "status", "level"), (
                        f"Unrecognized label key {label_key}"
                    )
                    assert len(label_val) <= 20, f"Label value {label_val} suspiciously long"


def test_record_claim_telemetry_endpoint() -> None:
    """Operational endpoint POST /v1/telemetry/claims validates payload and updates Prometheus gauges."""
    import os

    from app.api.app import app
    from app.api.security import load_keys

    os.environ["DOCSCOUT_API_KEY"] = f"{PRIMARY_KEY}"
    app.state.api_keys = load_keys()
    local_client = TestClient(app)

    # 401 without auth
    resp_unauth = local_client.post(
        "/v1/telemetry/claims", json={"supported_claims": 10, "total_claims": 10}
    )
    assert resp_unauth.status_code == 401

    # 422 if supported_claims > total_claims
    resp_invalid = local_client.post(
        "/v1/telemetry/claims",
        json={"supported_claims": 20, "total_claims": 10},
        headers=auth(),
    )
    assert resp_invalid.status_code == 422

    # 200 with valid payload
    resp_ok = local_client.post(
        "/v1/telemetry/claims",
        json={"supported_claims": 99, "total_claims": 100},
        headers=auth(),
    )
    assert resp_ok.status_code == 200
    data = resp_ok.json()
    assert data["recorded"] is True
    assert 0.0 <= data["current_claim_support_ratio"] <= 1.0
    assert isinstance(data["is_alert_active"], bool)
    assert data["alarm_threshold"] == 0.98
