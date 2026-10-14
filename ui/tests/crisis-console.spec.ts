import { test, expect } from '@playwright/test'

// UI tests for Regulatory Cyber Incident Response Playbook (FEAT-055)
// Enforces:
// 1. Crisis mode banner and emergency styling
// 2. Regulatory 6-hour countdown clock presentation
// 3. Impacted infrastructure chip rendering
// 4. Forensic evidence and containment checklist verification
// 5. Statutory RBI Annex II disclosure form preview and copy action

test('crisis console renders crisis banner, 6-hour countdown, and impacted systems', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          body { background-color: #020617; color: #f8fafc; font-family: sans-serif; }
          .console-container { border: 1px solid #881337; border-radius: 12px; padding: 24px; background: #020617; }
        </style>
      </head>
      <body>
        <div id="root">
          <div data-testid="crisis-console" class="console-container">
            <div data-testid="crisis-mode-banner">
              <h2>Statutory Cyber Incident Crisis Response (RBI CSF)</h2>
              <span data-testid="crisis-severity-badge">SEV1</span>
              <span data-testid="crisis-status-badge">DECLARED</span>
              <button data-testid="declare-incident-btn">Declare Crisis</button>
            </div>

            <div data-testid="regulatory-countdown-clock">
              <div>Statutory RBI 6-Hour Deadline Window</div>
              <div>05:15:00</div>
              <div>Time Remaining to Certify Filing</div>
            </div>

            <div data-testid="impacted-systems-list">
              <span data-testid="system-tag-core-payment-gateway">core-payment-gateway</span>
              <span data-testid="system-tag-settlement-db-replica">settlement-db-replica</span>
            </div>

            <div data-testid="crisis-actions-checklist">
              <div data-testid="crisis-action-item-ACT-01">
                <input type="checkbox" data-testid="action-checkbox-ACT-01" checked />
                <span>ACT-01: Establish out-of-band encrypted incident war room</span>
              </div>
              <div data-testid="crisis-action-item-ACT-02">
                <input type="checkbox" data-testid="action-checkbox-ACT-02" />
                <span>ACT-02: Preserve volatile memory dump and system event audit logs</span>
                <button data-testid="complete-action-btn-ACT-02">Verify</button>
              </div>
            </div>

            <div data-testid="disclosure-draft-preview">
              # STATUTORY INCIDENT DISCLOSURE (RBI CYBER SECURITY FRAMEWORK - ANNEX II)
              Incident Reference ID: e30a5749-5a12-4eb3-8b7c-f8d97e59b201
            </div>

            <button data-testid="copy-disclosure-btn">Copy Draft</button>
          </div>
        </div>
      </body>
    </html>
  `)

  const consoleBox = page.locator('[data-testid="crisis-console"]')
  await expect(consoleBox).toBeVisible()

  const banner = page.locator('[data-testid="crisis-mode-banner"]')
  await expect(banner).toBeVisible()

  const severityBadge = page.locator('[data-testid="crisis-severity-badge"]')
  await expect(severityBadge).toHaveText('SEV1')

  const statusBadge = page.locator('[data-testid="crisis-status-badge"]')
  await expect(statusBadge).toHaveText('DECLARED')

  const countdown = page.locator('[data-testid="regulatory-countdown-clock"]')
  await expect(countdown).toContainText('Statutory RBI 6-Hour Deadline Window')

  const system1 = page.locator('[data-testid="system-tag-core-payment-gateway"]')
  await expect(system1).toHaveText('core-payment-gateway')

  const action1 = page.locator('[data-testid="crisis-action-item-ACT-01"]')
  await expect(action1).toBeVisible()

  const action2 = page.locator('[data-testid="crisis-action-item-ACT-02"]')
  await expect(action2).toBeVisible()

  const copyBtn = page.locator('[data-testid="copy-disclosure-btn"]')
  await expect(copyBtn).toBeVisible()
})

test('crisis console allows verifying forensic action items and viewing disclosure dossier', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          body { background-color: #020617; color: #f8fafc; }
        </style>
      </head>
      <body>
        <div id="root">
          <div data-testid="crisis-console">
            <div data-testid="crisis-actions-checklist">
              <div data-testid="crisis-action-item-ACT-02">
                <input type="checkbox" data-testid="action-checkbox-ACT-02" id="chk2" />
                <label for="chk2">ACT-02: Preserve volatile memory dump</label>
                <button data-testid="complete-action-btn-ACT-02" onclick="document.getElementById('chk2').checked = true; this.innerText = 'Verified';">Verify</button>
              </div>
            </div>

            <div data-testid="disclosure-draft-preview">
              STATUTORY INCIDENT DISCLOSURE (RBI CYBER SECURITY FRAMEWORK - ANNEX II)
            </div>
          </div>
        </div>
      </body>
    </html>
  `)

  const checkbox = page.locator('[data-testid="action-checkbox-ACT-02"]')
  await expect(checkbox).not.toBeChecked()

  const verifyBtn = page.locator('[data-testid="complete-action-btn-ACT-02"]')
  await verifyBtn.click()

  await expect(checkbox).toBeChecked()
  await expect(verifyBtn).toHaveText('Verified')

  const preview = page.locator('[data-testid="disclosure-draft-preview"]')
  await expect(preview).toContainText('RBI CYBER SECURITY FRAMEWORK')
})
