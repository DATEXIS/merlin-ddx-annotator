import { expect, test, type Locator, type Page } from '@playwright/test'
import { readdirSync, readFileSync } from 'node:fs'
import { answerPair, openAudit, openView, selectAnnotator, syntheticAnswer, waitSaved } from './helpers'

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
  await openAudit(page)
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

// DDx annotation views. The synthetic raters' records are first written through the API,
// exactly as the interface saves them (examples/synthetic/ddx/).
const DDX_OUT = 'docs/assets/screenshots/ddx'

test('DDx documentation screenshots', async ({ page, request }) => {
  const root = 'examples/synthetic/ddx'
  for (const file of readdirSync(`${root}/custom_diagnoses`)) {
    for (const item of JSON.parse(readFileSync(`${root}/custom_diagnoses/${file}`, 'utf-8'))) {
      await request.post(`/api/custom-diagnoses/${file.replace('.json', '')}`,
        { data: { label: item.label, createdBy: item.createdBy } })
    }
  }
  for (const rater of readdirSync(`${root}/annotations`).filter(r => r !== 'synthetic_rater_3')) {
    for (const file of readdirSync(`${root}/annotations/${rater}`)) {
      const record = JSON.parse(readFileSync(`${root}/annotations/${rater}/${file}`, 'utf-8'))
      await request.put(`/api/annotations/${rater}/${record.patientId}`, { data: { annotations: record.annotations } })
    }
  }
  await page.goto('/')
  await openView(page, 'test (350)')
  await selectAnnotator(page, 'Synthetic rater 3')
  await expect(page.getByText('900201 (back_pain)')).toBeVisible()
  const panel = page.getByRole('region', { name: 'Diagnoses panel' })
  await expect(panel.getByLabel('Synthetic rater 1 Vertebral osteomyelitis: annotated')).toBeVisible()
  await page.getByLabel('My annotation Vertebral osteomyelitis').check()
  await page.screenshot({ path: `${DDX_OUT}/01_case_and_candidates.png` })

  await panel.getByLabel('Model reasoning: Qwen Vertebral osteomyelitis').hover()
  await expect(page.getByRole('tooltip')).toBeVisible()
  await expect(page.getByRole('tooltip')).toHaveCSS('opacity', '1')   // wait for the fade-in
  await page.screenshot({ path: `${DDX_OUT}/02_model_ranks_and_reasoning.png` })
  await page.mouse.move(10, 10)

  await page.getByRole('switch', { name: 'Human annotators' }).click()
  await page.getByRole('switch', { name: 'MERLIN predictions' }).click()
  await expect(panel.getByLabel(/Model reasoning: Qwen/)).toHaveCount(0)
  await expect(page.getByRole('switch', { name: 'MERLIN predictions' })).toHaveAttribute('aria-checked', 'false')
  await page.waitForTimeout(600)     // switch and panel-width transitions (200 / 300 ms)
  await page.screenshot({ path: `${DDX_OUT}/03_predictions_and_peers_hidden.png` })
  await page.getByRole('switch', { name: 'Human annotators' }).click()
  await page.getByRole('switch', { name: 'MERLIN predictions' }).click()

  for (let step = 0; step < 3; step += 1) await page.getByRole('button', { name: 'Next patient' }).click()
  await expect(page.getByText('900202 (diarrhea)')).toBeVisible()
  await expect(panel.getByText('Immune checkpoint inhibitor colitis')).toBeVisible()
  await page.getByLabel('My annotation Medication-induced diarrhea').check()
  await panel.getByText('Other Disease').scrollIntoViewIfNeeded()
  await panelShot(page, panel.locator('.rounded-lg').first(), `${DDX_OUT}/04_added_diagnosis.png`)

  for (const title of ['Labs', 'Discharge Diagnosis', 'Ground Truth ICD Codes']) {
    await page.getByText(title, { exact: true }).first().click()
  }
  await page.screenshot({ path: `${DDX_OUT}/05_reference_panels.png` })
})
