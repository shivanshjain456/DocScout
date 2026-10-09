# DocScout UI Scaffold

This directory contains the React 19 + TypeScript + Vite frontend client scaffold for DocScout.

DocScout also provides a self-contained server-rendered interactive demo UI directly from the FastAPI
service at `GET /` (`app/api/demo.py`), which requires no separate Node or Vite process to run.

## Development

```bash
pnpm install
pnpm dev
```

## Testing

Smoke tests for the UI scaffold use Playwright:

```bash
pnpm exec playwright test
```
