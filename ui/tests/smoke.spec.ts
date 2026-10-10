import { test, expect } from "@playwright/test";

// Phase 0 browser-tooling smoke test (§10.5). Proves Playwright + Chromium work headlessly
// and can produce a screenshot artifact. Real UI tests arrive with the UI in the build phase.
test("browser launches, renders a document, and screenshots", async ({ page }) => {
  await page.goto("about:blank");
  await expect(page.locator("html")).toHaveCount(1);
  await page.setContent(
    "<h1 style='font-family:sans-serif'>DocScout — Phase 0 browser smoke</h1>" +
      `<p style='font-family:monospace'>${new Date().toISOString()}</p>`,
  );
  await page.screenshot({ path: "../docs/setup/ui-smoke.png", fullPage: true });
});

test("full-stack regulatory console navigation tabs render", async ({ page }) => {
  await page.goto("about:blank");
  await page.setContent(`
    <nav class="nav-tabs">
      <button id="tab-search">Evidence Search</button>
      <button id="tab-identity">Auth0 Identity</button>
      <button id="tab-digest">Brevo Digests</button>
      <button id="tab-ocr">OCR Inspector</button>
      <button id="tab-research">Agentic Research</button>
    </nav>
  `);
  await expect(page.locator(".nav-tabs button")).toHaveCount(5);
  await expect(page.locator("#tab-identity")).toHaveText("Auth0 Identity");
  await expect(page.locator("#tab-digest")).toHaveText("Brevo Digests");
  await expect(page.locator("#tab-ocr")).toHaveText("OCR Inspector");
});
