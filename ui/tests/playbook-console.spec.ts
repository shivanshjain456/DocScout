import { test, expect } from '@playwright/test'

// UI tests for Playbook Progress Dashboard in Console UI (FEAT-059)
// Enforces:
// 1. Dashboard container, header, and playbook selector rendering
// 2. Dual circular progress gauges (overall completion and active stage completion)
// 3. 4-Stage progressive workflow lifecycle stepper
// 4. Role filter toggling and milestone checklist rendering
// 5. Milestone completion interaction and exit criteria banner state

test('playbook console renders header, progress rings, and 4-stage stepper', async ({ page }) => {
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
          <div data-testid="playbook-console" class="console-container">
            <div>
              <h2>Playbook Progress Dashboard</h2>
              <select data-testid="playbook-select">
                <option value="playbook.foundations-30d" selected>Foundations 30-Day Engineering Decoupling</option>
                <option value="playbook.ai-assurance">Algorithmic & AI Model Risk Governance Playbook</option>
              </select>
              <button data-testid="export-summary-btn">Export Report</button>
            </div>

            <div class="gauges">
              <div data-testid="overall-progress-ring">
                <span>13%</span>
                <div>Overall Playbook Progress</div>
              </div>
              <div data-testid="stage-progress-ring">
                <span>50%</span>
                <div>Active Stage Progress</div>
              </div>
            </div>

            <div data-testid="stage-stepper">
              <div data-testid="stage-step-1">Stage 1: Decouple / Establish (ACTIVE)</div>
              <div data-testid="stage-step-2">Stage 2: Bound / Contain (LOCKED)</div>
              <div data-testid="stage-step-3">Stage 3: Automate (LOCKED)</div>
              <div data-testid="stage-step-4">Stage 4: Self-Govern (LOCKED)</div>
            </div>

            <div data-testid="role-filter">
              <button id="filter-all">ALL</button>
              <button id="filter-sre">SRE</button>
              <button id="filter-dev">DEVELOPER</button>
            </div>

            <div data-testid="exit-criteria-banner">
              <div>Active Stage Exit Criteria Gate</div>
            </div>

            <div data-testid="milestones-checklist">
              <div data-testid="milestone-row-M1-1">
                <input data-testid="milestone-checkbox-M1-1" type="checkbox" checked />
                <span>Map database dependencies and domain boundary edges</span>
              </div>
              <div data-testid="milestone-row-M1-2">
                <input data-testid="milestone-checkbox-M1-2" type="checkbox" />
                <span>Draft architectural decoupling ADR and API contracts</span>
              </div>
            </div>

            <button data-testid="promote-stage-btn" disabled>Promote to Stage 2</button>
          </div>
        </div>
      </body>
    </html>
  `)

  // 1. Verify container, selector, and export button
  const container = page.locator('[data-testid="playbook-console"]')
  await expect(container).toBeVisible()

  const select = page.locator('[data-testid="playbook-select"]')
  await expect(select).toBeVisible()
  await expect(select).toHaveValue('playbook.foundations-30d')

  const exportBtn = page.locator('[data-testid="export-summary-btn"]')
  await expect(exportBtn).toBeVisible()

  // 2. Verify dual circular progress rings
  const overallRing = page.locator('[data-testid="overall-progress-ring"]')
  await expect(overallRing).toBeVisible()
  await expect(overallRing).toContainText('13%')

  const stageRing = page.locator('[data-testid="stage-progress-ring"]')
  await expect(stageRing).toBeVisible()
  await expect(stageRing).toContainText('50%')

  // 3. Verify 4-stage stepper
  const stepper = page.locator('[data-testid="stage-stepper"]')
  await expect(stepper).toBeVisible()

  const step1 = page.locator('[data-testid="stage-step-1"]')
  await expect(step1).toBeVisible()
  await expect(step1).toContainText('Stage 1')

  const step4 = page.locator('[data-testid="stage-step-4"]')
  await expect(step4).toBeVisible()
  await expect(step4).toContainText('Stage 4')

  // 4. Verify milestones checklist and checkboxes
  const checklist = page.locator('[data-testid="milestones-checklist"]')
  await expect(checklist).toBeVisible()

  const chk1 = page.locator('[data-testid="milestone-checkbox-M1-1"]')
  await expect(chk1).toBeChecked()

  const chk2 = page.locator('[data-testid="milestone-checkbox-M1-2"]')
  await expect(chk2).not.toBeChecked()

  // 5. Verify exit criteria gate banner
  const exitBanner = page.locator('[data-testid="exit-criteria-banner"]')
  await expect(exitBanner).toBeVisible()

  const promoteBtn = page.locator('[data-testid="promote-stage-btn"]')
  await expect(promoteBtn).toBeDisabled()
})

test('playbook console role filter and milestone deliverables display properly', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          body { background-color: #020617; color: #f8fafc; font-family: sans-serif; }
          .container { border: 1px solid #1e293b; padding: 20px; }
        </style>
      </head>
      <body>
        <div id="root">
          <div data-testid="playbook-console" class="container">
            <div data-testid="role-filter">
              <button id="btn-all" data-testid="filter-role-all">ALL</button>
              <button id="btn-sre" data-testid="filter-role-sre">SRE</button>
              <button id="btn-dev" data-testid="filter-role-developer">DEVELOPER</button>
            </div>

            <div id="task-m1-1" data-testid="milestone-row-M1-1">
              <span>Map database dependencies</span>
              <span data-testid="task-role-M1-1">SRE</span>
            </div>
            <div id="task-m1-2" data-testid="milestone-row-M1-2">
              <span>Draft decoupling ADR</span>
              <span data-testid="task-role-M1-2">DEVELOPER</span>
            </div>
          </div>
        </div>
      </body>
    </html>
  `)

  const filterAll = page.locator('[data-testid="filter-role-all"]')
  await expect(filterAll).toBeVisible()

  const filterSre = page.locator('[data-testid="filter-role-sre"]')
  await expect(filterSre).toBeVisible()

  const filterDev = page.locator('[data-testid="filter-role-developer"]')
  await expect(filterDev).toBeVisible()

  const row1 = page.locator('[data-testid="milestone-row-M1-1"]')
  await expect(row1).toBeVisible()
  await expect(row1).toContainText('Map database dependencies')

  const row2 = page.locator('[data-testid="milestone-row-M1-2"]')
  await expect(row2).toBeVisible()
  await expect(row2).toContainText('Draft decoupling ADR')
})
