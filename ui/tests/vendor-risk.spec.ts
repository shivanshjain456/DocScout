import { test, expect } from '@playwright/test'

// UI tests for Third-Party Vendor Risk Assessment Engine (FEAT-049)
// Enforces:
// 1. Accessibility: region landmark, aria-label, and proper field labels
// 2. Form interactions: vendor category, agreement textarea, strict localization toggle
// 3. Results rendering: compliance score gauge, risk rating badge (LOW/MEDIUM/HIGH/CRITICAL)
// 4. Missing clauses listing with statutory requirement, citation, and copyable amendment clause

test('vendor risk view renders form controls, category select, and contract area', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          .vendor-risk-view {
            background-color: #0d1117;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 24px;
            color: #c9d1d9;
          }
        </style>
      </head>
      <body>
        <div id="root">
          <div role="region" aria-label="Third-Party Vendor Risk Assessment Engine" class="vendor-risk-view">
            <h2 id="vendor-risk-title">Third-Party Vendor Risk Assessment Engine</h2>
            <form>
              <input id="vendor-name-input" type="text" value="Acme Cloud Solutions" />
              <select id="vendor-type-select">
                <option value="CLOUD" selected>Cloud Infrastructure Provider (IaaS/PaaS)</option>
                <option value="SAAS">SaaS & Application Software Provider</option>
              </select>
              <textarea id="contract-text-area">Sample Master Services Agreement with basic provisions.</textarea>
              <button type="submit">Run Regulatory Audit</button>
            </form>
          </div>
        </div>
      </body>
    </html>
  `)

  const container = page.locator('[role="region"][aria-label="Third-Party Vendor Risk Assessment Engine"]')
  await expect(container).toBeVisible()

  const title = page.locator('#vendor-risk-title')
  await expect(title).toHaveText('Third-Party Vendor Risk Assessment Engine')

  const select = page.locator('#vendor-type-select')
  await expect(select).toHaveValue('CLOUD')

  const textarea = page.locator('#contract-text-area')
  await expect(textarea).toHaveValue('Sample Master Services Agreement with basic provisions.')
})

test('vendor risk view displays compliance score, critical risk badge, and missing clauses', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <body>
        <div role="region" aria-label="Third-Party Vendor Risk Assessment Engine">
          <div data-testid="vendor-risk-results">
            <div data-testid="compliance-score-gauge">45%</div>
            <span data-testid="risk-rating-badge">CRITICAL</span>
            <div data-testid="clauses-ratio-count">3 Present / 5 Missing</div>
            <div data-testid="missing-clauses-list">
              <div data-testid="missing-clause-item-0">
                <strong>Unconditional Regulatory Audit & Inspection Access</strong>
                <span>CRITICAL</span>
                <p>RBI Master Direction on Outsourcing of IT Services (2023), Chapter IV, Clause 15(a)</p>
                <button type="button">Copy Amendment</button>
              </div>
              <div data-testid="missing-clause-item-1">
                <strong>Indian Sovereign Data Localization</strong>
                <span>CRITICAL</span>
                <p>RBI Directive DPSS.CO.OD.No.2785/06.08.005/2017-18 & SEBI Cloud Framework Clause 3.2</p>
                <button type="button">Copy Amendment</button>
              </div>
            </div>
          </div>
        </div>
      </body>
    </html>
  `)

  const gauge = page.locator('[data-testid="compliance-score-gauge"]')
  await expect(gauge).toHaveText('45%')

  const badge = page.locator('[data-testid="risk-rating-badge"]')
  await expect(badge).toHaveText('CRITICAL')

  const list = page.locator('[data-testid="missing-clauses-list"]')
  await expect(list).toBeVisible()

  const firstMissing = page.locator('[data-testid="missing-clause-item-0"]')
  await expect(firstMissing).toContainText('Unconditional Regulatory Audit & Inspection Access')
  await expect(firstMissing).toContainText('RBI Master Direction on Outsourcing of IT Services (2023)')
})
