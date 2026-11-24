import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { RebuttalAudit } from '../../src/components/RebuttalAudit'

const audit = [{
  hadm_id: '123', chief_complaint: 'cough', admission_note: 'Line one\nLine two',
  pairs: [
    { pair_id: '1', hadm_id: '123', stage: 'V2', target_A: 'Pneumonia', reason_A: 'V2 A', target_B: 'Cough', reason_B: 'V2 B' },
    { pair_id: '2', hadm_id: '123', stage: 'V4', target_A: 'J18.9', reason_A: 'V4 A', target_B: 'R05.9', reason_B: 'V4 B',
      description_A: 'Pneumonia, unspecified organism', description_B: 'Cough, unspecified' },
  ],
}]
function response(value: unknown) { return new Response(JSON.stringify(value), { status: 200 }) }
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })

it('shows both stages and unlocks target and rationale comparisons after four judgments', async () => {
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(response(
    url === '/api/rebuttal-audit' ? audit : [],
  ))))
  const user = userEvent.setup()
  render(<RebuttalAudit annotators={[{ id: 'clinician', name: 'Clinician', type: 'human' }]}
    annotatorId="clinician" onAnnotatorChange={() => {}} onViewChange={() => {}} />)
  const v2 = await screen.findByRole('region', { name: 'V2 pair' })
  const v4 = screen.getByRole('region', { name: 'V4 pair' })
  expect(within(v2).getByRole('radio', { name: 'Equivalent' })).toBeDisabled()
  expect(within(v2).getByRole('radio', { name: 'Equally appropriate' })).toBeDisabled()
  expect(within(v4).getByRole('radio', { name: 'Equivalent' })).toBeDisabled()
  await user.click(within(v4).getAllByRole('radio', { name: 'Yes' })[0])
  expect(within(v2).getByRole('radio', { name: 'Equivalent' })).toBeDisabled()
  for (const choice of within(v2).getAllByRole('radio', { name: 'Yes' })) await user.click(choice)
  expect(within(v2).getByRole('radio', { name: 'Equivalent' })).toBeEnabled()
  expect(within(v2).getByRole('radio', { name: 'Equally appropriate' })).toBeEnabled()
  await user.click(within(v2).getByRole('radio', { name: 'Equivalent' }))
  expect(screen.getByText('0 / 1 admissions complete')).toBeInTheDocument()
  await user.click(within(v2).getByRole('radio', { name: 'Equally appropriate' }))
  expect(within(v4).getByText(/J18\.9/)).toHaveTextContent('Pneumonia, unspecified organism')
  expect(within(v4).getByRole('radio', { name: 'Equivalent' })).toBeDisabled()
  await waitFor(() => expect(screen.getByRole('region', { name: 'Admission note' })).toHaveTextContent('Line one Line two'))
})

it('omits target comparison for identical targets but always asks for rationale comparison', async () => {
  const identical = [{ ...audit[0], pairs: [
    { ...audit[0].pairs[0], target_B: 'Pneumonia' }, audit[0].pairs[1],
  ] }]
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(response(
    url === '/api/rebuttal-audit' ? identical : [],
  ))))
  const user = userEvent.setup()
  render(<RebuttalAudit annotators={[{ id: 'clinician', name: 'Clinician', type: 'human' }]}
    annotatorId="clinician" onAnnotatorChange={() => {}} onViewChange={() => {}} />)
  const v2 = await screen.findByRole('region', { name: 'V2 pair' })
  expect(within(v2).queryByRole('radio', { name: 'Equally appropriate' })).not.toBeInTheDocument()
  expect(within(v2).getByRole('radio', { name: 'Equivalent' })).toBeDisabled()
  for (const choice of within(v2).getAllByRole('radio', { name: 'Yes' })) await user.click(choice)
  expect(within(v2).getByRole('radio', { name: 'Equivalent' })).toBeEnabled()
  await user.click(within(v2).getByRole('radio', { name: 'Equivalent' }))
  await waitFor(() => expect(localStorage.getItem('ddx-rebuttal-audit:clinician')).toContain('"target_preference_A_B_equal":null'))
})

it('renders all four stages with the new stage-specific rubric and evidence', async () => {
  const pairs = ['V1', 'V2', 'V3', 'V4'].map(stage => ({
    pair_id: stage, hadm_id: '123', stage, target_format: 'stage_output',
    target_A: 'Synthetic output A', target_B: 'Synthetic output B',
    reason_A: 'Synthetic rationale A', reason_B: 'Synthetic rationale B',
    clinical_context: stage === 'V3' ? 'Synthetic laboratory context.' : '',
  }))
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(response(
    url === '/api/rebuttal-audit' ? [{ ...audit[0], pairs }] : [],
  ))))
  render(<RebuttalAudit annotators={[{ id: 'clinician', name: 'Clinician', type: 'human' }]}
    annotatorId="clinician" onAnnotatorChange={() => {}} onViewChange={() => {}} />)
  const v1 = await screen.findByRole('region', { name: 'V1 pair' })
  const v3 = screen.getByRole('region', { name: 'V3 pair' })
  expect(within(v1).getAllByText(/correctly and completely classify/)).toHaveLength(2)
  expect(within(v3).getByText('Synthetic laboratory context.')).toBeInTheDocument()
  expect(within(v3).getAllByText(/updated diagnosis ranking/)).toHaveLength(2)
  expect(screen.getByRole('region', { name: 'V2 pair' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'V4 pair' })).toBeInTheDocument()
  expect(within(v1).queryByText('Synthetic laboratory context.')).not.toBeInTheDocument()
})

it('reviews a reference without demanding a generated rationale or comparison', async () => {
  const pair = {
    pair_id: 'reference-1', hadm_id: '123', stage: 'V1', target_format: 'reference_label',
    target_A: 'Synthetic manifestation labels', target_B: '', reason_A: '', reason_B: '',
    label_source: 'Synthetic disease prototype',
  }
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(response(
    url === '/api/rebuttal-audit' ? [{ ...audit[0], pairs: [pair] }] : [],
  ))))
  render(<RebuttalAudit annotators={[{ id: 'clinician', name: 'Clinician', type: 'human' }]}
    annotatorId="clinician" onAnnotatorChange={() => {}} onViewChange={() => {}} />)
  const review = await screen.findByRole('region', { name: 'V1 reference label' })
  expect(within(review).getByText('Synthetic manifestation labels')).toBeInTheDocument()
  expect(within(review).queryByText('Response B')).not.toBeInTheDocument()
  const user = userEvent.setup()
  await waitFor(() => expect(within(review).getByRole('radio', { name: 'No' })).toBeEnabled())
  await user.click(within(review).getByRole('radio', { name: 'No' }))
  await user.type(within(review).getByLabelText(/Suggested correction/), 'Synthetic correction')
  expect(screen.getByText('1 / 1 admissions complete')).toBeInTheDocument()
})

it('uses the same label-only rubric for both blinded sources', async () => {
  const pair = {
    pair_id: 'compare-1', hadm_id: '123', stage: 'V2', target_format: 'label_comparison',
    target_A: 'Synthetic diagnosis A', target_B: 'Synthetic diagnosis B', reason_A: '', reason_B: '',
  }
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(response(
    url === '/api/rebuttal-audit' ? [{ ...audit[0], pairs: [pair] }] : [],
  ))))
  render(<RebuttalAudit annotators={[{ id: 'clinician', name: 'Clinician', type: 'human' }]}
    annotatorId="clinician" onAnnotatorChange={() => {}} onViewChange={() => {}} />)
  const review = await screen.findByRole('region', { name: 'V2 label comparison' })
  expect(within(review).getAllByText('Is this diagnosis clinically appropriate given the admission evidence?')).toHaveLength(2)
  expect(within(review).queryByText(/Source:/)).not.toBeInTheDocument()
  expect(within(review).queryByText(/rationale/i)).not.toBeInTheDocument()
  expect(within(review).getByRole('radio', { name: 'Equally appropriate' })).toBeDisabled()
  const user = userEvent.setup()
  await waitFor(() => expect(within(review).getAllByRole('radio', { name: 'Yes' })[0]).toBeEnabled())
  await user.click(within(review).getAllByRole('radio', { name: 'Yes' })[0])
  await user.click(within(review).getAllByRole('radio', { name: 'No' })[1])
  await user.click(within(review).getByRole('radio', { name: 'A' }))
  expect(screen.getByText('1 / 1 admissions complete')).toBeInTheDocument()
})
