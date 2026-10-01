"""Evaluation harness: the gold set, the deterministic scorers, and the reports.

`EVAL_PROTOCOL.md` is the contract this package implements. The package exists separately
from `app/ingest` because the eval harness must be able to judge the pipeline without
importing its conclusions -- it reuses the chunker (so citations resolve to real chunks) and
nothing else.
"""
