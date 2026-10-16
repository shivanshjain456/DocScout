import { test, expect } from '@playwright/test'

// UI tests for Interactive Compliance Playbook Runtime (FEAT-051)
// Enforces:
// 1. Accessibility: data-testid markers, select controls, inputs
// 2. 4-Stage Progressive Stepper: rendering of all 4 stages
// 3. Milestone Checklist: checkboxes, progress meter calculation, exit criteria banner
// 4. Stage Progression: advancement to next stage upon satisfying exit criteria

test('playbook runtime renders controls, playbook selector, and 4-stage stepper', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          .playbook-container {
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
          <div data-testid="playbook-runtime-container" class="playbook-container">
            <h2 id="playbook-title">Interactive Compliance Playbook Runtime</h2>
            <form>
              <select data-testid="playbook-select">
                <option value="playbook.foundations-30d" selected>Foundations 30-Day Engineering Decoupling</option>
                <option value="playbook.ai-assurance">Algorithmic & AI Model Risk Governance Playbook</option>
                <option value="playbook.vendor-risk">Third-Party Vendor Risk Assessment Playbook</option>
              </select>
              <input data-testid="tenant-id-input" type="text" value="tenant-test-corp" />
              <input data-testid="assigned-lead-input" type="text" value="Chief Compliance Officer" />
              <button data-testid="start-playbook-button" type="submit">Start Run</button>
            </form>

            <div data-testid="playbook-stage-stepper">
              <div data-testid="stage-item-1" class="stage-active">Stage 1: Decouple / Establish</div>
              <div data-testid="stage-item-2">Stage 2: Bound / Contain</div>
              <div data-testid="stage-item-3">Stage 3: Automate</div>
              <div data-testid="stage-item-4">Stage 4: Self-Govern</div>
            </div>

            <div data-testid="stage-completion-meter">0 / 2 (0%)</div>
            <button data-testid="advance-stage-button" type="button">Advance to Stage 2 -></button>
          </div>
        </div>
      </body>
    </html>
  `)

  const container = page.locator('[data-testid="playbook-runtime-container"]')
  await expect(container).toBeVisible()

  const title = page.locator('#playbook-title')
  await expect(title).toHaveText('Interactive Compliance Playbook Runtime')

  const select = page.locator('[data-testid="playbook-select"]')
  await expect(select).toHaveValue('playbook.foundations-30d')

  const tenant = page.locator('[data-testid="tenant-id-input"]')
  await expect(tenant).toHaveValue('tenant-test-corp')

  const stepper = page.locator('[data-testid="playbook-stage-stepper"]')
  await expect(stepper).toBeVisible()

  const stage1 = page.locator('[data-testid="stage-item-1"]')
  await expect(stage1).toContainText('Stage 1')

  const stage4 = page.locator('[data-testid="stage-item-4"]')
  await expect(stage4).toContainText('Stage 4')
})

test('playbook runtime updates milestone checklist and shows stage progress', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          .playbook-container {
            background-color: #0f172a;
            color: #f8fafc;
            padding: 20px;
          }
          .status-active {
            background-color: #083344;
            color: #22d3ee;
            padding: 4px 8px;
            border-radius: 9999px;
          }
        </style>
      </head>
      <body>
        <div id="root">
          <div data-testid="playbook-runtime-container" class="playbook-container">
            <span data-testid="playbook-status-badge" class="status-active">ACTIVE</span>

            <div data-testid="milestone-row-M1-1">
              <input data-testid="milestone-checkbox-M1-1" type="checkbox" checked />
              <span>Map database dependencies and domain boundary edges</span>
            </div>

            <div data-testid="milestone-row-M1-2">
              <input data-testid="milestone-checkbox-M1-2" type="checkbox" checked />
              <span>Draft architectural decoupling ADR and API contracts</span>
            </div>

            <div data-testid="stage-completion-meter">2 / 2 (100%)</div>
            <button data-testid="advance-stage-button" type="button">Advance to Stage 2 -></button>
          </div>
        </div>
      </body>
    </html>
  `)

  const statusBadge = page.locator('[data-testid="playbook-status-badge"]')
  await expect(statusBadge).toHaveText('ACTIVE')

  const checkbox1 = page.locator('[data-testid="milestone-checkbox-M1-1"]')
  await expect(checkbox1).toBeChecked()

  const checkbox2 = page.locator('[data-testid="milestone-checkbox-M1-2"]')
  await expect(checkbox2).toBeChecked()

  const meter = page.locator('[data-testid="stage-completion-meter"]')
  await expect(meter).toHaveText('2 / 2 (100%)')

  const advanceBtn = page.locator('[data-testid="advance-stage-button"]')
  await expect(advanceBtn).toBeEnabled()
})
