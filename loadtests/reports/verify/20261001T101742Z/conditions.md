# Run conditions — Phase 0 pipeline verification

- **Target:** loadtests/dummy_server.py (FastAPI stub returning a constant) on 127.0.0.1:8001
- **THESE NUMBERS ARE MEANINGLESS as a measure of DocScout.** The point of this run is to prove the
  k6 → report-directory pipeline works. No performance claim may cite this directory.
- Host: 2 vCPU, 1.9Gi RAM, Debian GNU/Linux 13 (trixie), kernel 6.1.158+
- **Load generator and target shared the same 2-vCPU box** — this alone caps credible throughput.
- k6: k6 v2.3.0 (commit/e088784614, go1.26.8, linux/amd64)
- Script: loadtests/smoke.js, SEED=42 (default)
- Git SHA at run time: 695e0f4
- Timestamp (UTC): 20261001T101742Z
