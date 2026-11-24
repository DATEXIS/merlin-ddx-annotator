import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  VerificationAnnotationPayload,
  VerificationAnswers,
  VerificationItemId,
  VerificationJudgment,
  VerificationQuestion,
} from '../types'

type VerificationStore = Record<string, VerificationAnswers>
type SaveStatus = 'idle' | 'loading' | 'saving' | 'saved' | 'offline' | 'error'

function storageKey(annotatorId: string | null) {
  return `ddx-verification70:${annotatorId ?? 'evaluation'}`
}

function readLocal(annotatorId: string | null): VerificationStore {
  try {
    return JSON.parse(localStorage.getItem(storageKey(annotatorId)) ?? '{}') as VerificationStore
  } catch {
    return {}
  }
}

export function useVerificationAnnotations(annotatorId: string | null) {
  const [store, setStore] = useState<VerificationStore>(() => readLocal(annotatorId))
  const [status, setStatus] = useState<SaveStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const storeRef = useRef(store)
  const revision = useRef(0)

  const replaceStore = useCallback((next: VerificationStore) => {
    storeRef.current = next
    setStore(next)
    try { localStorage.setItem(storageKey(annotatorId), JSON.stringify(next)) } catch { /* optional cache */ }
  }, [annotatorId])

  useEffect(() => {
    const local = readLocal(annotatorId)
    storeRef.current = local
    setStore(local)
    setError(null)
    if (!annotatorId) { setStatus('idle'); return }
    const controller = new AbortController()
    const startedAt = revision.current
    setStatus('loading')
    fetch(`/api/verification70/annotations/${encodeURIComponent(annotatorId)}`, {
      signal: controller.signal,
    })
      .then(async response => {
        if (!response.ok) throw new Error(`Verification load failed (${response.status})`)
        return response.json() as Promise<VerificationAnnotationPayload[]>
      })
      .then(records => {
        const remote = Object.fromEntries(records.map(record => [record.patientId, record.answers]))
        replaceStore(revision.current === startedAt
          ? { ...readLocal(annotatorId), ...remote }
          : { ...remote, ...storeRef.current })
        setStatus('idle')
      })
      .catch(cause => {
        if (controller.signal.aborted) return
        setStatus('offline')
        setError(cause instanceof Error ? cause.message : 'Could not load verification answers')
      })
    return () => controller.abort()
  }, [annotatorId, replaceStore])

  const setAnswer = useCallback((patientId: string, itemId: VerificationItemId,
    question: VerificationQuestion, value: VerificationJudgment) => {
    revision.current += 1
    const current = storeRef.current[patientId] ?? {}
    replaceStore({
      ...storeRef.current,
      [patientId]: { ...current, [itemId]: { ...current[itemId], [question]: value } },
    })
  }, [replaceStore])

  const save = useCallback(async (patientId: string) => {
    if (!annotatorId) { setError('Select an annotator before saving.'); setStatus('error'); return false }
    setStatus('saving')
    setError(null)
    try {
      const response = await fetch(
        `/api/verification70/annotations/${encodeURIComponent(annotatorId)}/${encodeURIComponent(patientId)}`,
        { method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ answers: storeRef.current[patientId] ?? {} }) },
      )
      if (!response.ok) throw new Error(`Verification save failed (${response.status})`)
      setStatus('saved')
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save verification answers')
      setStatus('offline')
      return false
    }
  }, [annotatorId])

  const isComplete = useCallback((patientId: string, requiredItems: VerificationItemId[]) => {
    const answers = store[patientId]
    return requiredItems.every(itemId =>
      Boolean(answers?.[itemId]?.grounding && answers?.[itemId]?.clinicalSupport))
  }, [store])

  return { store, setAnswer, save, isComplete, status, error }
}
