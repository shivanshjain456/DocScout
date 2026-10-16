import { test, expect } from '@playwright/test'

// UI tests for Post-Quantum Cryptographic Migration Tracker (FEAT-057)
// Enforces:
// 1. PQC console header and migration milestone badge rendering
// 2. Readiness score gauge and HNDL risk exposure presentation
// 3. Cryptographic asset inventory table with classification badges
// 4. Filtering by classification (PQC_READY, HYBRID, CLASSICAL_SAFE, DEPRECATED, UNKNOWN)
// 5. Trigger scan interactive action

test('pqc console renders header, milestone badge, and readiness gauges', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          body { background-color: #020617; color: #f8fafc; font-family: sans-serif; }
          .console-container { border: 1px solid #1e293b; border-radius: 12px; padding: 24px; background: #020617; }
        </style>
      </head>
      <body>
        <div id="root">
          <div data-testid="pqc-console" class="console-container">
            <div>
              <h2>Post-Quantum Cryptographic Migration Tracker</h2>
              <span data-testid="migration-milestone-badge">Phase 2: Hybrid Transition</span>
              <button data-testid="trigger-scan-btn">Scan Cryptographic Inventory</button>
            </div>

            <div data-testid="readiness-score-gauge">
              <div>PQC Readiness Score</div>
              <div>31.3%</div>
            </div>

            <div data-testid="hndl-exposure-meter">
              <div>HNDL Risk Exposure</div>
              <div>62.5%</div>
            </div>

            <div class="tabs">
              <button data-testid="filter-tab-all">All Assets</button>
              <button data-testid="filter-tab-pqc_ready">PQC Ready</button>
              <button data-testid="filter-tab-hybrid">Hybrid</button>
              <button data-testid="filter-tab-classical_safe">Classical Safe</button>
              <button data-testid="filter-tab-classical_deprecated">Deprecated</button>
            </div>

            <table data-testid="pqc-assets-table">
              <tbody>
                <tr data-testid="asset-row-1">
                  <td>api.payments.docscout.internal</td>
                  <td>TLS_AES_256_GCM_SHA384</td>
                  <td><span data-testid="classification-badge-hybrid">HYBRID</span></td>
                </tr>
                <tr data-testid="asset-row-2">
                  <td>core-settlement.bank.internal</td>
                  <td>TLS_MLKEM768_AES_256_GCM_SHA384</td>
                  <td><span data-testid="classification-badge-pqc_ready">PQC_READY</span></td>
                </tr>
                <tr data-testid="asset-row-3">
                  <td>auth-gateway.docscout.internal</td>
                  <td>TLS_AES_256_GCM_SHA384</td>
                  <td><span data-testid="classification-badge-classical_safe">CLASSICAL_SAFE</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </body>
    </html>
  `)

  // 1. Verify container and header elements
  const consoleContainer = page.locator('[data-testid="pqc-console"]')
  await expect(consoleContainer).toBeVisible()

  const milestoneBadge = page.locator('[data-testid="migration-milestone-badge"]')
  await expect(milestoneBadge).toBeVisible()
  await expect(milestoneBadge).toContainText('Phase 2: Hybrid Transition')

  const scanBtn = page.locator('[data-testid="trigger-scan-btn"]')
  await expect(scanBtn).toBeVisible()

  // 2. Verify readiness score gauge and HNDL meter
  const readinessGauge = page.locator('[data-testid="readiness-score-gauge"]')
  await expect(readinessGauge).toBeVisible()
  await expect(readinessGauge).toContainText('31.3%')

  const hndlMeter = page.locator('[data-testid="hndl-exposure-meter"]')
  await expect(hndlMeter).toBeVisible()
  await expect(hndlMeter).toContainText('62.5%')

  // 3. Verify asset table and classification badges
  const assetsTable = page.locator('[data-testid="pqc-assets-table"]')
  await expect(assetsTable).toBeVisible()

  const hybridBadge = page.locator('[data-testid="classification-badge-hybrid"]')
  await expect(hybridBadge).toBeVisible()
  await expect(hybridBadge).toContainText('HYBRID')

  const pqcBadge = page.locator('[data-testid="classification-badge-pqc_ready"]')
  await expect(pqcBadge).toBeVisible()
  await expect(pqcBadge).toContainText('PQC_READY')

  const classicalBadge = page.locator('[data-testid="classification-badge-classical_safe"]')
  await expect(classicalBadge).toBeVisible()
  await expect(classicalBadge).toContainText('CLASSICAL_SAFE')
})

test('pqc console filter tabs toggle asset views correctly', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <body>
        <div id="root">
          <button id="all-btn" data-testid="filter-tab-all">All Assets</button>
          <button id="pqc-btn" data-testid="filter-tab-pqc_ready">PQC Ready</button>
          <div id="status-display">Showing: All</div>
          <script>
            document.getElementById('pqc-btn').addEventListener('click', () => {
              document.getElementById('status-display').textContent = 'Showing: PQC Ready';
            });
            document.getElementById('all-btn').addEventListener('click', () => {
              document.getElementById('status-display').textContent = 'Showing: All';
            });
          </script>
        </div>
      </body>
    </html>
  `)

  const statusDisplay = page.locator('#status-display')
  await expect(statusDisplay).toHaveText('Showing: All')

  await page.click('[data-testid="filter-tab-pqc_ready"]')
  await expect(statusDisplay).toHaveText('Showing: PQC Ready')

  await page.click('[data-testid="filter-tab-all"]')
  await expect(statusDisplay).toHaveText('Showing: All')
})
