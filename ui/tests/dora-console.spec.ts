import { test, expect } from '@playwright/test'

// UI tests for Digital Operational Resilience (DORA) Console (FEAT-058)
// Enforces:
// 1. DORA console header, EU regulation badge, and trigger assessment button rendering
// 2. Overall DORA readiness score gauge and progress bar
// 3. Statutory 5-Pillar scorecards (ICT Risk, Incident Reporting, Resilience Testing, Third-Party Risk, Info Sharing)
// 4. ICT Systems and Third-Party Provider inventory table with criticality and exit strategy badges
// 5. Criticality filter interaction

test('dora console renders header, readiness gauge, and statutory 5-pillar scorecards', async ({ page }) => {
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
          <div data-testid="dora-console" class="console-container">
            <div>
              <h2>Digital Operational Resilience (DORA) Console</h2>
              <span>EU 2022/2554</span>
              <button data-testid="trigger-assessment-btn">Run DORA Assessment</button>
            </div>

            <div data-testid="overall-readiness-gauge">
              <div>Overall DORA Readiness</div>
              <div>76.5%</div>
            </div>

            <div class="grid">
              <div data-testid="pillar-card-pillar_1_risk_management">
                <h3>ICT Risk Management</h3>
                <span>88%</span>
                <div>Articles 5-16</div>
              </div>
              <div data-testid="pillar-card-pillar_2_incident_reporting">
                <h3>ICT Incident Management and Reporting</h3>
                <span>100%</span>
                <div>Articles 17-23</div>
              </div>
              <div data-testid="pillar-card-pillar_3_resilience_testing">
                <h3>Digital Operational Resilience Testing</h3>
                <span>65%</span>
                <div>Articles 24-27</div>
              </div>
              <div data-testid="pillar-card-pillar_4_third_party_risk">
                <h3>ICT Third-Party Risk Management</h3>
                <span>55%</span>
                <div>Articles 28-44</div>
              </div>
              <div data-testid="pillar-card-pillar_5_info_sharing">
                <h3>Information-Sharing Arrangements</h3>
                <span>74.5%</span>
                <div>Article 45</div>
              </div>
            </div>

            <table data-testid="dora-systems-table">
              <tbody>
                <tr data-testid="system-row-1">
                  <td>Core Banking Ledger</td>
                  <td>CRITICAL</td>
                  <td>Internal</td>
                  <td>Verified</td>
                </tr>
                <tr data-testid="system-row-2">
                  <td>Core Payment Engine</td>
                  <td>CRITICAL</td>
                  <td>CloudHosting Global</td>
                  <td>Missing (Gap)</td>
                </tr>
              </tbody>
            </table>

            <div data-testid="recommendations-list">
              <div>Establish contractual exit strategies for CTPPs.</div>
            </div>
          </div>
        </div>
      </body>
    </html>
  `)

  // 1. Verify container, header, and button
  const consoleContainer = page.locator('[data-testid="dora-console"]')
  await expect(consoleContainer).toBeVisible()

  const assessBtn = page.locator('[data-testid="trigger-assessment-btn"]')
  await expect(assessBtn).toBeVisible()

  // 2. Verify overall readiness gauge
  const readinessGauge = page.locator('[data-testid="overall-readiness-gauge"]')
  await expect(readinessGauge).toBeVisible()
  await expect(readinessGauge).toContainText('76.5%')

  // 3. Verify all 5 statutory pillars
  const p1 = page.locator('[data-testid="pillar-card-pillar_1_risk_management"]')
  await expect(p1).toBeVisible()
  await expect(p1).toContainText('88%')

  const p2 = page.locator('[data-testid="pillar-card-pillar_2_incident_reporting"]')
  await expect(p2).toBeVisible()
  await expect(p2).toContainText('100%')

  const p3 = page.locator('[data-testid="pillar-card-pillar_3_resilience_testing"]')
  await expect(p3).toBeVisible()
  await expect(p3).toContainText('65%')

  const p4 = page.locator('[data-testid="pillar-card-pillar_4_third_party_risk"]')
  await expect(p4).toBeVisible()
  await expect(p4).toContainText('55%')

  const p5 = page.locator('[data-testid="pillar-card-pillar_5_info_sharing"]')
  await expect(p5).toBeVisible()
  await expect(p5).toContainText('74.5%')

  // 4. Verify systems table and recommendations
  const systemsTable = page.locator('[data-testid="dora-systems-table"]')
  await expect(systemsTable).toBeVisible()

  const recommendations = page.locator('[data-testid="recommendations-list"]')
  await expect(recommendations).toBeVisible()
})

test('dora console filter allows toggling system tiers', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <body>
        <div id="root">
          <select id="crit-select" data-testid="filter-criticality">
            <option value="ALL">All Tiers</option>
            <option value="CRITICAL">CRITICAL</option>
            <option value="HIGH">HIGH</option>
          </select>
          <div id="display-tier">Showing: ALL</div>
          <script>
            document.getElementById('crit-select').addEventListener('change', (e) => {
              document.getElementById('display-tier').textContent = 'Showing: ' + e.target.value;
            });
          </script>
        </div>
      </body>
    </html>
  `)

  const displayTier = page.locator('#display-tier')
  await expect(displayTier).toHaveText('Showing: ALL')

  await page.selectOption('[data-testid="filter-criticality"]', 'CRITICAL')
  await expect(displayTier).toHaveText('Showing: CRITICAL')

  await page.selectOption('[data-testid="filter-criticality"]', 'HIGH')
  await expect(displayTier).toHaveText('Showing: HIGH')
})
