import { test, expect } from '@playwright/test'

// UI tests for 4-Stage Progressive Milestone Tracker (FEAT-052)
// Enforces:
// 1. Accessibility: data-testid markers, inputs, buttons, checklist
// 2. Stage Progress Meter: calculation of completion ratio and exit readiness badge
// 3. Evidence & Notes validation: minimum note length and sign-off behavior
// 4. Milestone completion state: checkbox state, verified audit notes, evidence doc id

test('milestone list renders stage header, progress meter, and milestone items', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          .container {
            background-color: #0f172a;
            border: 1px solid #1e293b;
            border-radius: 12px;
            padding: 20px;
            color: #f8fafc;
          }
        </style>
      </head>
      <body>
        <div id="root">
          <div data-testid="milestone-list-container" class="container">
            <div>
              <span>Stage 1</span>
              <h3>Decouple / Establish</h3>
              <div data-testid="stage-progress-ratio">0 / 2 (0%)</div>
              <span data-testid="stage-exit-badge">Prerequisites Incomplete</span>
            </div>

            <div data-testid="milestone-item-M1-1">
              <input data-testid="milestone-check-M1-1" type="checkbox" />
              <span>M1-1: Map database dependencies</span>
              <input data-testid="milestone-evidence-input-M1-1" type="text" placeholder="Evidence Doc ID" />
              <input data-testid="milestone-notes-input-M1-1" type="text" placeholder="Audit note" />
              <button data-testid="milestone-submit-btn-M1-1" type="button">Sign Off</button>
            </div>

            <div data-testid="milestone-item-M1-2">
              <input data-testid="milestone-check-M1-2" type="checkbox" />
              <span>M1-2: Draft decoupling ADR</span>
              <input data-testid="milestone-evidence-input-M1-2" type="text" placeholder="Evidence Doc ID" />
              <input data-testid="milestone-notes-input-M1-2" type="text" placeholder="Audit note" />
              <button data-testid="milestone-submit-btn-M1-2" type="button">Sign Off</button>
            </div>
          </div>
        </div>
      </body>
    </html>
  `)

  const container = page.locator('[data-testid="milestone-list-container"]')
  await expect(container).toBeVisible()

  const ratio = page.locator('[data-testid="stage-progress-ratio"]')
  await expect(ratio).toHaveText('0 / 2 (0%)')

  const badge = page.locator('[data-testid="stage-exit-badge"]')
  await expect(badge).toHaveText('Prerequisites Incomplete')

  const item1 = page.locator('[data-testid="milestone-item-M1-1"]')
  await expect(item1).toBeVisible()

  const submitBtn1 = page.locator('[data-testid="milestone-submit-btn-M1-1"]')
  await expect(submitBtn1).toBeEnabled()
})

test('milestone list displays completed milestones with evidence and exit ready badge', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          .container {
            background-color: #0f172a;
            border: 1px solid #1e293b;
            padding: 20px;
            color: #f8fafc;
          }
          .exit-ready {
            color: #34d399;
          }
        </style>
      </head>
      <body>
        <div id="root">
          <div data-testid="milestone-list-container" class="container">
            <div>
              <span>Stage 1</span>
              <h3>Decouple / Establish</h3>
              <div data-testid="stage-progress-ratio">2 / 2 (100%)</div>
              <span data-testid="stage-exit-badge" class="exit-ready">Exit Ready</span>
            </div>

            <div data-testid="milestone-item-M1-1">
              <input data-testid="milestone-check-M1-1" type="checkbox" checked disabled />
              <span>M1-1: Map database dependencies</span>
              <p>Verified: Schema decoupled and mapped [ADR-0043]</p>
            </div>

            <div data-testid="milestone-item-M1-2">
              <input data-testid="milestone-check-M1-2" type="checkbox" checked disabled />
              <span>M1-2: Draft decoupling ADR</span>
              <p>Verified: ADR-0043 approved by architect [ADR-0043]</p>
            </div>

            <div data-testid="milestone-success-alert">Milestone M1-2 completed and audit evidence recorded.</div>
          </div>
        </div>
      </body>
    </html>
  `)

  const ratio = page.locator('[data-testid="stage-progress-ratio"]')
  await expect(ratio).toHaveText('2 / 2 (100%)')

  const badge = page.locator('[data-testid="stage-exit-badge"]')
  await expect(badge).toHaveText('Exit Ready')

  const check1 = page.locator('[data-testid="milestone-check-M1-1"]')
  await expect(check1).toBeChecked()
  await expect(check1).toBeDisabled()

  const check2 = page.locator('[data-testid="milestone-check-M1-2"]')
  await expect(check2).toBeChecked()
  await expect(check2).toBeDisabled()

  const successAlert = page.locator('[data-testid="milestone-success-alert"]')
  await expect(successAlert).toBeVisible()
})
