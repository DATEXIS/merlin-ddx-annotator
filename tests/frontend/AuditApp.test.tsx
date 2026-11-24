import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { AuditApp } from '../../src/AuditApp'

const annotators = [
  { id: 'synthetic_rater_1', name: 'Synthetic rater 1', type: 'human', active: true },
  { id: 'synthetic_rater_2', name: 'Synthetic rater 2', type: 'human', active: true },
]
const audit = [{
  hadm_id: 'SYN001', chief_complaint: 'chest_pain', admission_note: 'SYNTHETIC CASE - not a real patient.',
  pairs: [
    { pair_id: '1', hadm_id: 'SYN001', stage: 'V2', target_A: 'Diagnosis A', reason_A: 'Reason A',
      target_B: 'Diagnosis B', reason_B: 'Reason B' },
    { pair_id: '2', hadm_id: 'SYN001', stage: 'V4', target_A: 'I21.4', reason_A: 'Reason C', target_B: 'I21.4',
      reason_B: 'Reason D', description_A: 'Non-ST elevation (NSTEMI) myocardial infarction',
      description_B: 'Non-ST elevation (NSTEMI) myocardial infarction' },
  ],
}]

function serve() {
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(
    url === '/api/annotators' ? annotators : url === '/api/rebuttal-audit' ? audit : [],
  ), { status: 200 }))))
}
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })

it('renders the study audit screen and lists the synthetic annotators', async () => {
  serve()
  render(<AuditApp />)
  expect(await screen.findByRole('region', { name: 'V2 pair' })).toBeInTheDocument()
  const selector = screen.getByRole('combobox', { name: 'Annotator' })
  expect(within(selector).getByRole('option', { name: 'Synthetic rater 1' })).toBeInTheDocument()
  expect(screen.getByText('Select an annotator to record answers.')).toBeInTheDocument()
})

it('remembers the selected annotator under the study key', async () => {
  serve()
  const user = userEvent.setup()
  render(<AuditApp />)
  await screen.findByRole('region', { name: 'V2 pair' })
  await user.selectOptions(screen.getByRole('combobox', { name: 'Annotator' }), 'synthetic_rater_2')
  expect(localStorage.getItem('ddx-selected-annotator')).toBe('synthetic_rater_2')
  expect(screen.queryByText('Select an annotator to record answers.')).not.toBeInTheDocument()
})

it('explains that the other study views are not included', async () => {
  serve()
  const user = userEvent.setup()
  render(<AuditApp />)
  await screen.findByRole('region', { name: 'V2 pair' })
  await user.click(screen.getByRole('button', { name: 'train' }))
  expect(screen.getByText(/belonged to a separate annotation study and are not part of this release/)).toBeInTheDocument()
})
