import { expect, test } from '@playwright/test'
import { answerPair, selectAnnotator, syntheticAnswer, waitSaved } from './helpers'

const RATER = 'synthetic_rater_2'

test('a synthetic rater completes an admission; answers are saved by the server and exported', async ({ page, request }) => {
  await page.goto('/')
  await expect(page.getByRole('region', { name: 'Admission note' })).toContainText('SYNTHETIC CASE')
  await expect(page.getByText('Select an annotator to record answers.')).toBeVisible()
  await selectAnnotator(page, 'Synthetic rater 2')

  const v2 = page.getByRole('region', { name: 'V2 pair' })
  await expect(v2.getByRole('radio', { name: 'Equivalent' })).toBeDisabled()     // preferences wait for Q1/Q2
  await answerPair(page, 'V2', syntheticAnswer(RATER, '1'))
  await answerPair(page, 'V4', syntheticAnswer(RATER, '2'))
  await expect(page.getByRole('region', { name: 'V4 pair' }).getByText('Equally appropriate')).toHaveCount(0)  // identical targets
  await waitSaved(page)
  await expect(page.getByText('1 / 5 admissions complete')).toBeVisible()

  // Reload with browser storage cleared: answers come back from the server.
  await page.evaluate(() => localStorage.clear())
  await page.reload()
  await selectAnnotator(page, 'Synthetic rater 2')
  await expect(page.getByText('1 / 5 admissions complete')).toBeVisible()
  await expect(page.getByRole('region', { name: 'V2 pair' }).locator('fieldset').nth(3)
    .getByRole('radio', { name: 'Unclear', exact: true })).toBeChecked()

  const exported = await (await request.get(`/api/rebuttal-audit/annotations/${RATER}`)).json()
  expect(exported).toHaveLength(1)
  expect(exported[0].pairs['1'].B_Q2).toBe('Unclear')
  expect(exported[0].pairs['2'].target_preference_A_B_equal).toBeNull()

  await page.getByRole('button', { name: 'Jump to next unannotated' }).click()
  await expect(page.getByRole('region', { name: 'Admission note' })).toContainText('shortness of breath')
})
