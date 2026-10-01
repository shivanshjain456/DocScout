import http from "k6/http";
import { check } from "k6";

// DocScout load smoke test — Phase 0 pipeline verification.
//
// WORKLOAD (skill: load-test-protocol — generator must be seeded and documented):
//   arrival   : constant-arrival-rate, 10 iters/s for 30s (open model: queues when the
//               system slows, instead of hiding latency behind closed-loop backpressure)
//   VUs       : 10 preallocated
//   mix       : 70% POST /query (question lookup), 30% GET /healthz
//   seed      : SEED env var (default 42) — the question sequence is deterministic
//   corpus    : n/a in Phase 0 (dummy target)
//   depth     : n/a in Phase 0 (dummy target)
//
// PHASE 0 CAVEAT: the target is loadtests/dummy_server.py, a stub that returns a constant.
// These numbers measure the harness and the box, NOT DocScout. Do not quote them anywhere.

const BASE = __ENV.BASE_URL || "http://127.0.0.1:8001";
const SEED = parseInt(__ENV.SEED || "42", 10);

const QUESTIONS = [
  "What is the settlement timeline for payment aggregators?",
  "Which entities must report quarterly compliance?",
  "What is the maximum permissible reporting delay?",
  "Who issues master circulars on KYC norms?",
  "What are the FPI power of attorney requirements?",
];

// Deterministic LCG so the request sequence is reproducible across runs.
function lcg(s) {
  let state = s >>> 0;
  return () => ((state = (1103515245 * state + 12345) >>> 0) / 4294967296);
}
const rand = lcg(SEED);

export const options = {
  scenarios: {
    smoke: {
      executor: "constant-arrival-rate",
      rate: 10,
      timeUnit: "1s",
      duration: "30s",
      preAllocatedVUs: 10,
      maxVUs: 20,
    },
  },
  thresholds: {
    // Declared UP FRONT. A breach is a reported FAIL, not a rerun.
    http_req_duration: ["p(50)<200", "p(95)<500", "p(99)<1000"],
    http_req_failed: ["rate<0.01"],
    checks: ["rate>0.99"],
  },
};

export default function () {
  if (rand() < 0.7) {
    const q = QUESTIONS[Math.floor(rand() * QUESTIONS.length)];
    const res = http.post(`${BASE}/query`, JSON.stringify({ question: q }), {
      headers: { "Content-Type": "application/json" },
    });
    check(res, {
      "query status 200": (r) => r.status === 200,
      "query has answer": (r) => r.body && r.body.includes("answer"),
    });
  } else {
    const res = http.get(`${BASE}/healthz`);
    check(res, { "health status 200": (r) => r.status === 200 });
  }
}
