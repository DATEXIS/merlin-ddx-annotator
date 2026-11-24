import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../../src/App'
import pilot from '../../examples/synthetic/data_root/app/patients.json'
import study from '../../examples/synthetic/data_root/app/patients_test350.json'
import annotators from '../../examples/synthetic/data_root/app/annotators.json'
import reasoningPilot from '../../examples/synthetic/data_root/app/model_reasoning.json'
import reasoningStudy from '../../examples/synthetic/data_root/app/model_reasoning_test350.json'

// The study's application shell (src/App.tsx, unchanged) on the synthetic DDx cohorts.
// The server is replaced by a fetch stub that answers like the study backend.
const ANNOTATIONS_DIR = 'examples/synthetic/ddx/annotations'
const peerRecords = readdirSync(ANNOTATIONS_DIR).flatMap(rater => readdirSync(join(ANNOTATIONS_DIR, rater))
  .map(file => JSON.parse(readFileSync(join(ANNOTATIONS_DIR, rater, file), 'utf-8'))))
const patients = [...pilot, ...study]
const reasoning = { ...reasoningPilot.patients, ...reasoningStudy.patients } as Record<string, unknown>

let saved: { url: string, body: unknown }[] = []

function respond(value: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } }))
}

beforeEach(() => {
  saved = []
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (init?.method === 'PUT' || init?.method === 'POST') {
      saved.push({ url, body: JSON.parse(String(init.body)) })
      if (url.startsWith('/api/custom-diagnoses/')) {
        return respond({ id: 'o1', label: (saved.at(-1)?.body as { label: string }).label,
          createdBy: 'synthetic_rater_1', createdAt: '2026-01-01T00:00:00Z' })
      }
      return respond({ record: { ...(saved.at(-1)?.body as object), updatedAt: '2026-01-01T00:00:01Z' } })
    }
    if (url === '/api/patients') return respond(patients)
    if (url === '/api/annotators') return respond(annotators)
    if (url === '/api/verification70') return respond({ detail: 'Missing data file' }, 404)
    if (url === '/api/annotations') return respond(peerRecords)
    if (url.startsWith('/api/annotations/')) {
      const id = decodeURIComponent(url.split('/').pop() ?? '')
      return respond(peerRecords.filter(record => record.annotatorId === id))
    }
    if (url.startsWith('/api/model-reasoning/')) {
      const id = decodeURIComponent(url.split('/').pop() ?? '')
      return id in reasoning ? respond(reasoning[id]) : respond({ detail: 'none' }, 404)
    }
    if (url.startsWith('/api/custom-diagnoses/')) {
      const id = decodeURIComponent(url.split('/').pop() ?? '')
      return respond(id === '900202-diarrhea'
        ? [{ id: 'o1', label: 'Immune checkpoint inhibitor colitis', createdBy: 'synthetic_rater_1',
          createdAt: '2026-01-01T00:00:00Z' }]
        : [])
    }
    if (url === '/api/rebuttal-audit') return respond([])
    return respond([])
  }))
})
afterEach(() => { vi.unstubAllGlobals() })

async function openView(user: ReturnType<typeof userEvent.setup>, label: string) {
  await screen.findByText('DDx Annotator')
  await user.click(within(screen.getByLabelText('Dataset split')).getByRole('button', { name: label }))
}

async function goToCase(user: ReturnType<typeof userEvent.setup>, name: string) {
  for (let step = 0; step < 6 && !screen.queryByText(name); step += 1) {
    await user.click(screen.getByLabelText('Next patient'))
  }
  expect(screen.getByText(name)).toBeInTheDocument()
}

describe('unified shell', () => {
  it('opens on the pilot train view and offers the pilot, 350-case and audit views, not the verification draft', async () => {
    render(<App />)
    const views = within(await screen.findByLabelText('Dataset split'))
    expect(views.getAllByRole('button').map(button => button.textContent))
      .toEqual(['train', 'test', 'test (350)', 'reasoning audit'])
    expect(views.getByRole('button', { name: 'train' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('900101 (chest_pain)')).toBeInTheDocument()
    expect(screen.queryByText(/verification/i)).not.toBeInTheDocument()
  })

  it('lists only human annotators in the selector', async () => {
    render(<App />)
    const selector = await screen.findByRole('combobox', { name: 'Annotator' })
    expect(within(selector).getAllByRole('option').map(option => option.textContent))
      .toEqual(['Evaluation mode', 'Synthetic rater 1', 'Synthetic rater 2', 'Synthetic rater 3'])
  })

  it('shows model rankings and other annotators by default, as in the study interface', async () => {
    render(<App />)
    await screen.findByText('DDx Annotator')
    expect(screen.getByRole('switch', { name: 'Human annotators' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('switch', { name: 'MERLIN predictions' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('switch', { name: 'AI annotators' })).toHaveAttribute('aria-checked', 'false')
  })

  it('selects the 350-case cohort and shows peer marks and model ranks until hidden', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openView(user, 'test (350)')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Annotator' }), 'synthetic_rater_3')
    await goToCase(user, '900201 (back_pain)')
    const panel = screen.getByRole('region', { name: 'Diagnoses panel' })
    await waitFor(() => expect(within(panel)
      .getByLabelText('Synthetic rater 1 Vertebral osteomyelitis: annotated')).toBeInTheDocument())
    expect(within(panel).getByLabelText('Model reasoning: Qwen Vertebral osteomyelitis')).toHaveTextContent('3 / 2 / 1 / 1')

    await user.click(screen.getByRole('switch', { name: 'Human annotators' }))
    await user.click(screen.getByRole('switch', { name: 'MERLIN predictions' }))
    expect(within(panel).queryByLabelText(/Synthetic rater 1 Vertebral osteomyelitis/)).not.toBeInTheDocument()
    expect(within(panel).queryByLabelText(/Model reasoning: Qwen/)).not.toBeInTheDocument()
  })

  it('records a selection and saves it in the study record format', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openView(user, 'test (350)')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Annotator' }), 'synthetic_rater_3')
    await goToCase(user, '900204 (chest_pain)')
    await user.click(screen.getByLabelText('My annotation Pulmonary embolism'))
    const stored = JSON.parse(localStorage.getItem('ddx-annotations:synthetic_rater_3') ?? '{}')
    expect(stored['900204-chest_pain']).toEqual({ d2: true })
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(saved.some(item => item.url === '/api/annotations/synthetic_rater_3/900204-chest_pain'))
      .toBe(true))
    expect(saved.find(item => item.url.endsWith('/900204-chest_pain'))?.body)
      .toMatchObject({ annotations: { d2: true } })
  })

  it('adds a diagnosis that is missing from the candidate list', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openView(user, 'test (350)')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Annotator' }), 'synthetic_rater_1')
    await goToCase(user, '900205 (cough)')
    await user.type(screen.getByLabelText('Add a diagnosis not in the WikiDoc list'), 'Parapneumonic effusion')
    await user.click(screen.getByLabelText('Add other disease'))
    await waitFor(() => expect(saved.some(item => item.url === '/api/custom-diagnoses/900205-cough')).toBe(true))
    expect(saved.find(item => item.url === '/api/custom-diagnoses/900205-cough')?.body)
      .toEqual({ label: 'Parapneumonic effusion', createdBy: 'synthetic_rater_1' })
  })

  it('shows an added diagnosis shared by all annotators of a case', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openView(user, 'test (350)')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Annotator' }), 'synthetic_rater_3')
    await goToCase(user, '900202 (diarrhea)')
    const panel = screen.getByRole('region', { name: 'Diagnoses panel' })
    expect(await within(panel).findByText('Immune checkpoint inhibitor colitis')).toBeInTheDocument()
    await waitFor(() => expect(within(panel)
      .getByLabelText('Synthetic rater 2 Immune checkpoint inhibitor colitis: annotated')).toBeInTheDocument())
  })

  it('opens the unchanged reasoning-audit screen and returns to the DDx views', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openView(user, 'reasoning audit')
    expect(await screen.findByText(/reasoning audit/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'test (350)' }))
    expect(await screen.findByText('900201 (back_pain)')).toBeInTheDocument()
  })
})
