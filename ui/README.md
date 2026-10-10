# DocScout UI

This directory contains the full-stack React 19 + TypeScript + Vite frontend console for DocScout.

**Tabs:** Search (hybrid-rrf) · Identity · Digests · OCR · Research (server demo at `GET /` has full parity).

Surfaces citation-grounded hybrid retrieval, Auth0 analyst identity profiles (`/v1/user/me`),
Brevo regulatory alert subscriptions (`/v1/subscriptions`, 300/day quota, one-click unsubscribe),
OCR.Space inspection and fallback triggers (`/v1/documents/{id}/ocr`, 1MB/3p limit),
and deterministic agentic research synthesis (`/v1/research`).

## Development

```bash
pnpm install  # or npm install
pnpm dev      # or npm run dev
```

## Testing

Smoke tests for the browser environment:

```bash
pnpm exec playwright test
```
