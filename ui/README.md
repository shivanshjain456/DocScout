# DocScout UI

This directory contains the minimal React 19 + TypeScript + Vite frontend console for DocScout,
querying `/v1/search` with citation rendering, confidence metrics, and request tracing.

DocScout also provides a comprehensive, self-contained server-rendered interactive regulatory console
directly from the FastAPI service at `GET /` (`app/api/demo.py`), which requires no separate Node or Vite process.

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
