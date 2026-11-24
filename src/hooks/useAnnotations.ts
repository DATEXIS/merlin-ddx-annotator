import { useEffect, useState, useCallback, useRef } from 'react'
import type { AnnotationPayload, AnnotationStore, MyAnnotations, SyncStatus } from '../types'

const STORAGE_KEY = 'ddx-annotations'

function storageKey(annotatorId: string | null): string {
  return annotatorId ? `${STORAGE_KEY}:${annotatorId}` : STORAGE_KEY
}

function loadStore(annotatorId: string | null): AnnotationStore {
  try {
    const raw = localStorage.getItem(storageKey(annotatorId))
    return raw ? (JSON.parse(raw) as AnnotationStore) : {}
  } catch {
    return {}
  }
}

function saveStore(annotatorId: string | null, store: AnnotationStore): void {
  localStorage.setItem(storageKey(annotatorId), JSON.stringify(store))
}

function payloadToStore(payloads: AnnotationPayload[]): AnnotationStore {
  return payloads.reduce<AnnotationStore>((next, payload) => {
    next[payload.patientId] = payload.annotations
    return next
  }, {})
}

function hasBackend(): boolean {
  return typeof fetch === 'function'
}

export function useAnnotations(annotatorId: string | null) {
  const [store, setStore] = useState<AnnotationStore>(() => loadStore(annotatorId))
  const [syncStatus, setSyncStatus] = useState<SyncStatus>('idle')
  const [syncError, setSyncError] = useState<string | null>(null)
  const storeRef = useRef(store)
  const localRevision = useRef(0)

  const replaceStore = useCallback((next: AnnotationStore) => {
    storeRef.current = next
    setStore(next)
    saveStore(annotatorId, next)
  }, [annotatorId])

  useEffect(() => {
    const local = loadStore(annotatorId)
    storeRef.current = local
    setStore(local)
    setSyncError(null)

    if (!annotatorId || !hasBackend()) {
      setSyncStatus('idle')
      return
    }

    const controller = new AbortController()
    const loadStartedAtRevision = localRevision.current
    setSyncStatus('loading')
    fetch(`/api/annotations/${encodeURIComponent(annotatorId)}`, {
      signal: controller.signal,
    })
      .then(response => {
        if (!response.ok) {
          throw new Error(`Load failed (${response.status})`)
        }
        return response.json() as Promise<AnnotationPayload[]>
      })
      .then(payloads => {
        const remote = payloadToStore(payloads)
        const localAfterLoad = loadStore(annotatorId)
        const merged = localRevision.current === loadStartedAtRevision
          ? { ...localAfterLoad, ...remote }
          : { ...remote, ...localAfterLoad }
        storeRef.current = merged
        setStore(merged)
        saveStore(annotatorId, merged)
        setSyncStatus(previous => previous === 'loading' ? 'idle' : previous)
      })
      .catch(error => {
        if (error instanceof DOMException && error.name === 'AbortError') {
          return
        }
        setSyncStatus('offline')
        setSyncError(error instanceof Error ? error.message : 'Backend unavailable')
      })

    return () => controller.abort()
  }, [annotatorId])

  const toggle = useCallback((patientId: string, diagnosisId: string) => {
    localRevision.current += 1
    const patientAnnotations = storeRef.current[patientId] ?? {}
    const next: AnnotationStore = {
      ...storeRef.current,
      [patientId]: {
        ...patientAnnotations,
        [diagnosisId]: !patientAnnotations[diagnosisId],
      },
    }
    replaceStore(next)
  }, [replaceStore])

  const save = useCallback(
    async (
      patientId: string,
      options: { successStatus?: Extract<SyncStatus, 'saved' | 'autosaved'> } = {},
    ) => {
      const latestStore = storeRef.current
      saveStore(annotatorId, latestStore)
      if (!annotatorId) {
        setSyncStatus('error')
        setSyncError('Select an annotator before saving.')
        return false
      }
      if (!hasBackend()) {
        setSyncStatus('offline')
        setSyncError('Backend unavailable; saved locally.')
        return false
      }

      const annotations: MyAnnotations = latestStore[patientId] ?? {}
      setSyncStatus('saving')
      setSyncError(null)
      try {
        const response = await fetch(
          `/api/annotations/${encodeURIComponent(annotatorId)}/${encodeURIComponent(patientId)}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ annotations }),
          },
        )
        if (!response.ok) {
          const detail = await response.text()
          throw new Error(detail || `Save failed (${response.status})`)
        }
        setSyncStatus(options.successStatus ?? 'saved')
        return true
      } catch (error) {
        setSyncStatus('offline')
        setSyncError(error instanceof Error ? error.message : 'Backend unavailable; saved locally.')
        return false
      }
    },
    [annotatorId],
  )

  const getForPatient = useCallback(
    (patientId: string) => store[patientId] ?? {},
    [store],
  )

  return { toggle, save, getForPatient, store, syncStatus, syncError }
}
