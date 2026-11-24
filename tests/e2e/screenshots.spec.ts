import { expect, test, type Locator, type Page } from '@playwright/test'
import { answerPair, selectAnnotator, syntheticAnswer, waitSaved } from './helpers'

// Regenerates docs/assets/screenshots/ from the running application on synthetic data:
//   CAPTURE_SCREENSHOTS=1 npx playwright test tests/e2e/screenshots.spec.ts
test.skip(!process.env.CAPTURE_SCREENSHOTS, 'set CAPTURE_SCREENSHOTS=1 to regenerate the documentation screenshots')

const OUT = 'docs/assets/screenshots'
const RATER = 'synthetic_rater_1'
test.use({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 })

// The app scrolls its panels internally under a sticky header; a tall viewport shows each
// panel whole without scrolling, and the screenshot is clipped to the panel's box.
async function panelShot(page: Page, panel: Locator, path: string) {
  await page.setViewportSize({ width: 1440, height: 2200 })
  const box = await panel.boundingBox()
  if (!box) throw new Error('panel not visible')
  await page.screenshot({ path, clip: { x: box.x - 8, y: box.y - 8, width: box.width + 16, height: box.height + 16 } })
  await page.setViewportSize({ width: 1440, height: 900 })
}

test('documentation screenshots', async ({ page }) => {
  await page.goto('/')
  await selectAnnotator(page, 'Synthetic rater 1')
  await expect(page.getByRole('region', { name: 'V2 pair' })).toBeVisible()
  await page.screenshot({ path: `${OUT}/01_clinical_context.png` })

  await answerPair(page, 'V2', syntheticAnswer(RATER, '1'))
  await panelShot(page, page.getByRole('region', { name: 'V2 pair' }), `${OUT}/02_v2_blinded_comparison.png`)

  await answerPair(page, 'V4', syntheticAnswer(RATER, '2'))
  await waitSaved(page)
  await page.setViewportSize({ width: 1440, height: 1640 })
  await expect(page.getByText('1 / 5 admissions complete')).toBeVisible()
  await page.screenshot({ path: `${OUT}/04_rating_completed.png` })

  await page.setViewportSize({ width: 1440, height: 900 })
  for (let step = 0; step < 4; step += 1) await page.getByRole('button', { name: 'Next patient' }).click()  // fifth admission
  await expect(page.getByRole('region', { name: 'Admission note' })).toContainText('dizziness')
  const v4 = page.getByRole('region', { name: 'V4 pair' })
  await v4.locator('fieldset').nth(0).getByRole('radio', { name: 'Yes', exact: true }).check()
  await v4.locator('fieldset').nth(1).getByRole('radio', { name: 'No', exact: true }).check()
  await expect(v4).toContainText('Closest catalog category R42')
  await panelShot(page, v4, `${OUT}/03_v4_icd_assessment.png`)
})
