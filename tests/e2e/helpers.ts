import { readFileSync } from 'node:fs'
import { expect, type Page } from '@playwright/test'

type Answer = { A_Q1: string, A_Q2: string, B_Q1: string, B_Q2: string, target: string | null, rationale: string,
  comment?: string }
const spec = JSON.parse(readFileSync('examples/synthetic/demo_cases.json', 'utf-8'))

export function syntheticAnswer(rater: string, pairId: string): Answer {
  return spec.ratings[rater][pairId]
}

/** The application opens on the DDx pilot view; the audit is one of the dataset views. */
export async function openView(page: Page, label: string) {
  await page.getByLabel('Dataset split').getByRole('button', { name: label, exact: true }).click()
}

export async function openAudit(page: Page) {
  await openView(page, 'reasoning audit')
  await expect(page.getByRole('region', { name: 'V2 pair' })).toBeVisible()
}

export async function selectAnnotator(page: Page, name: string) {
  await page.getByRole('combobox', { name: 'Annotator' }).selectOption({ label: name })
}

/** Answer one pair through the interface exactly as a rater would. */
export async function answerPair(page: Page, stage: 'V2' | 'V4', answer: Answer) {
  const region = page.getByRole('region', { name: `${stage} pair` })
  const fields = [answer.A_Q1, answer.A_Q2, answer.B_Q1, answer.B_Q2]
  for (const [index, value] of fields.entries()) {
    await region.locator('fieldset').nth(index).getByRole('radio', { name: value, exact: true }).check()
  }
  if (answer.target) {
    const label = answer.target === 'Equal' ? 'Equally appropriate' : answer.target
    await region.getByRole('group').filter({ hasText: 'more clinically appropriate' })
      .getByRole('radio', { name: label, exact: true }).check()
  }
  await region.getByRole('group').filter({ hasText: 'Which rationale is clinically better?' })
    .getByRole('radio', { name: answer.rationale, exact: true }).check()
  if (answer.comment) await region.getByLabel('Optional comment').fill(answer.comment)
}

export async function waitSaved(page: Page) {
  await expect(page.getByRole('status').filter({ hasText: /^Saved$/ })).toBeVisible()
}
