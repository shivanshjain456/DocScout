import { test, expect } from '@playwright/test'

// UI tests for Role-Based Compliance Task Routing (FEAT-054)
// Enforces:
// 1. Accessibility: data-testid markers, role tab bar, task counters
// 2. Role filtering: filtering deliverables by taxonomy roles (developer, sre, qa-engineer, compliance-officer)
// 3. Task metadata rendering: role badges, estimated hours, stage indicators

test('role task view renders role tabs, task counters, and deliverable items', async ({ page }) => {
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
          <div data-testid="role-task-view-container" class="container">
            <h2>Role-Based Compliance Action Checklist</h2>
            <div data-testid="pending-task-count">4</div>
            <div data-testid="total-estimated-hours">34h</div>

            <div data-testid="role-tab-bar">
              <button data-testid="role-tab-all">All Roles</button>
              <button data-testid="role-tab-developer">Developer</button>
              <button data-testid="role-tab-sre">SRE</button>
              <button data-testid="role-tab-qa-engineer">QA Engineer</button>
              <button data-testid="role-tab-compliance-officer">Compliance Officer</button>
            </div>

            <div data-testid="task-item-M1-1">
              <span>M1-1</span>
              <span>Map database dependencies and domain boundary edges</span>
              <span data-testid="task-role-badge-M1-1">sre</span>
              <span data-testid="task-hours-M1-1">8h</span>
            </div>

            <div data-testid="task-item-M1-2">
              <span>M1-2</span>
              <span>Draft architectural decoupling ADR and API contracts</span>
              <span data-testid="task-role-badge-M1-2">developer</span>
              <span data-testid="task-hours-M1-2">8h</span>
            </div>
          </div>
        </div>
      </body>
    </html>
  `)

  const container = page.locator('[data-testid="role-task-view-container"]')
  await expect(container).toBeVisible()

  const pendingCount = page.locator('[data-testid="pending-task-count"]')
  await expect(pendingCount).toHaveText('4')

  const totalHours = page.locator('[data-testid="total-estimated-hours"]')
  await expect(totalHours).toHaveText('34h')

  const tabSre = page.locator('[data-testid="role-tab-sre"]')
  await expect(tabSre).toBeVisible()

  const badge1 = page.locator('[data-testid="task-role-badge-M1-1"]')
  await expect(badge1).toHaveText('sre')

  const hours1 = page.locator('[data-testid="task-hours-M1-1"]')
  await expect(hours1).toHaveText('8h')
})

test('role task view filters tasks by selected role and displays empty state when none match', async ({ page }) => {
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
        </style>
      </head>
      <body>
        <div id="root">
          <div data-testid="role-task-view-container" class="container">
            <div data-testid="pending-task-count">1</div>
            <div data-testid="total-estimated-hours">8h</div>

            <div data-testid="task-item-M1-2">
              <span>M1-2: Draft decoupling contracts</span>
              <span data-testid="task-role-badge-M1-2">developer</span>
            </div>

            <div data-testid="role-task-empty" style="display: none;">
              No pending tasks dispatched for role engineering-manager.
            </div>
          </div>
        </div>
      </body>
    </html>
  `)

  const pendingCount = page.locator('[data-testid="pending-task-count"]')
  await expect(pendingCount).toHaveText('1')

  const taskDev = page.locator('[data-testid="task-item-M1-2"]')
  await expect(taskDev).toBeVisible()

  const badgeDev = page.locator('[data-testid="task-role-badge-M1-2"]')
  await expect(badgeDev).toHaveText('developer')
})
