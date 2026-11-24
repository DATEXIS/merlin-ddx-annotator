import { useCallback, useEffect, useRef, useState } from 'react'
import type { Annotator } from '../types'
import { PatientNav } from './PatientNav'

type Judgment = 'Yes' | 'No' | 'Unclear'
type RationalePreference = 'A' | 'B' | 'Equivalent'
type TargetPreference = 'A' | 'B' | 'Equal'
type Field = 'A_Q1' | 'A_Q2' | 'B_Q1' | 'B_Q2'
type PairAnswers = Partial<Record<Field, Judgment>> & {
  target_preference_A_B_equal?: TargetPreference | null
  rationale_preference_A_B_equal?: RationalePreference
  // Retained only when loading an annotation saved by the former interface.
  preference_A_B_equivalent?: RationalePreference
  A_Q1_evidence_grounded?: Judgment
  A_Q2_supports_target?: Judgment
  B_Q1_evidence_grounded?: Judgment
  B_Q2_supports_target?: Judgment
  rater_comment?: string
}
type AuditStore = Record<string, Record<string, PairAnswers>>
type AuditPair = {
  pair_id: string
  hadm_id: string
  stage: 'V1' | 'V2' | 'V3' | 'V4'
  target_format?: 'stage_output'
  clinical_context?: string
  target_A: string
  reason_A: string
  target_B: string
  reason_B: string
  description_A?: string
  description_B?: string
  description_category_A?: string | null
  description_category_B?: string | null
}
type AuditCase = {
  hadm_id: string
  chief_complaint: string
  admission_note: string
  pairs: AuditPair[]
}
type RecordFromServer = { hadm_id: string; pairs: Record<string, PairAnswers> }
const FIELDS: Field[] = ['A_Q1', 'A_Q2', 'B_Q1', 'B_Q2']
const VIEWS = [
  ['train', 'train'], ['test', 'test'], ['test350', 'test (350)'],
  ['rebuttalAudit', 'reasoning audit'],
] as const

function storageKey(annotatorId: string) { return `ddx-rebuttal-audit:${annotatorId}` }
function dirtyKey(annotatorId: string) { return `ddx-rebuttal-audit-dirty:${annotatorId}` }
function readLocal(annotatorId: string): AuditStore {
  try { return normalizeStore(JSON.parse(localStorage.getItem(storageKey(annotatorId)) ?? '{}') as AuditStore) }
  catch { return {} }
}
function normalizeStore(store: AuditStore): AuditStore {
  return Object.fromEntries(Object.entries(store).map(([hadmId, pairs]) => [hadmId,
    Object.fromEntries(Object.entries(pairs).map(([pairId, answer]) => [pairId, {
      ...answer,
      A_Q1: answer.A_Q1 ?? answer.A_Q1_evidence_grounded,
      A_Q2: answer.A_Q2 ?? answer.A_Q2_supports_target,
      B_Q1: answer.B_Q1 ?? answer.B_Q1_evidence_grounded,
      B_Q2: answer.B_Q2 ?? answer.B_Q2_supports_target,
    }]))]))
}
function complete(pair: AuditPair, answers?: PairAnswers) {
  return FIELDS.every(field => Boolean(answers?.[field]))
    && Boolean(answers?.rationale_preference_A_B_equal)
    && (pair.target_A === pair.target_B || Boolean(answers?.target_preference_A_B_equal))
}

function PairPanel({ pair, answers, onChange, canAnnotate }: {
  pair: AuditPair
  answers: PairAnswers
  onChange: (field: Field | 'target_preference_A_B_equal' | 'rationale_preference_A_B_equal' | 'rater_comment', value: string) => void
  canAnnotate: boolean
}) {
  const allJudged = FIELDS.every(field => Boolean(answers[field]))
  const fullStage = pair.target_format === 'stage_output'
  const isV4 = pair.stage === 'V4' && !fullStage
  const stageQuestion = {
    V1: 'Does the extraction correctly and completely classify the relevant manifestations, including explicit absences and unmentioned findings?',
    V2: 'Is the differential diagnosis ranking clinically supported by the available admission evidence?',
    V3: 'Is the updated diagnosis ranking supported by the available admission and laboratory evidence?',
    V4: 'Are the predicted ICD diagnoses and their specificity clinically supported by the available evidence?',
  }[pair.stage]
  return <section aria-label={`${pair.stage} pair`} className="rounded-lg border border-gray-200 bg-white shadow-sm">
    <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between gap-3">
      <h2 className="text-base font-semibold text-gray-900">{pair.stage} clinical reasoning</h2>
      <span className="text-xs text-gray-400">Pair {pair.pair_id}</span>
    </div>
    {pair.clinical_context && <div className="border-b border-gray-200 px-4 py-3 text-sm whitespace-pre-wrap break-words">{pair.clinical_context}</div>}
    <div className="p-4 grid gap-4 xl:grid-cols-2">
      {(['A', 'B'] as const).map(arm => <div key={arm} className="rounded-lg border border-gray-200 overflow-hidden">
        <div className="border-b border-gray-100 bg-gray-50 px-3 py-2">
          <span className="text-xs font-semibold text-blue-700">Response {arm}</span>
          <h3 className="mt-1 font-semibold text-gray-900 break-words">
            {fullStage ? <span className="block whitespace-pre-wrap text-sm font-normal">{pair[`target_${arm}`]}</span> : pair[`target_${arm}`]}
            {isV4 && <span className="font-normal"> — {pair[`description_${arm}`]}</span>}
          </h3>
          {isV4 && pair[`description_category_${arm}`] && <p className="mt-1 text-xs text-amber-800">
            Closest catalog category {pair[`description_category_${arm}`]}; no exact full-code description listed.
          </p>}
        </div>
        <p className="px-3 py-3 text-sm leading-6 text-gray-800 whitespace-pre-wrap break-words">{pair[`reason_${arm}`]}</p>
        <div className="border-t border-gray-100 px-3 py-3 space-y-4">
          {([1, 2] as const).map(question => {
            const field = `${arm}_Q${question}` as Field
            const label = question === 1
              ? 'Are the clinical facts stated in this rationale supported by the patient information?'
              : fullStage ? stageQuestion
                : isV4
                ? 'Do the stated facts clinically support this specific ICD diagnosis?'
                : 'Do the stated facts clinically support this diagnosis as a plausible diagnosis for this patient?'
            return <fieldset key={field}>
              <legend className="text-sm font-medium text-gray-800">{label}</legend>
              <div className="mt-2 flex flex-wrap gap-2">
                {(['Yes', 'No', 'Unclear'] as Judgment[]).map(value => <label key={value}
                  className={`rounded border px-2 py-1 text-sm cursor-pointer ${answers[field] === value ? 'border-blue-600 bg-blue-50 text-blue-800' : 'border-gray-200 text-gray-700'}`}>
                  <input type="radio" name={`${pair.pair_id}-${field}`} value={value} checked={answers[field] === value}
                    disabled={!canAnnotate} onChange={() => onChange(field, value)} className="mr-1 accent-blue-600" />{value}
                </label>)}
              </div>
            </fieldset>
          })}
        </div>
      </div>)}
    </div>
    <div className="border-t border-gray-200 px-4 py-4">
      {pair.target_A !== pair.target_B && <fieldset disabled={!canAnnotate || !allJudged}>
        <legend className="text-sm font-semibold text-gray-900">{fullStage ? 'Which stage output is more clinically appropriate given the available evidence?' : isV4
          ? 'Which ICD diagnosis is more clinically appropriate for this patient, including whether the level of specificity is justified by the available evidence?'
          : 'Which diagnosis is more clinically appropriate for this patient at this point in the case?'}</legend>
        {isV4 && <p className="mt-1 text-xs text-gray-600">Prefer a more specific code when the evidence supports it; penalize unsupported over-specificity.</p>}
        <div className="mt-2 flex flex-wrap gap-2">
          {(['A', 'B', 'Equal'] as TargetPreference[]).map(value => <label key={value}
            className={`rounded border px-3 py-1.5 text-sm ${!allJudged ? 'opacity-50' : 'cursor-pointer'} ${answers.target_preference_A_B_equal === value ? 'border-blue-600 bg-blue-50 text-blue-800' : 'border-gray-200 text-gray-700'}`}>
            <input type="radio" name={`${pair.pair_id}-target-preference`} checked={answers.target_preference_A_B_equal === value}
              onChange={() => onChange('target_preference_A_B_equal', value)} className="mr-2 accent-blue-600" />{value === 'Equal' ? 'Equally appropriate' : value}
          </label>)}
        </div>
      </fieldset>}
      <fieldset disabled={!canAnnotate || !allJudged} className={pair.target_A !== pair.target_B ? 'mt-4' : ''}>
        <legend className="text-sm font-semibold text-gray-900">Which rationale is clinically better?</legend>
        <p className="mt-1 text-xs text-gray-600">Consider grounding in the patient record, clinical relevance, whether the reasoning supports its target, and clarity of the justification.</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {(['A', 'B', 'Equivalent'] as RationalePreference[]).map(value => <label key={value}
            className={`rounded border px-3 py-1.5 text-sm ${!allJudged ? 'opacity-50' : 'cursor-pointer'} ${answers.rationale_preference_A_B_equal === value ? 'border-blue-600 bg-blue-50 text-blue-800' : 'border-gray-200 text-gray-700'}`}>
            <input type="radio" name={`${pair.pair_id}-rationale-preference`} checked={answers.rationale_preference_A_B_equal === value}
              onChange={() => onChange('rationale_preference_A_B_equal', value)} className="mr-2 accent-blue-600" />{value}
          </label>)}
        </div>
      </fieldset>
      <label className="mt-4 block text-sm font-medium text-gray-700">Optional comment
        <textarea value={answers.rater_comment ?? ''} disabled={!canAnnotate}
          onChange={event => onChange('rater_comment', event.target.value)} rows={2}
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
      </label>
    </div>
  </section>
}

export function RebuttalAudit({ annotators, annotatorId, onAnnotatorChange, onViewChange }: {
  annotators: Annotator[]
  annotatorId: string
  onAnnotatorChange: (id: string) => void
  onViewChange: (view: 'train' | 'test' | 'test350') => void
}) {
  const [cases, setCases] = useState<AuditCase[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [answersLoaded, setAnswersLoaded] = useState(false)
  const [index, setIndex] = useState(0)
  const [store, setStore] = useState<AuditStore>({})
  const [saveStatus, setSaveStatus] = useState('')
  const storeRef = useRef<AuditStore>({})
  const pending = useRef<Record<string, number>>({})
  const dirty = useRef<Set<string>>(new Set())
  const revision = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/rebuttal-audit', { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error(`Audit data unavailable (${response.status})`)
      return response.json() as Promise<AuditCase[]>
    }).then(data => { setCases(data); setLoading(false) })
      .catch(cause => { if (!controller.signal.aborted) { setError(String(cause)); setLoading(false) } })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    setAnswersLoaded(false)
    const local = annotatorId ? readLocal(annotatorId) : {}
    try { dirty.current = new Set(JSON.parse(localStorage.getItem(dirtyKey(annotatorId)) ?? '[]') as string[]) }
    catch { dirty.current = new Set() }
    storeRef.current = local
    setStore(local)
    if (!annotatorId) { setAnswersLoaded(true); return }
    const controller = new AbortController()
    const startedAt = revision.current
    fetch(`/api/rebuttal-audit/annotations/${encodeURIComponent(annotatorId)}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(`Could not load saved answers (${response.status})`)
        return response.json() as Promise<RecordFromServer[]>
      }).then(records => {
        const remote = normalizeStore(Object.fromEntries(records.map(record => [record.hadm_id, record.pairs])))
        const next = { ...local, ...remote }
        for (const hadmId of dirty.current) {
          if (storeRef.current[hadmId]) next[hadmId] = storeRef.current[hadmId]
        }
        if (revision.current !== startedAt) Object.assign(next, storeRef.current)
        storeRef.current = next
        setStore(next)
        localStorage.setItem(storageKey(annotatorId), JSON.stringify(next))
        setAnswersLoaded(true)
      }).catch(cause => {
        if (controller.signal.aborted) return
        setError(String(cause)); setAnswersLoaded(true)
      })
    return () => controller.abort()
  }, [annotatorId])

  const save = useCallback(async (hadmId: string) => {
    if (!annotatorId || !storeRef.current[hadmId]) return
    const dirtyForSave = dirty.current
    const pairs = storeRef.current[hadmId]
    setSaveStatus('Saving…')
    try {
      const response = await fetch(`/api/rebuttal-audit/annotations/${encodeURIComponent(annotatorId)}/${encodeURIComponent(hadmId)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pairs }),
      })
      if (!response.ok) throw new Error(`Save failed (${response.status})`)
      if (dirtyForSave !== dirty.current || storeRef.current[hadmId] === pairs) {
        dirtyForSave.delete(hadmId)
        try { localStorage.setItem(dirtyKey(annotatorId), JSON.stringify([...dirtyForSave])) } catch { /* optional cache */ }
      }
      setSaveStatus('Saved')
    } catch (cause) { setSaveStatus(String(cause)) }
  }, [annotatorId])

  const change = useCallback((hadmId: string, pair: AuditPair, field: Field | 'target_preference_A_B_equal' | 'rationale_preference_A_B_equal' | 'rater_comment', value: string) => {
    revision.current += 1
    const next = { ...storeRef.current, [hadmId]: {
      ...storeRef.current[hadmId], [pair.pair_id]: {
        ...storeRef.current[hadmId]?.[pair.pair_id],
        ...(pair.target_A === pair.target_B ? { target_preference_A_B_equal: null } : {}),
        [field]: value,
      },
    } } as AuditStore
    storeRef.current = next; setStore(next); setSaveStatus('Unsaved')
    dirty.current.add(hadmId)
    try { localStorage.setItem(storageKey(annotatorId), JSON.stringify(next)) } catch { /* server save still works */ }
    try { localStorage.setItem(dirtyKey(annotatorId), JSON.stringify([...dirty.current])) } catch { /* server save still works */ }
    window.clearTimeout(pending.current[hadmId])
    pending.current[hadmId] = window.setTimeout(() => { void save(hadmId); delete pending.current[hadmId] }, 900)
  }, [annotatorId, save])

  const moveTo = (next: number) => {
    const current = cases[index]
    if (current && pending.current[current.hadm_id]) {
      window.clearTimeout(pending.current[current.hadm_id]); delete pending.current[current.hadm_id]
      void save(current.hadm_id)
    }
    setIndex(Math.max(0, Math.min(cases.length - 1, next)))
  }
  const flushPending = () => {
    for (const hadmId of Object.keys(pending.current)) {
      window.clearTimeout(pending.current[hadmId])
      delete pending.current[hadmId]
      void save(hadmId)
    }
  }
  const auditCase = cases[index]
  const pairAnswers = auditCase ? store[auditCase.hadm_id] ?? {} : {}
  const completed = cases.filter(item => item.pairs.every(pair => complete(pair, store[item.hadm_id]?.[pair.pair_id]))).length

  return <div className="min-h-screen bg-gray-50 flex flex-col">
    <header className="sticky top-0 z-10 border-b border-gray-200 bg-white px-5 py-3 shadow-sm">
      <div className="flex flex-wrap items-center gap-4">
        <span className="font-bold text-blue-700">DDx Annotator</span>
        {auditCase && <PatientNav current={index} total={cases.length} name={auditCase.chief_complaint.replace(/_/g, ' ')}
          onPrev={() => moveTo(index - 1)} onNext={() => moveTo(index + 1)} onJump={moveTo} />}
        <div className="ml-auto flex items-center gap-3">
          <label className="text-sm text-gray-700">Annotator <select aria-label="Annotator" value={annotatorId}
            onChange={event => { flushPending(); onAnnotatorChange(event.target.value) }} className="ml-2 rounded border border-gray-300 p-1">
            <option value="">Evaluation mode</option>
            {annotators.filter(a => a.type === 'human' && a.active !== false).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select></label>
          <button type="button" disabled={!annotatorId || !auditCase || !answersLoaded} onClick={() => auditCase && void save(auditCase.hadm_id)}
            className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50">Save</button>
          <span role="status" className="text-xs text-gray-500 min-w-16">{saveStatus}</span>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded border border-gray-300 bg-white p-0.5" aria-label="Dataset split">
          {VIEWS.map(([id, label]) => <button key={id} type="button" aria-pressed={id === 'rebuttalAudit'}
            onClick={() => { if (id !== 'rebuttalAudit') { flushPending(); onViewChange(id) } }}
            className={`rounded px-3 py-1 text-sm font-medium ${id === 'rebuttalAudit' ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`}>{label}</button>)}
        </div>
        <button type="button" disabled={!annotatorId || !cases.length} onClick={() => {
          for (let step = 1; step <= cases.length; step += 1) {
            const next = (index + step) % cases.length
            if (!cases[next].pairs.every(pair => complete(pair, store[cases[next].hadm_id]?.[pair.pair_id]))) { moveTo(next); return }
          }
          setSaveStatus('All admissions complete')
        }} className="rounded border border-gray-300 px-3 py-1 text-sm text-gray-700 disabled:opacity-50">Jump to next unannotated</button>
        <span className="text-sm text-gray-500">{completed} / {cases.length} admissions complete</span>
      </div>
    </header>
    {loading ? <p className="p-6 text-gray-600">Loading audit…</p> : error && !auditCase ? <p role="alert" className="p-6 text-red-700">{error}</p> : auditCase && <>
      {error && <p role="alert" className="px-5 py-2 text-sm text-red-700">{error}</p>}
      <div className="grid flex-1 min-h-0 lg:grid-cols-2">
        <section aria-label="Admission note" className="min-w-0 overflow-y-auto border-r border-gray-200 bg-white p-5 lg:h-[calc(100vh-112px)]">
          <h1 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">Admission note</h1>
          <div className="whitespace-pre-wrap break-words text-sm leading-6 text-gray-800">{auditCase.admission_note}</div>
        </section>
        <section aria-label="Clinical reasoning audit" className="min-w-0 space-y-4 overflow-y-auto p-4 lg:h-[calc(100vh-112px)]">
          {!annotatorId && <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm">Select an annotator to record answers.</p>}
          {auditCase.pairs.map(pair => <PairPanel key={pair.pair_id} pair={pair} answers={pairAnswers[pair.pair_id] ?? {}} canAnnotate={!!annotatorId && answersLoaded}
            onChange={(field, value) => change(auditCase.hadm_id, pair, field, value)} />)}
        </section>
      </div>
    </>}
  </div>
}
