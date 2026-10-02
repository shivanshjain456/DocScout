"""Tests for the Prometheus instrumentation.

Two things are worth testing here and one thing is not. Worth testing: that the counters
actually move when requests happen, and that the labels stay bounded. Not worth testing:
that `prometheus_client` serialises correctly — that is its job, not this repository's.

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
