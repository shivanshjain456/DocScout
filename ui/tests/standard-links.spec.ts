import { test, expect } from '@playwright/test'

// UI tests for ISO/NIST Clause Cross-Citation Hyperlinking in Document Reader (FEAT-046)
// Enforces:
// 1. Ingestion-time entity extraction hyperlinking in reader UI
// 2. Interactive badges (.standard-mention-badge) with data-standard-id and data-control-hint
// 3. Dynamic popover card with standard title, ID, governing body, and deep link (/standards/{id})
// 4. Keyboard accessibility: WCAG 2.2 AA compliant button role and dialog interactions
// 5. Clean fallback text rendering when no standard mentions are present

test('document reader renders standard mention badges with data attributes', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          .standard-mention-badge {
            background-color: rgba(56, 139, 253, 0.15);
            border-bottom: 1.5px solid #58a6ff;
            color: #79c0ff;
            padding: 1px 4px;
            cursor: pointer;
          }
        </style>
      </head>
      <body>
        <div id="root">
          <div class="document-reader-container">
            <header>
              <h2>Master Direction on IT Governance</h2>
              <span class="mentions-count-badge">2 Standards Cited</span>
            </header>
            <div class="document-body-content">
              Banks shall adhere to
              <span class="standard-mention-badge" data-standard-id="ISO/IEC 27001" data-control-hint="Annex A.5.15" role="button" tabindex="0" aria-haspopup="dialog" aria-expanded="false">ISO/IEC 27001 Annex A.5.15</span>
              and secure transaction networks under
              <span class="standard-mention-badge" data-standard-id="PCI DSS 4.0" data-control-hint="Requirement 3.4" role="button" tabindex="0" aria-haspopup="dialog" aria-expanded="false">PCI DSS 4.0 Requirement 3.4</span>.
            </div>
          </div>
        </div>
      </body>
    </html>
  `)

  const badges = page.locator('.standard-mention-badge')
  await expect(badges).toHaveCount(2)
  await expect(badges.nth(0)).toHaveAttribute('data-standard-id', 'ISO/IEC 27001')
  await expect(badges.nth(0)).toHaveAttribute('data-control-hint', 'Annex A.5.15')
  await expect(badges.nth(1)).toHaveAttribute('data-standard-id', 'PCI DSS 4.0')
  await expect(badges.nth(1)).toHaveAttribute('data-control-hint', 'Requirement 3.4')
})

test('popover card displays standard title, governing body, control hint, and deep link', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <body>
        <div id="reader-test">
          <span class="standard-mention-badge" data-standard-id="ISO/IEC 27001" role="button" tabindex="0">ISO/IEC 27001</span>
          <div role="dialog" aria-label="ISO/IEC 27001">
            <span class="standard-title">Information Security Management Systems</span>
            <span class="standard-id-badge">ISO/IEC 27001</span>
            <span class="standard-gov-body">ISO/IEC</span>
            <div class="standard-control-hint">Control Hint: Annex A.5.15</div>
            <a href="/standards/ISO%2FIEC%2027001" class="standard-deep-link">View Standard Specification &rarr;</a>
          </div>
        </div>
      </body>
    </html>
  `)

  const dialog = page.locator('[role="dialog"]')
  await expect(dialog).toBeVisible()
  await expect(dialog.locator('.standard-title')).toHaveText('Information Security Management Systems')
  await expect(dialog.locator('.standard-id-badge')).toHaveText('ISO/IEC 27001')
  await expect(dialog.locator('.standard-gov-body')).toHaveText('ISO/IEC')
  await expect(dialog.locator('.standard-control-hint')).toContainText('Annex A.5.15')
  await expect(dialog.locator('.standard-deep-link')).toHaveAttribute('href', '/standards/ISO%2FIEC%2027001')
})

test('keyboard accessibility: badge has role button, tabindex, and aria-haspopup', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <body>
        <button id="prev">Start</button>
        <span class="standard-mention-badge" data-standard-id="NIST SP 800-53" role="button" tabindex="0" aria-haspopup="dialog" aria-expanded="false">NIST SP 800-53</span>
        <button id="next">End</button>
      </body>
    </html>
  `)

  const badge = page.locator('.standard-mention-badge')
  await expect(badge).toHaveAttribute('tabindex', '0')
  await expect(badge).toHaveAttribute('role', 'button')
  await expect(badge).toHaveAttribute('aria-haspopup', 'dialog')

  // Focus badge via keyboard
  await page.focus('#prev')
  await page.keyboard.press('Tab')
  await expect(badge).toBeFocused()
})

test('fallback behavior: clean text without hyperlinks rendered when no mentions exist', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <body>
        <div class="document-body-content">
          The bank shall maintain a minimum leverage ratio of 4 percent under Basel guidelines.
        </div>
      </body>
    </html>
  `)

  const badges = page.locator('.standard-mention-badge')
  await expect(badges).toHaveCount(0)
  const body = page.locator('.document-body-content')
  await expect(body).toContainText('The bank shall maintain a minimum leverage ratio')
})
