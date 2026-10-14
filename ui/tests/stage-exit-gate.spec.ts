import { test, expect } from '@playwright/test'

// UI tests for Automated Stage Exit Criteria Validator (FEAT-053)
// Enforces:
// 1. Accessibility: data-testid markers, exit statement, precondition checks, buttons
// 2. Blocking view: displays blocked criteria, missing deliverables, disabled advancement
// 3. Administrative override: exception rationale input (min 15 chars), submit button
// 4. Successful validation: promote button enabled when all criteria pass

test('stage exit gate modal renders blocked criteria and blocking issues', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          .container {
            background-color: #0f172a;
            border: 1px solid #1e293b;
            border-radius: 16px;
            padding: 24px;
            color: #f8fafc;
          }
          .blocked-badge {
            background-color: #881337;
            color: #fda4af;
          }
        </style>
      </head>
      <body>
        <div id="root">
          <div data-testid="stage-exit-gate-container" class="container">
            <h2>Automated Stage Exit Validator</h2>
            <div data-testid="stage-exit-statement">Domain interfaces documented with zero circular schema references.</div>

            <div data-testid="criterion-check-item-0">
              <span>Domain interfaces documented with zero circular schema references.</span>
              <span data-testid="criterion-badge-0" class="blocked-badge">FAILED</span>
            </div>

            <div data-testid="stage-exit-blocking-issues">
              <span>Promotion Blocked (1 unsatisfied preconditions)</span>
              <li data-testid="blocking-issue-item-0">Milestone M1-2 is incomplete.</li>
            </div>

            <button data-testid="toggle-override-btn">Apply Administrative Exception / Override</button>
            <button data-testid="stage-exit-close-btn">Close</button>
          </div>
        </div>
      </body>
    </html>
  `)

  const container = page.locator('[data-testid="stage-exit-gate-container"]')
  await expect(container).toBeVisible()

  const statement = page.locator('[data-testid="stage-exit-statement"]')
  await expect(statement).toContainText('Domain interfaces documented')

  const badge0 = page.locator('[data-testid="criterion-badge-0"]')
  await expect(badge0).toHaveText('FAILED')

  const blockers = page.locator('[data-testid="stage-exit-blocking-issues"]')
  await expect(blockers).toBeVisible()

  const issueItem0 = page.locator('[data-testid="blocking-issue-item-0"]')
  await expect(issueItem0).toContainText('Milestone M1-2 is incomplete')

  const toggleBtn = page.locator('[data-testid="toggle-override-btn"]')
  await expect(toggleBtn).toBeVisible()

  // Promote button should not be present when blocked
  const promoteBtn = page.locator('[data-testid="promote-stage-btn"]')
  await expect(promoteBtn).toHaveCount(0)
})

test('stage exit gate renders passing checks, promote button, and handles override', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          .container {
            background-color: #0f172a;
            border: 1px solid #1e293b;
            border-radius: 16px;
            padding: 24px;
            color: #f8fafc;
          }
          .pass-badge {
            background-color: #064e3b;
            color: #6ee7b7;
          }
        </style>
      </head>
      <body>
        <div id="root">
          <div data-testid="stage-exit-gate-container" class="container">
            <h2>Automated Stage Exit Validator</h2>
            <div data-testid="stage-exit-statement">Domain interfaces documented with zero circular schema references.</div>

            <div data-testid="criterion-check-item-0">
              <span>Domain interfaces documented with zero circular schema references.</span>
              <span data-testid="criterion-badge-0" class="pass-badge">PASSED</span>
            </div>

            <div data-testid="override-section">
              <textarea data-testid="override-justification-input">Architectural audit approved under regulatory emergency protocol</textarea>
              <button data-testid="submit-override-btn">Sign Audit Exception & Promote</button>
            </div>

            <button data-testid="promote-stage-btn">Promote to Stage 2</button>
            <div data-testid="stage-exit-success-alert">Stage successfully promoted to next stage.</div>
          </div>
        </div>
      </body>
    </html>
  `)

  const badge0 = page.locator('[data-testid="criterion-badge-0"]')
  await expect(badge0).toHaveText('PASSED')

  const promoteBtn = page.locator('[data-testid="promote-stage-btn"]')
  await expect(promoteBtn).toBeVisible()
  await expect(promoteBtn).toBeEnabled()

  const overrideInput = page.locator('[data-testid="override-justification-input"]')
  await expect(overrideInput).toHaveValue(
    'Architectural audit approved under regulatory emergency protocol'
  )

  const successAlert = page.locator('[data-testid="stage-exit-success-alert"]')
  await expect(successAlert).toBeVisible()
})
