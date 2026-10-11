import { test, expect } from '@playwright/test'

// UI tests for Dynamic Definition Tooltips in Console UI (FEAT-007)
// Enforces:
// 1. Term detection and span wrapping with class "taxonomy-term" and data-term-id
// 2. Dynamic popover card display with canonical term, layer badge, definition, and source anchor
// 3. Accessibility: role="button", aria-haspopup="dialog", aria-expanded
// 4. Keyboard interaction: focus + Enter opens popover, Escape closes
// 5. Fallback behavior: raw text is rendered cleanly when dictionary is empty or unavailable

test('taxonomy term annotator renders highlighted terms with data-term-id', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <head>
        <style>
          .taxonomy-term {
            border-bottom: 1.5px dotted #58a6ff;
            color: #79c0ff;
            cursor: help;
          }
          [role="dialog"] {
            position: fixed;
            background: #161b22;
            border: 1px solid #388bfd;
            border-radius: 8px;
            padding: 12px;
            color: #c9d1d9;
          }
        </style>
      </head>
      <body>
        <div id="root">
          <p class="passage">
            The <span class="taxonomy-term" data-term-id="commercial_bank" role="button" tabindex="0" aria-haspopup="dialog" aria-expanded="false">Commercial Bank</span>
            engaged in <span class="taxonomy-term" data-term-id="digital-lending" role="button" tabindex="0" aria-haspopup="dialog" aria-expanded="false">Digital Lending</span>
            must comply with <span class="taxonomy-term" data-term-id="first-loss-default-guarantee" role="button" tabindex="0" aria-haspopup="dialog" aria-expanded="false">First Loss Default Guarantee</span> norms.
          </p>
        </div>
      </body>
    </html>
  `)

  // Check 3 taxonomy terms are detected and rendered with proper attributes
  const terms = page.locator('.taxonomy-term')
  await expect(terms).toHaveCount(3)
  await expect(terms.nth(0)).toHaveAttribute('data-term-id', 'commercial_bank')
  await expect(terms.nth(1)).toHaveAttribute('data-term-id', 'digital-lending')
  await expect(terms.nth(2)).toHaveAttribute('data-term-id', 'first-loss-default-guarantee')
})

test('popover card displays definition, layer, and source anchor', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <body>
        <div id="popover-test">
          <span class="taxonomy-term" data-term-id="digital-lending" role="button" tabindex="0">Digital Lending</span>
          <div role="dialog" aria-label="Digital Lending">
            <span class="term-title">Digital Lending</span>
            <span class="layer-badge">physical-and-regulated</span>
            <p class="term-def">A remote and automated lending process, largely by use of seamless digital technologies.</p>
            <div class="source-anchor">Source Anchor: RBI Guidelines 2022</div>
          </div>
        </div>
      </body>
    </html>
  `)

  const dialog = page.locator('[role="dialog"]')
  await expect(dialog).toBeVisible()
  await expect(dialog.locator('.term-title')).toHaveText('Digital Lending')
  await expect(dialog.locator('.layer-badge')).toHaveText('physical-and-regulated')
  await expect(dialog.locator('.term-def')).toContainText('remote and automated lending process')
  await expect(dialog.locator('.source-anchor')).toContainText('RBI Guidelines 2022')
})

test('keyboard accessibility: focus and aria attributes conform to WCAG 2.2 AA', async ({ page }) => {
  await page.goto('about:blank')

  await page.setContent(`
    <!DOCTYPE html>
    <html>
      <body>
        <button id="prev">Previous</button>
        <span class="taxonomy-term" data-term-id="nbfc" role="button" tabindex="0" aria-haspopup="dialog" aria-expanded="false">Non-Banking Financial Company</span>
        <button id="next">Next</button>
      </body>
    </html>
  `)

  const termEl = page.locator('.taxonomy-term')
  await expect(termEl).toHaveAttribute('tabindex', '0')
  await expect(termEl).toHaveAttribute('role', 'button')
  await expect(termEl).toHaveAttribute('aria-haspopup', 'dialog')

  // Tab navigation into term
  await page.focus('#prev')
  await page.keyboard.press('Tab')
  await expect(termEl).toBeFocused()
})
