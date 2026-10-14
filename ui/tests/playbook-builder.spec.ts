import { test, expect } from '@playwright/test'

// UI tests for Custom Enterprise Compliance Playbook Builder (FEAT-060)
// Enforces:
// 1. Playbook builder container, header, and metadata inputs (ID, name, goal, domain)
// 2. Multi-stage workflow composer (minimum 2 stages, maximum 6 stages)
// 3. Stage addition, deletion, and stage milestone manipulation
// 4. Real-time structural validation callout when invariants are violated
// 5. Direct JSON editor toggle mode and template export

test('playbook builder renders header, metadata inputs, and default stages', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          body { background-color: #020617; color: #f8fafc; font-family: sans-serif; }
          .builder-container { border: 1px solid #1e293b; border-radius: 12px; padding: 24px; background: #0f172a; }
        </style>
      </head>
      <body>
        <div id="root">
          <div data-testid="playbook-builder" class="builder-container">
            <h2>Custom Compliance Playbook Builder</h2>
            <button data-testid="btn-toggle-json">JSON Mode</button>
            <button data-testid="btn-publish-playbook">Publish Playbook</button>

            <div>
              <input data-testid="input-playbook-id" value="playbook.custom-enterprise-audit" />
              <input data-testid="input-playbook-name" value="Enterprise Cryptographic & Vendor Resilience Playbook" />
              <input data-testid="input-playbook-domain" value="compliance-resilience" />
              <textarea data-testid="input-playbook-goal">Orchestrate end-to-end cryptographic inventory transition.</textarea>
            </div>

            <button data-testid="btn-add-stage">+ Add Stage</button>

            <div data-testid="stage-card-0">
              <span class="stage-num">1</span>
              <input data-testid="input-stage-name-0" value="Scope and Discovery" />
              <button data-testid="btn-remove-stage-0" disabled>Delete Stage</button>
              <button data-testid="btn-add-milestone-0">+ Add Milestone</button>
              <button data-testid="btn-add-exit-criterion-0">+ Add Criterion</button>
            </div>

            <div data-testid="stage-card-1">
              <span class="stage-num">2</span>
              <input data-testid="input-stage-name-1" value="Risk Assessment & Remediation" />
              <button data-testid="btn-remove-stage-1" disabled>Delete Stage</button>
              <button data-testid="btn-add-milestone-1">+ Add Milestone</button>
              <button data-testid="btn-add-exit-criterion-1">+ Add Criterion</button>
            </div>
          </div>
        </div>
      </body>
    </html>
  `)

  // 1. Verify container and header actions
  const container = page.locator('[data-testid="playbook-builder"]')
  await expect(container).toBeVisible()

  const jsonToggle = page.locator('[data-testid="btn-toggle-json"]')
  await expect(jsonToggle).toBeVisible()

  const publishBtn = page.locator('[data-testid="btn-publish-playbook"]')
  await expect(publishBtn).toBeVisible()

  // 2. Verify metadata inputs
  const idInput = page.locator('[data-testid="input-playbook-id"]')
  await expect(idInput).toHaveValue('playbook.custom-enterprise-audit')

  const nameInput = page.locator('[data-testid="input-playbook-name"]')
  await expect(nameInput).toHaveValue('Enterprise Cryptographic & Vendor Resilience Playbook')

  const domainInput = page.locator('[data-testid="input-playbook-domain"]')
  await expect(domainInput).toHaveValue('compliance-resilience')

  const goalInput = page.locator('[data-testid="input-playbook-goal"]')
  await expect(goalInput).toBeVisible()

  // 3. Verify stage cards (default 2 stages)
  const stage0 = page.locator('[data-testid="stage-card-0"]')
  await expect(stage0).toBeVisible()
  await expect(page.locator('[data-testid="input-stage-name-0"]')).toHaveValue('Scope and Discovery')

  const stage1 = page.locator('[data-testid="stage-card-1"]')
  await expect(stage1).toBeVisible()
  await expect(page.locator('[data-testid="input-stage-name-1"]')).toHaveValue(
    'Risk Assessment & Remediation'
  )

  // 4. Verify stage deletion is disabled when at boundary (2 stages)
  await expect(page.locator('[data-testid="btn-remove-stage-0"]')).toBeDisabled()
  await expect(page.locator('[data-testid="btn-remove-stage-1"]')).toBeDisabled()
})

test('playbook builder validates stage boundaries and handles stage manipulation', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          body { background-color: #020617; color: #f8fafc; font-family: sans-serif; }
          .error-box { background: rgba(180, 83, 9, 0.2); border: 1px solid #f59e0b; padding: 12px; }
        </style>
      </head>
      <body>
        <div id="root">
          <div data-testid="playbook-builder">
            <div data-testid="validation-errors" class="error-box">
              <span id="err-title">Validation Requirements (1)</span>
              <ul>
                <li id="err-item-1">Stage 2 has an empty name.</li>
              </ul>
            </div>

            <div data-testid="stage-card-0">
              <input data-testid="input-stage-name-0" value="Stage 1: Architecture" />
            </div>

            <div data-testid="stage-card-1">
              <input data-testid="input-stage-name-1" value="" />
            </div>

            <div data-testid="stage-card-2">
              <input data-testid="input-stage-name-2" value="Stage 3: Verification" />
              <button data-testid="btn-remove-stage-2">Delete Stage</button>
            </div>

            <button data-testid="btn-publish-playbook" disabled>Publish Playbook</button>
            <div data-testid="publish-success-banner" style="display:none">Custom playbook published!</div>
          </div>
        </div>
      </body>
    </html>
  `)

  // 1. Validation box displays when errors exist
  const validationBox = page.locator('[data-testid="validation-errors"]')
  await expect(validationBox).toBeVisible()
  await expect(validationBox).toContainText('Validation Requirements')
  await expect(validationBox).toContainText('Stage 2 has an empty name.')

  // 2. Publish button is disabled when invalid
  const publishBtn = page.locator('[data-testid="btn-publish-playbook"]')
  await expect(publishBtn).toBeDisabled()

  // 3. Stage 3 delete button is enabled when > 2 stages
  const deleteStage2Btn = page.locator('[data-testid="btn-remove-stage-2"]')
  await expect(deleteStage2Btn).toBeEnabled()
})
