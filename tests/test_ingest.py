"""Ingestion tests — each one named for the requirement it proves.

These cover M2's exit criterion 2 (off-allowlist rejection, stub-page rejection,
hash de-duplication, new-version creation with stable old chunk IDs, idempotent re-run)
and criterion 3 (refusal to start with deploy credentials), plus the invariants ADR-0003
and ADR-0004 made the pipeline responsible for.

The database tests run as **`docscout_app`**, the least-privilege role the service really
uses, inside a transaction that is always rolled back. That is deliberate: it proves the
whole write path works with SELECT/INSERT/UPDATE and no DELETE and no DDL, rather than
proving it works as the owner and hoping.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import psycopg
import pytest

from app.ingest.allowlist import ALLOWED_HOSTS, assert_allowed, is_synthetic
from app.ingest.chunk import MAX_TOKENS, chunk_document, uncovered_characters, verify_offsets
from app.ingest.clean import clean_char_count, clean_preserving_offsets
from app.ingest.embed import EMBEDDING_DIM, QUERY_PREFIX, Embedder
from app.ingest.errors import (
    CredentialBleedError,
    DisallowedHostError,
    ShortExtractionError,
)
from app.ingest.extract import (
    MIN_CLEAN_CHARS,
    assert_extraction_long_enough,
    extract,
    normalise_whitespace,
)
from app.ingest.fetch import fetch_url
from app.ingest.guards import DEPLOY_CREDENTIAL_VARS, assert_no_deploy_credentials
from app.ingest.pipeline import prepare_document, run_ingest
from app.ingest.source import (
    DEFAULT_MANIFEST,
    ManifestError,
    SourceDocument,
    _media_type_for,
    iter_manifest_documents,
)
from app.ingest.store import Action, row_counts, store_document

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "corpus" / "raw"
FIXTURES = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
class StubEmbedder(Embedder):
    """Deterministic stand-in so the database tests never load a 128 MB model.

    Subclasses the real `Embedder` and overrides only the two methods that touch the
    model, so every type signature and every caller path is the production one.
    """

    def __init__(self) -> None:
        super().__init__(model_id="stub-embedder-384")

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed)
            vector = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
            out[row] = vector / np.linalg.norm(vector)
        return out


def synthetic_source_document(
    *, url: str, body: str, sha: str | None = None, source: str = "RBI"
) -> SourceDocument:
    content = body.encode()
    return SourceDocument(
        url=url,
        source=source,
        sha256=sha or hashlib.sha256(content).hexdigest(),
        content=content,
        media_type="text/plain",
        fetch_ts=datetime.now(UTC),
        http_status=200,
        detail_page=None,
        authority="Reserve Bank of India",
        is_injection_canary=False,
    )


def long_body(marker: str, repeats: int = 120) -> str:
    """Text comfortably over FR-3's floor, with a marker so versions differ."""
    return f"Reserve Bank of India circular {marker}. " * repeats


class _ExplodingTransport(httpx.BaseTransport):
    """Fails loudly if anything tries to open a connection."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"a network call was attempted to {request.url}")


@pytest.fixture(scope="session")
def real_embedder() -> Embedder:
    embedder = Embedder()
    try:
        embedder.count_tokens("warm up")
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"embedding model unavailable: {exc}")
    return embedder


# --------------------------------------------------------------------------------------
# FR-1 / C-1 — the host allowlist, enforced before any socket is opened
# --------------------------------------------------------------------------------------
def test_fr1_off_allowlist_host_is_rejected_before_any_network_call() -> None:
    client = httpx.Client(transport=_ExplodingTransport())
    with pytest.raises(DisallowedHostError, match="allowlist"):
        fetch_url("https://evil.example/circular.pdf", client=client)


def test_fr1_userinfo_cannot_smuggle_an_allowed_host_past_the_check() -> None:
    """`https://www.rbi.org.in@evil.example/` resolves to evil.example, not RBI."""
    with pytest.raises(DisallowedHostError):
        assert_allowed("https://www.rbi.org.in@evil.example/x.pdf")


def test_fr1_plaintext_http_is_refused_even_for_an_allowed_host() -> None:
    with pytest.raises(DisallowedHostError, match="scheme"):
        assert_allowed("http://www.rbi.org.in/x.pdf")


def test_fr1_every_allowlisted_host_is_accepted_over_https() -> None:
    for host in ALLOWED_HOSTS:
        assert assert_allowed(f"https://{host}/some/document.pdf") == host


def test_fr1_a_redirect_off_the_allowlist_is_refused_mid_flight() -> None:
    """An allowed host answering 302 to elsewhere must not be followed."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.rbi.org.in":
            return httpx.Response(302, headers={"location": "https://evil.example/payload.pdf"})
        raise AssertionError("followed a redirect off the allowlist")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(DisallowedHostError):
        fetch_url("https://www.rbi.org.in/start.pdf", client=client)


def test_fr1_a_redirect_within_the_allowlist_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start.pdf":
            return httpx.Response(302, headers={"location": "https://rbidocs.rbi.org.in/final.pdf"})
        return httpx.Response(
            200, content=b"%PDF-1.4 body", headers={"content-type": "application/pdf"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = fetch_url("https://www.rbi.org.in/start.pdf", client=client)
    assert result.url == "https://rbidocs.rbi.org.in/final.pdf"
    assert result.status_code == 200


def test_the_injection_canary_can_never_be_fetched_over_the_network() -> None:
    assert is_synthetic("synthetic://canary-001")
    with pytest.raises(DisallowedHostError, match="synthetic"):
        assert_allowed("synthetic://canary-001")


# --------------------------------------------------------------------------------------
# FR-6 / SECURITY S-4 — stage credential isolation
# --------------------------------------------------------------------------------------
def test_fr6_ingestion_refuses_to_start_with_deploy_credentials() -> None:
    with pytest.raises(CredentialBleedError, match="AWS_SECRET_ACCESS_KEY"):
        assert_no_deploy_credentials({"AWS_SECRET_ACCESS_KEY": "AKIA-not-a-real-secret"})


def test_fr6_the_error_names_the_variable_but_never_its_value() -> None:
    opaque_value = "this-value-must-not-be-echoed"
    with pytest.raises(CredentialBleedError) as caught:
        assert_no_deploy_credentials({"FLY_API_TOKEN": opaque_value})
    assert opaque_value not in str(caught.value)


def test_fr6_an_empty_variable_is_not_a_credential() -> None:
    """CI declares variables with no value when a secret is unavailable to a job."""
    assert_no_deploy_credentials({"AWS_ACCESS_KEY_ID": "", "KUBECONFIG": "   "})


def test_fr6_region_and_profile_selectors_are_not_treated_as_credentials() -> None:
    assert_no_deploy_credentials({"AWS_REGION": "ap-south-1", "AWS_PROFILE": "default"})
    assert not DEPLOY_CREDENTIAL_VARS & {"AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE"}


# --------------------------------------------------------------------------------------
# FR-3 / C-11 — the short-extraction guard, the pipeline's most dangerous failure mode
# --------------------------------------------------------------------------------------
def test_fr3_a_stub_page_is_rejected_rather_than_stored() -> None:
    """CORPUS_SPEC K-17: the SEBI detail page extracts ~227 characters and looks fine."""
    stub = FIXTURES / "sebi_detail_stub.html"
    extraction = extract(stub.read_bytes(), media_type="text/html")
    cleaned = clean_preserving_offsets(extraction.text)
    assert clean_char_count(cleaned) < MIN_CLEAN_CHARS, (
        "fixture no longer reproduces the stub-page failure mode"
    )
    with pytest.raises(ShortExtractionError, match="stub-page failure mode"):
        assert_extraction_long_enough(cleaned, url="https://www.sebi.gov.in/legal/x.html")


def test_fr3_the_floor_counts_non_whitespace_so_a_blanked_document_cannot_pass() -> None:
    """A scanned Devanagari PDF cleans to thousands of spaces; length alone would pass it."""
    devanagari = "\u0915\u0916\u0917 " * 900
    cleaned = clean_preserving_offsets(devanagari)
    assert len(cleaned) > 3000
    assert clean_char_count(cleaned) == 0
    with pytest.raises(ShortExtractionError):
        assert_extraction_long_enough(cleaned, url="https://rbidocs.rbi.org.in/scan.pdf")


def test_fr3_a_real_document_clears_the_floor() -> None:
    assert_extraction_long_enough(long_body("A"), url="https://rbidocs.rbi.org.in/ok.pdf")


# --------------------------------------------------------------------------------------
# ADR-0003 — cleaning preserves offsets; chunking preserves coverage and FR-7
# --------------------------------------------------------------------------------------
def test_adr0003_cleaning_never_moves_a_character() -> None:
    text = "RBI \u0915\u0916\u0917 circular \ufffd Page 3 of 9 end"
    cleaned = clean_preserving_offsets(text)
    assert len(cleaned) == len(text)
    assert "\u0915" not in cleaned
    assert "\ufffd" not in cleaned
    assert "Page 3 of 9" not in cleaned
    assert cleaned.index("circular") == text.index("circular")


def test_adr0003_normalise_whitespace_is_idempotent() -> None:
    once = normalise_whitespace("  a \n\n b \t c  ")
    assert once == "a b c"
    assert normalise_whitespace(once) == once


@pytest.mark.parametrize("size,overlap", [(1000, 150), (400, 60), (200, 0)])
def test_fr7_offsets_re_extract_to_stored_text_for_any_geometry(size: int, overlap: int) -> None:
    text = normalise_whitespace(long_body("offsets", repeats=200))
    chunks = chunk_document(text, lambda s: max(1, len(s) // 4), size=size, overlap=overlap)
    verify_offsets(text, chunks)
    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.text


def test_chunking_covers_every_non_whitespace_character() -> None:
    text = normalise_whitespace(long_body("coverage", repeats=300))
    chunks = chunk_document(text, lambda s: max(1, len(s) // 4))
    assert uncovered_characters(text, chunks) == 0


def test_chunking_produces_no_chunk_wholly_contained_in_another() -> None:
    """A trailing window that duplicates its predecessor indexes the same text twice."""
    text = normalise_whitespace(long_body("contained", repeats=150))
    spans = [(c.char_start, c.char_end) for c in chunk_document(text, lambda s: len(s) // 4)]
    for i, a in enumerate(spans):
        for j, b in enumerate(spans):
            if i != j:
                assert not (b[0] <= a[0] and a[1] <= b[1]), f"chunk {i} is contained in {j}"


def test_adr0002_a_token_dense_chunk_is_split_rather_than_truncated() -> None:
    """The ceiling must hold even when a 1,000-character window tokenises densely."""
    text = normalise_whitespace(long_body("ceiling", repeats=200))
    # One token per character forces every window far past 512.
    chunks = chunk_document(text, len)
    assert chunks, "expected chunks"
    assert all(c.token_count <= MAX_TOKENS for c in chunks)
    verify_offsets(text, chunks)
    assert uncovered_characters(text, chunks) == 0


def test_chunking_rejects_an_overlap_that_cannot_make_progress() -> None:
    with pytest.raises(ValueError, match="smaller than size"):
        chunk_document("abc", len, size=100, overlap=100)


# --------------------------------------------------------------------------------------
# ADR-0002 — the embedding contract
# --------------------------------------------------------------------------------------
def test_adr0002_embeddings_are_384_dimensional_unit_vectors(real_embedder: Embedder) -> None:
    vectors = real_embedder.encode_passages(["a regulatory paragraph", "another one"])
    assert vectors.shape == (2, EMBEDDING_DIM)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-4)


def test_adr0002_query_and_passage_encodings_differ_for_identical_text(
    real_embedder: Embedder,
) -> None:
    """The BGE prefix applies to queries only; if it leaked into passages these would match."""
    text = "capital adequacy requirements for scheduled commercial banks"
    passage = real_embedder.encode_passages([text])[0]
    query = real_embedder.encode_query(text)
    assert not np.allclose(passage, query, atol=1e-6)
    assert QUERY_PREFIX.strip()


def test_adr0002_token_count_includes_special_tokens(real_embedder: Embedder) -> None:
    """max_seq_length counts [CLS] and [SEP]; excluding them would under-measure by two."""
    assert real_embedder.count_tokens("hello") > len("hello".split())


# --------------------------------------------------------------------------------------
# the corpus manifest is a claim about files, and claims decay
# --------------------------------------------------------------------------------------
@pytest.mark.skipif(
    not (CORPUS_DIR / "manifest.json").is_file(), reason="corpus manifest not present"
)
def test_extraction_reproduces_every_recorded_char_count() -> None:
    """Pins extraction against Phase 0, which is what ADR-0003's sweep measured.

    `char_count` in the manifest is `len(normalise_whitespace(pypdf_text))`. If a pypdf
    upgrade or an edit to the normaliser changed that, chunk boundaries would move and
    ADR-0003's evidence would quietly stop describing the shipped pipeline.
    """
    records = json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))["documents"]
    checked = 0
    for record in records:
        local = REPO_ROOT / str(record["local_path"])
        if not local.is_file():
            pytest.skip("corpus payloads are not git-tracked and are absent")
        extraction = extract(local.read_bytes(), media_type=_media_type_for(local))
        assert len(extraction.text) == record["char_count"], record["local_path"]
        checked += 1
    assert checked == len(records)


@pytest.mark.skipif(
    not (CORPUS_DIR / "manifest.json").is_file(), reason="corpus manifest not present"
)
def test_a_payload_edited_after_fetch_is_refused(tmp_path: Path) -> None:
    """A manifest entry whose bytes no longer hash to the recorded digest must not load."""
    payload = tmp_path / "corpus" / "raw"
    payload.mkdir(parents=True)
    (payload / "doc.txt").write_text("tampered content")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "url": "https://rbidocs.rbi.org.in/a.pdf",
                        "source": "RBI",
                        "sha256": "0" * 64,
                        "local_path": "corpus/raw/doc.txt",
                        "fetch_ts": datetime.now(UTC).isoformat(),
                        "bytes": 16,
                        "ok": True,
                    }
                ]
            }
        )
    )
    with pytest.raises(ManifestError, match="changed after it was fetched"):
        list(iter_manifest_documents(manifest, repo_root=tmp_path))


@pytest.mark.skipif(not DEFAULT_MANIFEST.is_file(), reason="corpus manifest not present")
def test_every_manifest_url_is_on_the_allowlist_or_synthetic() -> None:
    for record in json.loads(DEFAULT_MANIFEST.read_text())["documents"]:
        url = str(record["url"])
        if not is_synthetic(url):
            assert_allowed(url)


# --------------------------------------------------------------------------------------
# FR-5 — de-duplicate by content hash first, then canonical URL
# --------------------------------------------------------------------------------------
def test_fr5_one_payload_under_two_urls_stores_one_document(
    ingest_db: psycopg.Connection[Any],
) -> None:
    embedder = StubEmbedder()
    body = long_body("dedup")
    first = synthetic_source_document(url="https://rbidocs.rbi.org.in/a.pdf", body=body)
    second = synthetic_source_document(url="https://rbidocs.rbi.org.in/b.pdf", body=body)
    assert first.sha256 == second.sha256

    before = row_counts(ingest_db)
    out_a = store_document(ingest_db, prepare_document(first, embedder))
    out_b = store_document(ingest_db, prepare_document(second, embedder))

    assert out_a.action is Action.INSERTED
    assert out_b.action is Action.SKIPPED_DUPLICATE_CONTENT
    assert out_b.chunks_written == 0
    after = row_counts(ingest_db)
    assert after["documents"] == before["documents"] + 1
    assert after["document_versions"] == before["document_versions"] + 1


# --------------------------------------------------------------------------------------
# FR-4 — a changed hash at a known URL is a new version, and old chunk IDs survive
# --------------------------------------------------------------------------------------
def test_fr4_changed_payload_creates_a_version_and_old_chunk_ids_still_resolve(
    ingest_db: psycopg.Connection[Any],
) -> None:
    embedder = StubEmbedder()
    url = "https://rbidocs.rbi.org.in/evolving.pdf"
    first = synthetic_source_document(url=url, body=long_body("version one"))
    out_first = store_document(ingest_db, prepare_document(first, embedder))
    assert out_first.action is Action.INSERTED

    old_ids = [
        row[0]
        for row in ingest_db.execute(
            "SELECT chunk_id FROM chunks WHERE version_id = %s", (out_first.version_id,)
        ).fetchall()
    ]
    assert old_ids

    second = synthetic_source_document(url=url, body=long_body("version two"))
    out_second = store_document(ingest_db, prepare_document(second, embedder))
    assert out_second.action is Action.SUPERSEDED
    assert out_second.document_id == out_first.document_id
    assert out_second.version_id != out_first.version_id

    # FR-4: the superseded version is retained and its chunk IDs still resolve.
    for chunk_id in old_ids:
        row = ingest_db.execute(
            "SELECT version_id FROM chunks WHERE chunk_id = %s", (chunk_id,)
        ).fetchone()
        assert row is not None
        assert row[0] == out_first.version_id

    current = ingest_db.execute(
        "SELECT version_id FROM document_versions WHERE document_id = %s AND is_current",
        (out_first.document_id,),
    ).fetchall()
    assert [r[0] for r in current] == [out_second.version_id]


# --------------------------------------------------------------------------------------
# NFR-8 — restartable and idempotent
# --------------------------------------------------------------------------------------
def test_nfr8_re_running_over_unchanged_input_writes_nothing(
    ingest_db: psycopg.Connection[Any],
) -> None:
    embedder = StubEmbedder()
    documents = [
        synthetic_source_document(
            url=f"https://rbidocs.rbi.org.in/n{i}.pdf", body=long_body(f"d{i}")
        )
        for i in range(3)
    ]

    first = run_ingest(documents, ingest_db, embedder)
    assert first.totals["inserted"] == 3
    assert first.wrote_anything

    second = run_ingest(documents, ingest_db, embedder)
    assert second.totals["skipped_unchanged"] == 3
    assert second.totals["chunks_written"] == 0
    assert second.counts_before == second.counts_after, "a re-run must write nothing"
    assert not second.wrote_anything


def test_nfr8_a_resumed_run_completes_the_remainder(
    ingest_db: psycopg.Connection[Any],
) -> None:
    """Interrupting after one document and resuming yields one copy of each."""
    embedder = StubEmbedder()
    documents = [
        synthetic_source_document(
            url=f"https://rbidocs.rbi.org.in/r{i}.pdf", body=long_body(f"r{i}")
        )
        for i in range(3)
    ]

    run_ingest(documents[:1], ingest_db, embedder)
    resumed = run_ingest(documents, ingest_db, embedder)

    assert resumed.totals["skipped_unchanged"] == 1
    assert resumed.totals["inserted"] == 2
    urls = ingest_db.execute(
        "SELECT canonical_url, count(*) FROM documents "
        "WHERE canonical_url LIKE 'https://rbidocs.rbi.org.in/r%%' GROUP BY 1"
    ).fetchall()
    assert all(count == 1 for _, count in urls)


def test_a_document_that_fails_the_guard_does_not_stop_the_run(
    ingest_db: psycopg.Connection[Any],
) -> None:
    """A bad document is counted and named; the rest of the corpus still ingests."""
    embedder = StubEmbedder()
    documents = [
        synthetic_source_document(url="https://rbidocs.rbi.org.in/good.pdf", body=long_body("ok")),
        synthetic_source_document(url="https://rbidocs.rbi.org.in/stub.pdf", body="too short"),
    ]
    report = run_ingest(documents, ingest_db, embedder)
    assert report.totals["failed"] == 1
    assert report.totals["inserted"] == 1
    failed = [d for d in report.documents if d.status == "failed"]
    assert "ShortExtractionError" in failed[0].detail


# --------------------------------------------------------------------------------------
# the stored result, read back
# --------------------------------------------------------------------------------------
def test_stored_chunks_satisfy_fr7_when_read_back_from_the_database(
    ingest_db: psycopg.Connection[Any],
) -> None:
    embedder = StubEmbedder()
    document = synthetic_source_document(
        url="https://rbidocs.rbi.org.in/readback.pdf", body=long_body("readback", repeats=200)
    )
    prepared = prepare_document(document, embedder)
    outcome = store_document(ingest_db, prepared)

    rows = ingest_db.execute(
        "SELECT text, char_start, char_end FROM chunks WHERE version_id = %s ORDER BY ordinal",
        (outcome.version_id,),
    ).fetchall()
    assert len(rows) == len(prepared.chunks)
    for text, start, end in rows:
        assert prepared.text[start:end] == text


def test_ingestion_works_with_no_delete_and_no_ddl_privilege(
    ingest_db: psycopg.Connection[Any],
) -> None:
    """The write path must need nothing beyond SELECT/INSERT/UPDATE (ADR-0004)."""
    role = ingest_db.execute("SELECT current_user").fetchone()
    assert role is not None and role[0] == "docscout_app"
    document = synthetic_source_document(
        url="https://rbidocs.rbi.org.in/leastpriv.pdf", body=long_body("priv")
    )
    outcome = store_document(ingest_db, prepare_document(document, StubEmbedder()))
    assert outcome.action is Action.INSERTED
    assert outcome.chunks_written > 0


# --------------------------------------------------------------------------------------
# regression — a crash after the data was already written is still a crash
# --------------------------------------------------------------------------------------
def test_report_path_display_survives_a_relative_report_dir(tmp_path: Path) -> None:
    """`--report-dir docs/x` once crashed the CLI *after* a successful 170-chunk ingest.

    `Path.relative_to` raises for a relative path that does not literally start with the
    repository prefix, so the run reported success to the database and a traceback to the
    operator. Cosmetic code on the success path still has to be total.
    """
    from app.ingest.__main__ import display_path

    assert display_path(Path("docs/corpus/evidence/run")) == "docs/corpus/evidence/run"
    assert display_path(REPO_ROOT / "corpus" / "reports") == "corpus/reports"
    assert display_path(tmp_path / "elsewhere") == str(tmp_path / "elsewhere")


# --- invisible / private-use character sanitisation (OWASP LLM09) ------------------------
# Measured on this corpus before the pass existed: four occurrences of U+F0E0, a Wingdings
# breadcrumb arrow in SEBI circulars ("under the link 'Legal <arrow> Circulars'"), two of
# them inside chunks the gold set cites. They were embedded, tokenised and served.
class TestInvisibleCharacters:
    def test_private_use_character_is_blanked(self) -> None:
        from app.ingest.clean import blank_invisible

        assert blank_invisible("Legal \uf0e0 Circulars") == "Legal   Circulars"

    @pytest.mark.parametrize(
        ("codepoint", "name"),
        [
            ("\u200b", "zero width space"),
            ("\u200d", "zero width joiner"),
            ("\ufeff", "byte order mark"),
            ("\u00ad", "soft hyphen"),
            ("\u202e", "right-to-left override"),
            ("\u2066", "left-to-right isolate"),
            ("\u2060", "word joiner"),
            ("\ue000", "private use area start"),
        ],
    )
    def test_each_invisible_class_is_blanked(self, codepoint: str, name: str) -> None:
        from app.ingest.clean import blank_invisible

        assert blank_invisible(f"a{codepoint}b") == "a b", name

    def test_legitimate_whitespace_and_text_survive(self) -> None:
        """Cc is deliberately excluded: newline and tab are structure, not noise."""
        from app.ingest.clean import blank_invisible

        text = "line one\n\tindented\r\nend \u00a0nbsp"
        assert blank_invisible(text) == text

    def test_blanking_is_length_preserving(self) -> None:
        """The property every chunk offset, chunk_id and pinned citation depends on."""
        from app.ingest.clean import blank_invisible

        text = "a\uf0e0b\u200bc\u202ed\ufeffe"
        assert len(blank_invisible(text)) == len(text)

    def test_clean_preserving_offsets_still_checks_its_invariant(self) -> None:
        from app.ingest.clean import clean_preserving_offsets

        text = "Legal \uf0e0 Circulars\u200b with \u0905 Devanagari and Page 2 of 9"
        assert len(clean_preserving_offsets(text)) == len(text)

    def test_text_with_nothing_to_blank_is_returned_unchanged(self) -> None:
        """The fast path must not allocate or alter a clean document."""
        from app.ingest.clean import blank_invisible

        text = "An ordinary SEBI circular paragraph."
        assert blank_invisible(text) is text

    def test_find_invisible_names_what_it_found(self) -> None:
        """Silent removal is how a corpus stops matching its source; this makes it auditable."""
        from app.ingest.clean import find_invisible

        found = find_invisible("Legal \uf0e0 x\u200b y\u200b")
        assert found["U+200B ZERO WIDTH SPACE"] == 2
        assert found["U+F0E0 <unnamed>"] == 1

    def test_find_invisible_is_empty_for_clean_text(self) -> None:
        from app.ingest.clean import find_invisible

        assert find_invisible("ordinary text") == {}

    def test_the_real_corpus_is_clean_after_ingestion(
        self, ingest_db: psycopg.Connection[Any]
    ) -> None:
        """End-to-end: no stored chunk may contain an invisible or private-use codepoint.

        This is the regression test for the defect itself. It reads what is actually in the
        database rather than re-running the cleaner, so it fails if the pass is bypassed
        anywhere in the ingest path, not only if `blank_invisible` regresses.
        """
        import unicodedata

        from app.ingest.clean import INVISIBLE_CATEGORIES

        rows = ingest_db.execute("SELECT chunk_id::text, text FROM chunks").fetchall()
        if not rows:
            pytest.skip("corpus not ingested; run `make ingest`")
        offenders = [
            (cid, f"U+{ord(ch):04X}")
            for cid, text in rows
            for ch in text
            if unicodedata.category(ch) in INVISIBLE_CATEGORIES
        ]
        assert not offenders, f"invisible characters survived ingestion: {offenders[:10]}"
