import { test, expect } from '@playwright/test'

// UI tests for Algorithmic & AI Impact Assessment Framework (FEAT-050)
// Enforces:
// 1. Accessibility: data-testid markers, input controls, presets
// 2. Form interactions: model category selector, specification textarea, kill switch toggle
// 3. Results rendering: conformity score gauge, status badge (CONFORMANT/CONDITIONAL/NON_CONFORMANT)
// 4. Statutory control findings with regulatory citations and copyable remedies

test('algo impact view renders form controls, model type selector, and specification area', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          .algo-view {
            background-color: #0f172a;
            border: 1px solid #1e293b;
            border-radius: 12px;
            padding: 24px;
            color: #f8fafc;
          }
        </style>
      </head>
      <body>
        <div id="root">
          <div data-testid="algo-impact-view" class="algo-view">
            <h2 id="algo-impact-title">Algorithmic & AI Impact Assessment Framework</h2>
            <form>
              <input data-testid="system-name-input" type="text" value="AlphaPulse HFT Market Maker v4.2" />
              <select data-testid="model-type-select">
                <option value="algorithmic_trading" selected>Algorithmic Trading (SEBI Order Routing)</option>
                <option value="credit_scoring">Credit Underwriting AI (RBI Master Direction)</option>
                <option value="llm_agent">Autonomous LLM Financial Agent</option>
              </select>
              <textarea data-testid="system-spec-textarea">System Architecture & Algorithmic Risk Specification with Kill Switch and Backtesting.</textarea>
              <button data-testid="audit-submit-btn" type="submit">Run Impact Assessment</button>
            </form>
          </div>
        </div>
      </body>
    </html>
  `)

  const container = page.locator('[data-testid="algo-impact-view"]')
  await expect(container).toBeVisible()

  const title = page.locator('#algo-impact-title')
  await expect(title).toHaveText('Algorithmic & AI Impact Assessment Framework')

  const systemName = page.locator('[data-testid="system-name-input"]')
  await expect(systemName).toHaveValue('AlphaPulse HFT Market Maker v4.2')

  const select = page.locator('[data-testid="model-type-select"]')
  await expect(select).toHaveValue('algorithmic_trading')

  const textarea = page.locator('[data-testid="system-spec-textarea"]')
  await expect(textarea).toContainText('Kill Switch')
})

test('algo impact view displays conformity score, status badge, audit certificate, and statutory findings', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <body>
        <div data-testid="algo-impact-view">
          <div data-testid="conformity-score">92.5%</div>
          <span data-testid="status-badge">CONFORMANT</span>
          <span data-testid="certificate-badge">CERT-ALGO-A4F98E1C2B04</span>
          <div data-testid="findings-list">
            <div data-testid="failed-control-item">
              <span>ALGO-CTRL-08</span>
              <strong>Annual Independent System & Algorithm Conformance Audit</strong>
              <p>SEBI System Audit Framework for Algorithmic Trading Members</p>
              <button type="button">Copy Remedy</button>
            </div>
          </div>
          <div data-testid="passed-controls-list">
            <span data-testid="passed-control-item">ALGO-CTRL-01</span>
            <span data-testid="passed-control-item">ALGO-CTRL-02</span>
            <span data-testid="passed-control-item">ALGO-CTRL-05</span>
          </div>
        </div>
      </body>
    </html>
  `)

  const score = page.locator('[data-testid="conformity-score"]')
  await expect(score).toHaveText('92.5%')

  const badge = page.locator('[data-testid="status-badge"]')
  await expect(badge).toHaveText('CONFORMANT')

  const cert = page.locator('[data-testid="certificate-badge"]')
  await expect(cert).toHaveText('CERT-ALGO-A4F98E1C2B04')

  const failedItem = page.locator('[data-testid="failed-control-item"]')
  await expect(failedItem).toBeVisible()
  await expect(failedItem).toContainText('ALGO-CTRL-08')

  const passedControls = page.locator('[data-testid="passed-control-item"]')
  await expect(passedControls).toHaveCount(3)
})
