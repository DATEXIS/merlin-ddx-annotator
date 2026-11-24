import { expect, test, type Page } from '@playwright/test'
import { openView, selectAnnotator } from './helpers'

// The study's DDx annotation workflow on the synthetic cohorts, against the real demo server.
const RATER = 'synthetic_rater_3'

async function goToCase(page: Page, name: string) {
  for (let step = 0; step < 6; step += 1) {
    if (await page.getByText(name, { exact: true }).count()) return
    await page.getByRole('button', { name: 'Next patient' }).click()
  }
  await expect(page.getByText(name, { exact: true })).toBeVisible()
}

test('the pilot views show the train and test splits of the pilot cohort', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('DDx Annotator')).toBeVisible()
  await expect(page.getByText('900101 (chest_pain)')).toBeVisible()
  await openView(page, 'test')
  await expect(page.getByText('900103 (abdominal_pain)')).toBeVisible()
  await expect(page.getByLabel('Dataset split').getByRole('button')).toHaveText(
    ['train', 'test', 'test (350)', 'reasoning audit'])
})

test('a synthetic rater selects a diagnosis, adds a missing one, and the server stores both', async ({ page, request }) => {
  await page.goto('/')
  await openView(page, 'test (350)')
  await selectAnnotator(page, 'Synthetic rater 3')

  await goToCase(page, '900204 (chest_pain)')
  await page.getByLabel('My annotation Pulmonary embolism').check()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Saved', { exact: true })).toBeVisible()

  await goToCase(page, '900205 (cough)')
  await page.getByLabel('Add a diagnosis not in the WikiDoc list').fill('Parapneumonic effusion')
  await page.getByLabel('Add other disease').click()
  const added = page.getByLabel('My annotation Parapneumonic effusion')
  await expect(added).toBeVisible()
  if (!(await added.isChecked())) await added.check()
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Saved', { exact: true })).toBeVisible()

  const records = await (await request.get(`/api/annotations/${RATER}`)).json()
  const byCase = Object.fromEntries(records.map((r: { patientId: string, annotations: object }) => [r.patientId, r.annotations]))
  expect(byCase['900204-chest_pain']).toEqual({ d2: true })
  const custom = await (await request.get('/api/custom-diagnoses/900205-cough')).json()
  expect(custom).toEqual([expect.objectContaining({ id: 'o1', label: 'Parapneumonic effusion', createdBy: RATER })])
  expect(byCase['900205-cough']).toEqual({ o1: true })

  // Reload with browser storage cleared: the selections come back from the server.
  await page.evaluate(() => localStorage.clear())
  await page.reload()
  await openView(page, 'test (350)')
  await selectAnnotator(page, 'Synthetic rater 3')
  await goToCase(page, '900204 (chest_pain)')
  await expect(page.getByLabel('My annotation Pulmonary embolism')).toBeChecked()
})
