import { screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import pilot from '../../examples/synthetic/data_root/app/patients.json'
import annotators from '../../examples/synthetic/data_root/app/annotators.json'

// src/main.tsx renders the study application when the data root holds DDx cases and the
// audit-only shell otherwise (e.g. the credentialed reasoning-audit inputs).
const audit = [{
  hadm_id: 'SYN001', chief_complaint: 'chest_pain', admission_note: 'SYNTHETIC CASE - not a real patient.',
  pairs: [{ pair_id: '1', hadm_id: 'SYN001', stage: 'V2', target_A: 'Diagnosis A', reason_A: 'Reason A',
    target_B: 'Diagnosis B', reason_B: 'Reason B' }],
}]

function serve(patients: unknown[] | null) {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    if (url === '/api/patients') {
      return Promise.resolve(patients === null
        ? new Response('{"detail":"Missing data file: patients.json"}', { status: 404 })
        : new Response(JSON.stringify(patients), { status: 200 }))
    }
    const body = url === '/api/annotators' ? annotators : url === '/api/rebuttal-audit' ? audit : []
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
  }))
}

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); document.body.innerHTML = '' })

it('renders the study application when DDx cases are available', async () => {
  document.body.innerHTML = '<div id="root"></div>'
  serve(pilot)
  await import('../../src/main.tsx')
  expect(await screen.findByRole('region', { name: 'Diagnoses panel' })).toBeInTheDocument()
})

it('falls back to the audit-only shell without a DDx cohort', async () => {
  document.body.innerHTML = '<div id="root"></div>'
  serve(null)
  await import('../../src/main.tsx')
  expect(await screen.findByRole('region', { name: 'V2 pair' })).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Diagnoses panel' })).not.toBeInTheDocument()
})
