import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import type { ReactNode } from 'react'
import { PatientNav } from './components/PatientNav'
import { DischargeNote } from './components/DischargeNote'
import { DiagnosesPanel } from './components/DiagnosesPanel'
import { VerificationPanel } from './components/VerificationPanel'
import { RebuttalAudit } from './components/RebuttalAudit'
import { Toggle } from './components/Toggle'
import { useAnnotations } from './hooks/useAnnotations'
import { useVerificationAnnotations } from './hooks/useVerificationAnnotations'
import { humanAnnotators } from './config/annotators'
import type {
  AnnotationPayload,
  Annotator,
  CustomDiagnosis,
  ExistingAnnotation,
  GroundTruthIcdCode,
  Patient,
  PatientModelReasoning,
  VerifierStage,
  VerificationCase,
  VerificationItemId,
} from './types'

// Fixed column widths (px) — must match DiagnosesPanel
const DX_COL_W = 360
const DX_COSSIM_COL_W = 128
const DX_ICD_RANK_COL_W = 80
const DX_ME_COL_W = 56
const ANNO_COL_W = 112 // each annotator column (w-28)
const PANEL_PAD = 32   // p-4 on both sides

const SELECTED_ANNOTATOR_KEY = 'ddx-selected-annotator'
const ANNOTATION_STORAGE_PREFIX = 'ddx-annotations:'
const AUTO_SAVE_INTERVAL_MS = 30_000
const SAVE_STATUS_FADE_DELAY_MS = 2_000
const SAVE_STATUS_HIDE_DELAY_MS = 5_000
const PEER_REFRESH_INITIAL_DELAY_MS = 15_000
const PEER_REFRESH_INTERVAL_MS = 30_000
const PEER_NOTIFICATION_TIMEOUT_MS = 8_000
const STAGES: VerifierStage[] = ['v1', 'v2', 'v3', 'v4']
// Dataset/split views for the top toggle. 'train'/'test' filter the pilot cohort
// by split; 'test350' selects the separate blind-annotation cohort (its own
// dataset, all test split). The verification view selects a fixed draft subset.
const DATASET_VIEWS = [
  { id: 'train', label: 'train', dataset: 'pilot', split: 'train' },
  { id: 'test', label: 'test', dataset: 'pilot', split: 'test' },
  { id: 'test350', label: 'test (350)', dataset: 'test350', split: null },
  { id: 'verification70', label: 'verification (70)', dataset: 'verification70', split: null },
  { id: 'rebuttalAudit', label: 'reasoning audit', dataset: 'rebuttalAudit', split: null },
] as const
type AppView = typeof DATASET_VIEWS[number]['id']
const VISIBLE_DATASET_VIEWS = DATASET_VIEWS.filter(view => view.id !== 'verification70')

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    throw new Error(`${path} failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

function localPeerAnnotationPayloads(annotators: Annotator[]): AnnotationPayload[] {
  try {
    return humanAnnotators(annotators).flatMap(annotator => {
      const raw = localStorage.getItem(`${ANNOTATION_STORAGE_PREFIX}${annotator.id}`)
      if (!raw) {
        return []
      }
      const store = JSON.parse(raw) as Record<string, Record<string, boolean>>
      return Object.entries(store).map(([patientId, annotations]) => ({
        annotatorId: annotator.id,
        patientId,
        updatedAt: '',
        annotations,
      }))
    })
  } catch {
    return []
  }
}

function payloadsToExistingAnnotations(
  payloads: AnnotationPayload[],
  patientId: string,
  selectedAnnotatorId: string,
): ExistingAnnotation[] {
  return payloads
    .filter(payload => (
      payload.patientId === patientId &&
      payload.annotatorId !== selectedAnnotatorId
    ))
    .flatMap(payload =>
      Object.entries(payload.annotations).map(([diagnosisId, checked]) => ({
        annotatorId: payload.annotatorId,
        diagnosisId,
        value: checked ? 'yes' as const : null,
      })),
    )
}

function payloadSignature(payload: AnnotationPayload): string {
  const annotations = Object.entries(payload.annotations)
    .sort(([left], [right]) => left.localeCompare(right))
  return JSON.stringify({
    updatedAt: payload.updatedAt,
    annotations,
  })
}

function payloadKey(payload: AnnotationPayload): string {
  return `${payload.annotatorId}:${payload.patientId}`
}

function peerUpdateMessage(
  payload: AnnotationPayload,
  previousPayload: AnnotationPayload | undefined,
  annotators: Annotator[],
  patients: Patient[],
): string {
  const annotator = annotators.find(item => item.id === payload.annotatorId)
  const updatedPatient = patients.find(item => item.id === payload.patientId)
  const annotatorName = annotator?.name ?? payload.annotatorId
  const patientName = updatedPatient?.name ?? payload.patientId
  const previousAnnotations = previousPayload?.annotations ?? {}
  const diagnosisIds = new Set([
    ...Object.keys(previousAnnotations),
    ...Object.keys(payload.annotations),
  ])

  for (const diagnosisId of diagnosisIds) {
    const previousChecked = Boolean(previousAnnotations[diagnosisId])
    const nextChecked = Boolean(payload.annotations[diagnosisId])
    if (previousChecked === nextChecked) {
      continue
    }

    const diagnosis = updatedPatient?.diagnoses.find(item => item.id === diagnosisId)
    const diagnosisLabel = diagnosis?.label ?? diagnosisId
    return nextChecked
      ? `${annotatorName} annotated ${diagnosisLabel} for ${patientName}`
      : `${annotatorName} removed ${diagnosisLabel} for ${patientName}`
  }

  return `${annotatorName} updated annotations for ${patientName}`
}

interface FoldablePanelProps {
  title: string
  children: ReactNode
}

function FoldablePanel({ title, children }: FoldablePanelProps) {
  return (
    <details className="group rounded-lg border border-gray-200 bg-white overflow-hidden">
      <summary className="flex items-center gap-2 px-4 py-3 cursor-pointer list-none select-none hover:bg-gray-50 transition-colors">
        <svg
          className="w-4 h-4 text-gray-400 transition-transform duration-200 group-open:rotate-90 shrink-0"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="text-sm font-medium text-gray-700">{title}</span>
      </summary>
      <div className="px-4 pb-4 pt-2 text-sm text-gray-600 border-t border-gray-100">
        {children}
      </div>
    </details>
  )
}

function GroundTruthIcdList({ codes }: { codes: GroundTruthIcdCode[] }) {
  if (!codes.length) {
    return <span className="text-gray-400">No ICD codes available.</span>
  }

  return (
    <ul className="flex flex-col gap-2">
      {codes.map((item, index) => (
        <li key={`${item.code}-${index}`} className="grid grid-cols-[5rem_1fr] gap-3">
          <span className="font-mono text-xs text-gray-500 pt-0.5">{item.code}</span>
          <span>{item.longDescription || 'Description not found'}</span>
        </li>
      ))}
    </ul>
  )
}

export default function App() {
  const [patients, setPatients] = useState<Patient[]>([])
  const [annotators, setAnnotators] = useState<Annotator[]>([])
  const [verificationCases, setVerificationCases] = useState<VerificationCase[]>([])
  const [dataStatus, setDataStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [dataError, setDataError] = useState<string | null>(null)
  const [patientIndex, setPatientIndex] = useState(0)
  const [selectedView, setSelectedView] = useState<AppView>('train')
  const [selectedAnnotatorId, setSelectedAnnotatorId] = useState<string>(() => {
    try {
      return localStorage.getItem(SELECTED_ANNOTATOR_KEY) ?? ''
    } catch {
      return ''
    }
  })
  const [showSimilarityScores, setShowSimilarityScores] = useState(false)
  const [showIcdRanks, setShowIcdRanks] = useState(false)
  const [showDiagnosisHelp, setShowDiagnosisHelp] = useState(true)
  const [showModelReasoning, setShowModelReasoning] = useState(true)
  const [showVerificationV2, setShowVerificationV2] = useState(true)
  const [showVerificationV4, setShowVerificationV4] = useState(true)
  const [visibleStages, setVisibleStages] = useState<Record<VerifierStage, boolean>>({
    v1: true,
    v2: true,
    v3: true,
    v4: true,
  })
  const [showHuman, setShowHuman] = useState(true)
  const [showLLM, setShowLLM] = useState(true)
  const [showAI, setShowAI] = useState(false)
  const [modelReasoningByPatient, setModelReasoningByPatient] = useState<
    Record<string, PatientModelReasoning | null>
  >({})
  const [customDiagnosesByPatient, setCustomDiagnosesByPatient] = useState<
    Record<string, CustomDiagnosis[]>
  >({})
  const [peerAnnotationPayloads, setPeerAnnotationPayloads] = useState<AnnotationPayload[]>([])
  const [peerNotification, setPeerNotification] = useState<string | null>(null)
  const [autoSaveRevision, setAutoSaveRevision] = useState(0)
  const [completedSaveLabel, setCompletedSaveLabel] = useState<'Saved' | 'Autosaved' | null>(null)
  const [completedSaveSequence, setCompletedSaveSequence] = useState(0)
  const [saveStatusVisible, setSaveStatusVisible] = useState(true)
  const [saveStatusFading, setSaveStatusFading] = useState(false)
  const autoSaveInFlight = useRef(false)
  const dirtyPatientIds = useRef<Set<string>>(new Set())
  const peerAnnotationSnapshot = useRef<Map<string, string>>(new Map())
  const peerAnnotationPayloadByKey = useRef<Map<string, AnnotationPayload>>(new Map())
  const peerRefreshRequestId = useRef(0)
  const notifyNextPeerPayload = useRef(false)

  const activeHumanAnnotators = useMemo(() => humanAnnotators(annotators), [annotators])

  const { toggle, save, getForPatient, store, syncStatus, syncError } = useAnnotations(
    selectedAnnotatorId || null,
  )
  const verification = useVerificationAnnotations(selectedAnnotatorId || null)
  const isVerificationView = selectedView === 'verification70'

  useEffect(() => {
    const controller = new AbortController()
    setDataStatus('loading')
    setDataError(null)

    Promise.all([
      fetchJson<Patient[]>('/api/patients'),
      fetchJson<Annotator[]>('/api/annotators'),
      fetchJson<VerificationCase[]>('/api/verification70').catch(() => []),
    ])
      .then(([nextPatients, nextAnnotators, nextVerificationCases]) => {
        if (controller.signal.aborted) {
          return
        }
        setPatients(nextPatients)
        setAnnotators(nextAnnotators)
        setVerificationCases(Array.isArray(nextVerificationCases) ? nextVerificationCases : [])
        setPeerAnnotationPayloads(localPeerAnnotationPayloads(nextAnnotators))
        setDataStatus('ready')
      })
      .catch(error => {
        if (controller.signal.aborted) {
          return
        }
        setDataError(error instanceof Error ? error.message : 'Could not load application data.')
        setDataStatus('error')
      })

    return () => controller.abort()
  }, [])

  const patientsForSplit = useMemo(
    () => {
      const view = DATASET_VIEWS.find(candidate => candidate.id === selectedView) ?? DATASET_VIEWS[0]
      if (view.id === 'verification70') {
        const byId = new Map(patients.map(item => [item.id, item]))
        return verificationCases.flatMap(item => {
          const match = byId.get(item.patientId)
          return match ? [match] : []
        })
      }
      return patients
        .filter(patient => {
          // Records without a dataset field are the original pilot cohort.
          if ((patient.dataset ?? 'pilot') !== view.dataset) return false
          // A view with split=null (test350) accepts every case in its dataset.
          if (view.split && (patient.split ?? 'train') !== view.split) return false
          return true
        })
        .sort((left, right) => (
          (left.chief_complaint ?? '').localeCompare(right.chief_complaint ?? '')
        ))
    },
    [patients, selectedView, verificationCases],
  )
  const visiblePatients = patientsForSplit.length > 0 || isVerificationView ? patientsForSplit : patients
  const verificationCase = isVerificationView
    ? verificationCases.find(item => item.patientId === visiblePatients[Math.min(patientIndex, visiblePatients.length - 1)]?.id)
    : undefined
  const patient = visiblePatients.length > 0
    ? visiblePatients[Math.min(patientIndex, visiblePatients.length - 1)]
    : null

  useEffect(() => {
    if (!patient || Object.prototype.hasOwnProperty.call(modelReasoningByPatient, patient.id)) {
      return
    }

    const controller = new AbortController()
    fetch(`/api/model-reasoning/${encodeURIComponent(patient.id)}`, {
      signal: controller.signal,
    })
      .then(async response => {
        if (!response.ok) {
          throw new Error(`Model reasoning load failed (${response.status})`)
        }
        return response.json() as Promise<PatientModelReasoning>
      })
      .then(reasoning => {
        if (controller.signal.aborted) {
          return
        }
        const validReasoning = reasoning?.patientId === patient.id && reasoning.models
          ? reasoning
          : null
        setModelReasoningByPatient(previous => ({
          ...previous,
          [patient.id]: validReasoning,
        }))
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setModelReasoningByPatient(previous => ({
            ...previous,
            [patient.id]: null,
          }))
        }
      })

    return () => controller.abort()
  }, [modelReasoningByPatient, patient])

  useEffect(() => {
    if (!patient || Object.prototype.hasOwnProperty.call(customDiagnosesByPatient, patient.id)) {
      return
    }

    const controller = new AbortController()
    fetch(`/api/custom-diagnoses/${encodeURIComponent(patient.id)}`, {
      signal: controller.signal,
    })
      .then(async response => {
        if (!response.ok) {
          throw new Error(`Custom diagnoses load failed (${response.status})`)
        }
        return response.json() as Promise<CustomDiagnosis[]>
      })
      .then(customDiagnoses => {
        if (controller.signal.aborted) {
          return
        }
        setCustomDiagnosesByPatient(previous => ({
          ...previous,
          [patient.id]: customDiagnoses,
        }))
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setCustomDiagnosesByPatient(previous => ({
            ...previous,
            [patient.id]: [],
          }))
        }
      })

    return () => controller.abort()
  }, [customDiagnosesByPatient, patient])

  const refreshPeerAnnotations = useCallback(async (notify = false) => {
    if (typeof fetch !== 'function') {
      const localPayloads = localPeerAnnotationPayloads(annotators)
      setPeerAnnotationPayloads(localPayloads)
      return localPayloads
    }

    const requestId = peerRefreshRequestId.current + 1
    peerRefreshRequestId.current = requestId

    try {
      const response = await fetch('/api/annotations')
      if (!response.ok) {
        throw new Error(`Annotation load failed (${response.status})`)
      }
      const payloads = await response.json() as AnnotationPayload[]
      if (requestId !== peerRefreshRequestId.current) {
        return null
      }

      notifyNextPeerPayload.current = notify
      setPeerAnnotationPayloads(payloads)
      return payloads
    } catch {
      return null
    }
  }, [])

  useEffect(() => {
    const nextSnapshot = new Map(
      peerAnnotationPayloads.map(payload => [payloadKey(payload), payloadSignature(payload)]),
    )

    if (notifyNextPeerPayload.current) {
      const updatedPayload = peerAnnotationPayloads.find(payload => (
        payload.annotatorId !== selectedAnnotatorId &&
        nextSnapshot.get(payloadKey(payload)) !== peerAnnotationSnapshot.current.get(payloadKey(payload))
      ))

      if (updatedPayload) {
        setPeerNotification(
          peerUpdateMessage(
            updatedPayload,
            peerAnnotationPayloadByKey.current.get(payloadKey(updatedPayload)),
            annotators,
            patients,
          ),
        )
      }
    }

    notifyNextPeerPayload.current = false
    peerAnnotationSnapshot.current = nextSnapshot
    peerAnnotationPayloadByKey.current = new Map(
      peerAnnotationPayloads.map(payload => [payloadKey(payload), payload]),
    )
  }, [annotators, patients, peerAnnotationPayloads, selectedAnnotatorId])

  useEffect(() => {
    if (dataStatus === 'ready') {
      void refreshPeerAnnotations()
    }
  }, [dataStatus, refreshPeerAnnotations, selectedAnnotatorId])

  useEffect(() => {
    if (dataStatus !== 'ready') {
      return
    }

    const timeout = window.setTimeout(() => {
      void refreshPeerAnnotations(true)
      const interval = window.setInterval(() => {
        void refreshPeerAnnotations(true)
      }, PEER_REFRESH_INTERVAL_MS)

      peerPollInterval = interval
    }, PEER_REFRESH_INITIAL_DELAY_MS)

    let peerPollInterval: number | null = null
    return () => {
      window.clearTimeout(timeout)
      if (peerPollInterval !== null) {
        window.clearInterval(peerPollInterval)
      }
    }
  }, [dataStatus, refreshPeerAnnotations])

  useEffect(() => {
    if (!peerNotification) {
      return
    }

    const timeout = window.setTimeout(() => {
      setPeerNotification(null)
    }, PEER_NOTIFICATION_TIMEOUT_MS)

    return () => window.clearTimeout(timeout)
  }, [peerNotification])

  useEffect(() => {
    if (dataStatus !== 'ready' || !patient || !selectedAnnotatorId) {
      return
    }

    const timeout = window.setTimeout(() => {
      if (!dirtyPatientIds.current.has(patient.id) || autoSaveInFlight.current) {
        return
      }

      const annotations = getForPatient(patient.id)
      if (Object.keys(annotations).length === 0) {
        dirtyPatientIds.current.delete(patient.id)
        return
      }

      autoSaveInFlight.current = true
      void save(patient.id, { successStatus: 'autosaved' })
        .then(saved => {
          if (saved) {
            dirtyPatientIds.current.delete(patient.id)
          }
          return refreshPeerAnnotations()
        })
        .finally(() => {
          autoSaveInFlight.current = false
        })
    }, AUTO_SAVE_INTERVAL_MS)

    return () => window.clearTimeout(timeout)
  }, [autoSaveRevision, dataStatus, getForPatient, patient, refreshPeerAnnotations, save, selectedAnnotatorId])

  useEffect(() => {
    if (syncStatus === 'saved' || syncStatus === 'autosaved') {
      setCompletedSaveLabel(syncStatus === 'autosaved' ? 'Autosaved' : 'Saved')
      setCompletedSaveSequence(value => value + 1)
      return
    }

    if (syncStatus === 'saving' || syncStatus === 'offline' || syncStatus === 'error') {
      setSaveStatusVisible(true)
      setSaveStatusFading(false)
      if (syncStatus === 'saving') {
        setCompletedSaveLabel(null)
      }
    }
  }, [syncStatus])

  useEffect(() => {
    if (!completedSaveLabel) {
      return
    }

    setSaveStatusVisible(true)
    setSaveStatusFading(false)
    const fadeTimeout = window.setTimeout(() => {
      setSaveStatusFading(true)
    }, SAVE_STATUS_FADE_DELAY_MS)
    const hideTimeout = window.setTimeout(() => {
      setSaveStatusVisible(false)
    }, SAVE_STATUS_HIDE_DELAY_MS)

    return () => {
      window.clearTimeout(fadeTimeout)
      window.clearTimeout(hideTimeout)
    }
  }, [completedSaveLabel, completedSaveSequence])

  const visibleAnnotators = useMemo(
    () => annotators.filter(annotator => (
      annotator.type !== 'human' || annotator.id !== selectedAnnotatorId
    )),
    [annotators, selectedAnnotatorId],
  )

  const displayExistingAnnotations = useMemo(
    () => patient
      ? [
        ...patient.existingAnnotations,
        ...payloadsToExistingAnnotations(peerAnnotationPayloads, patient.id, selectedAnnotatorId),
      ]
      : [],
    [patient, peerAnnotationPayloads, selectedAnnotatorId],
  )


  const savePatient = useCallback(
    async (patientId: string, successStatus: 'saved' | 'autosaved' = 'saved') => {
      const saved = await save(patientId, { successStatus })
      if (saved) {
        dirtyPatientIds.current.delete(patientId)
      }
      await refreshPeerAnnotations()
      return saved
    },
    [refreshPeerAnnotations, save],
  )

  const handleDiagnosisToggle = useCallback(
    (patientId: string, diagnosisId: string) => {
      toggle(patientId, diagnosisId)
      dirtyPatientIds.current.add(patientId)
      setAutoSaveRevision(value => value + 1)
    },
    [toggle],
  )

  const handleAddCustomDiagnosis = useCallback(
    async (patientId: string, label: string) => {
      if (!selectedAnnotatorId) {
        return
      }
      try {
        const response = await fetch(`/api/custom-diagnoses/${encodeURIComponent(patientId)}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ label, createdBy: selectedAnnotatorId }),
        })
        if (!response.ok) {
          return
        }
        const entry = await response.json() as CustomDiagnosis
        setCustomDiagnosesByPatient(previous => {
          const existing = previous[patientId] ?? []
          if (existing.some(item => item.id === entry.id)) {
            return previous
          }
          return { ...previous, [patientId]: [...existing, entry] }
        })
        if (!getForPatient(patientId)[entry.id]) {
          handleDiagnosisToggle(patientId, entry.id)
        }
      } catch {
        // Backend unreachable; the diagnosis simply won't appear this session.
      }
    },
    [getForPatient, handleDiagnosisToggle, selectedAnnotatorId],
  )

  const handleRemoveCustomDiagnosis = useCallback(
    async (patientId: string, diagnosisId: string) => {
      try {
        const response = await fetch(
          `/api/custom-diagnoses/${encodeURIComponent(patientId)}/${encodeURIComponent(diagnosisId)}`,
          { method: 'DELETE' },
        )
        if (!response.ok) {
          return
        }
      } catch {
        return
      }
      setCustomDiagnosesByPatient(previous => ({
        ...previous,
        [patientId]: (previous[patientId] ?? []).filter(item => item.id !== diagnosisId),
      }))
    },
    [],
  )

  const handleAnnotatorChange = useCallback((nextAnnotatorId: string) => {
    const changeAnnotator = async () => {
      if (patient && selectedAnnotatorId && selectedView !== 'rebuttalAudit') {
        if (isVerificationView) await verification.save(patient.id)
        else await savePatient(patient.id)
      }

      setSelectedAnnotatorId(nextAnnotatorId)
      try {
        if (nextAnnotatorId) {
          localStorage.setItem(SELECTED_ANNOTATOR_KEY, nextAnnotatorId)
        } else {
          localStorage.removeItem(SELECTED_ANNOTATOR_KEY)
        }
      } catch {
        // Ignore unavailable localStorage; explicit save will still report backend state.
      }
    }

    void changeAnnotator()
  }, [patient, savePatient, selectedAnnotatorId, selectedView, isVerificationView, verification.save])

  const handlePatientChange = useCallback(
    (next: number) => {
      if (!patient) {
        return
      }
      const boundedNext = Math.max(0, Math.min(next, visiblePatients.length - 1))
      if (boundedNext === patientIndex) {
        return
      }
      if (selectedAnnotatorId) {
        if (isVerificationView) void verification.save(patient.id)
        else void savePatient(patient.id)
      }
      setPatientIndex(boundedNext)
    },
    [patient, patientIndex, savePatient, selectedAnnotatorId, visiblePatients.length,
      isVerificationView, verification.save],
  )

  const handleViewChange = useCallback((view: AppView) => {
    if (!patient) {
      setSelectedView(view)
      setPatientIndex(0)
      return
    }
    if (view === selectedView) {
      return
    }
    if (selectedAnnotatorId && selectedView !== 'rebuttalAudit') {
      if (isVerificationView) void verification.save(patient.id)
      else void savePatient(patient.id)
    }
    setSelectedView(view)
    setPatientIndex(0)
  }, [patient, savePatient, selectedAnnotatorId, selectedView,
    isVerificationView, verification.save])

  // A patient counts as annotated (for the current annotator) once at least one
  // diagnosis is marked true in the local+synced store.
  const isAnnotated = useCallback(
    (patientId: string) => Object.values(store[patientId] ?? {}).some(Boolean),
    [store],
  )

  const handleJumpToNextUnannotated = useCallback(() => {
    const count = visiblePatients.length
    if (count === 0) return
    // Scan forward from the current position (wrapping) for the first patient
    // this annotator has not yet annotated.
    for (let step = 1; step <= count; step += 1) {
      const index = (patientIndex + step) % count
      const candidateId = visiblePatients[index].id
      const caseData = verificationCases.find(item => item.patientId === candidateId)
      const requiredItems: VerificationItemId[] = []
      if (showVerificationV2 && caseData?.mainDiagnosis.v2Reasoning) requiredItems.push('v2')
      if (showVerificationV4) requiredItems.push('a', 'b')
      if (!(isVerificationView
        ? verification.isComplete(candidateId, requiredItems)
        : isAnnotated(candidateId))) {
        if (patient && selectedAnnotatorId) {
          if (isVerificationView) void verification.save(patient.id)
          else void savePatient(patient.id)
        }
        setPatientIndex(index)
        return
      }
    }
    setPeerNotification('All cases in this view are annotated.')
  }, [visiblePatients, patientIndex, isAnnotated, patient, selectedAnnotatorId,
    savePatient, isVerificationView, verification.isComplete, verification.save,
    verificationCases, showVerificationV2, showVerificationV4])

  const handleStageChange = useCallback((stage: VerifierStage, checked: boolean) => {
    setVisibleStages(previous => ({
      ...previous,
      [stage]: checked,
    }))
  }, [])

  const saveLabel = syncStatus === 'saving'
    ? 'Saving...'
    : syncStatus === 'offline'
      ? 'Offline'
      : syncStatus === 'error'
        ? 'Save failed'
        : completedSaveLabel ?? ''

  const rightPanelWidth = useMemo(
    () => {
      const visibleAnnotatorCount = visibleAnnotators.filter(
        a =>
          (a.type === 'human' && showHuman) ||
          (a.type === 'llm' && showLLM) ||
          (a.type === 'ai' && showAI),
      ).length

      return DX_COL_W +
      (showSimilarityScores ? DX_COSSIM_COL_W : 0) +
      (showIcdRanks ? DX_ICD_RANK_COL_W : 0) +
      (selectedAnnotatorId ? DX_ME_COL_W : 0) +
      visibleAnnotatorCount * ANNO_COL_W +
      PANEL_PAD
    },
    [showHuman, showLLM, showAI, showSimilarityScores, showIcdRanks, selectedAnnotatorId, visibleAnnotators],
  )

  if (dataStatus === 'loading') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="rounded-lg border border-gray-200 bg-white px-5 py-4 text-sm text-gray-600 shadow-sm">
          Loading annotation dataset...
        </div>
      </div>
    )
  }

  if (selectedView === 'rebuttalAudit') {
    return <RebuttalAudit
      annotators={annotators}
      annotatorId={selectedAnnotatorId}
      onAnnotatorChange={handleAnnotatorChange}
      onViewChange={handleViewChange}
    />
  }

  if (dataStatus === 'error' || !patient) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
        <div className="max-w-lg rounded-lg border border-red-200 bg-white px-5 py-4 text-sm text-red-700 shadow-sm">
          {dataError ?? 'No patients are available from the annotation backend.'}
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {peerNotification && (
        <div
          role="status"
          className="fixed right-4 top-4 z-50 max-w-sm rounded-lg border border-blue-200 bg-white px-4 py-3 text-sm text-gray-700 shadow-lg"
        >
          <div className="flex items-start gap-3">
            <span className="mt-0.5 h-2 w-2 rounded-full bg-blue-600 shrink-0" aria-hidden="true" />
            <span className="min-w-0">{peerNotification}</span>
            <button
              type="button"
              aria-label="Dismiss update notification"
              onClick={() => setPeerNotification(null)}
              className="ml-2 shrink-0 text-gray-400 hover:text-gray-600"
            >
              x
            </button>
          </div>
        </div>
      )}
      {/* Top bar */}
      <header className="bg-white border-b border-gray-200 px-6 py-3 sticky top-0 z-10 shadow-sm">
        <div className="flex items-center gap-6">
          <span className="text-base font-bold text-blue-700 tracking-tight mr-2">DDx Annotator</span>

          <PatientNav
            current={patientIndex}
            total={visiblePatients.length}
            name={patient.name}
            onPrev={() => handlePatientChange(patientIndex - 1)}
            onNext={() => handlePatientChange(patientIndex + 1)}
            onJump={handlePatientChange}
          />

          <div className="ml-auto flex items-center gap-6">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <span className="text-sm text-gray-600">Annotator</span>
              <select
                aria-label="Annotator"
                value={selectedAnnotatorId}
                onChange={event => handleAnnotatorChange(event.target.value)}
                className="rounded-md border border-gray-300 bg-white px-2 py-1 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="">Evaluation mode</option>
                {activeHumanAnnotators.map(annotator => (
                  <option key={annotator.id} value={annotator.id}>
                    {annotator.name}
                  </option>
                ))}
              </select>
            </label>
            {!isVerificationView && (
              <>
                <Toggle label="Human annotators" checked={showHuman} onChange={setShowHuman} />
                <Toggle label="MERLIN predictions" checked={showLLM} onChange={setShowLLM} />
                <Toggle label="AI annotators" checked={showAI} onChange={setShowAI} />
              </>
            )}
            <button
              onClick={() => void (isVerificationView ? verification.save(patient.id) : savePatient(patient.id))}
              disabled={(isVerificationView ? verification.status === 'saving' : syncStatus === 'saving') || !selectedAnnotatorId}
              title={(isVerificationView ? verification.error : syncError) ?? undefined}
              className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-sm font-medium rounded-lg transition-colors shadow-sm"
            >
              Save
            </button>
            {(isVerificationView ? verification.status !== 'idle' : Boolean(saveLabel && saveStatusVisible)) && (
              <span
                className={`min-w-[4.5rem] text-xs text-gray-500 transition-opacity duration-[3000ms] ${
                  saveStatusFading ? 'opacity-0' : 'opacity-100'
                }`}
                title={(isVerificationView ? verification.error : syncError) ?? undefined}
              >
                {isVerificationView ? verification.status : saveLabel}
              </span>
            )}
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between gap-6">
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-md border border-gray-300 bg-white p-0.5" aria-label="Dataset split">
              {VISIBLE_DATASET_VIEWS.map(view => (
                <button
                  key={view.id}
                  type="button"
                  aria-pressed={selectedView === view.id}
                  onClick={() => handleViewChange(view.id)}
                  className={`px-3 py-1 text-sm font-medium rounded transition-colors ${
                    selectedView === view.id
                      ? 'bg-blue-600 text-white shadow-sm'
                      : 'text-gray-600 hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed'
                  }`}
                >
                  {view.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={handleJumpToNextUnannotated}
              disabled={!selectedAnnotatorId || visiblePatients.length === 0
                || (isVerificationView && !showVerificationV2 && !showVerificationV4)}
              title="Jump to the next case you have not annotated yet"
              className="px-3 py-1 text-sm font-medium rounded-md border border-gray-300 bg-white text-gray-700 hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Jump to next unannotated
            </button>
          </div>

          {!isVerificationView && <div className="flex items-center gap-6">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showSimilarityScores}
                onChange={event => setShowSimilarityScores(event.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm text-gray-600">Show diagnosis_cossim</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showIcdRanks}
                onChange={event => setShowIcdRanks(event.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm text-gray-600">Show icd_rank</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showDiagnosisHelp}
                onChange={event => setShowDiagnosisHelp(event.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm text-gray-600">Show diagnosis help</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showModelReasoning}
                onChange={event => setShowModelReasoning(event.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm text-gray-600">Show model reasoning</span>
            </label>
            <div className="flex items-center gap-3">
              {STAGES.map(stage => (
                <label key={stage} className="flex items-center gap-1 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={visibleStages[stage]}
                    onChange={event => handleStageChange(stage, event.target.checked)}
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-sm text-gray-600">{stage}</span>
                </label>
              ))}
            </div>
          </div>}
        </div>
      </header>

      {/* Note metadata bar */}
      <div className="bg-gray-50 border-b border-gray-200 px-6 py-1.5 flex items-center gap-6 text-xs text-gray-500">
        <span><span className="font-medium text-gray-700">subject_id</span> {patient.subject_id}</span>
        <span><span className="font-medium text-gray-700">hadm_id</span> {patient.hadm_id}</span>
        {patient.split && (
          <span><span className="font-medium text-gray-700">split</span> {patient.split}</span>
        )}
        {patient.chief_complaint && (
          <span><span className="font-medium text-gray-700">chief_complaint</span> {patient.chief_complaint}</span>
        )}
      </div>

      {/* Main layout — note fills remaining width; diagnoses panel has computed fixed width */}
      <main className="flex flex-1 overflow-hidden">
        {/* Left — Discharge Note: flex-1 takes all remaining space */}
        <section className={`${isVerificationView ? 'w-1/2' : 'flex-1'} min-w-0 border-r border-gray-200 bg-white overflow-y-auto p-4 flex flex-col gap-3`}>
          {!isVerificationView && <>
          <FoldablePanel title="Labs">
            <div className="whitespace-pre-wrap break-words">
              {patient.labs || <span className="text-gray-400">No labs available.</span>}
            </div>
          </FoldablePanel>

          <FoldablePanel title="Discharge Diagnosis">
            <div className="whitespace-pre-line">
              {patient.dischargeDiagnosis || <span className="text-gray-400">No discharge diagnosis available.</span>}
            </div>
          </FoldablePanel>

          <FoldablePanel title="Ground Truth ICD Codes">
            <GroundTruthIcdList codes={patient.groundTruthIcdCodes ?? []} />
          </FoldablePanel>
          </>}

          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500 px-1">
            {isVerificationView ? 'Admission information' : 'Discharge Note'}
          </h2>
          <DischargeNote key={patient.id} sections={patient.sections} admissionOnly={isVerificationView} />
        </section>

        {isVerificationView ? (
          <section aria-label="Verification panel" className="w-1/2 min-w-0 overflow-y-auto bg-gray-50 p-4">
            {verificationCase && <VerificationPanel
              caseData={verificationCase}
              answers={verification.store[patient.id] ?? {}}
              onAnswer={(itemId, question, value) =>
                verification.setAnswer(patient.id, itemId, question, value)}
              canAnnotate={!!selectedAnnotatorId}
              showV2={showVerificationV2}
              showV4={showVerificationV4}
              onToggleV2={setShowVerificationV2}
              onToggleV4={setShowVerificationV4}
            />}
          </section>
        ) : (
          <section
            aria-label="Diagnoses panel"
            className="shrink-0 overflow-auto bg-white"
            style={{ width: rightPanelWidth, transition: 'width 300ms ease' }}
          >
            <div className="p-4">
              <div className="rounded-lg border border-gray-200 overflow-hidden">
                <DiagnosesPanel
                diagnoses={patient.diagnoses}
                myAnnotations={getForPatient(patient.id)}
                onToggle={diagnosisId => handleDiagnosisToggle(patient.id, diagnosisId)}
                customDiagnoses={customDiagnosesByPatient[patient.id] ?? []}
                onAddCustomDiagnosis={label => void handleAddCustomDiagnosis(patient.id, label)}
                onRemoveCustomDiagnosis={
                  diagnosisId => void handleRemoveCustomDiagnosis(patient.id, diagnosisId)
                }
                canAnnotate={!!selectedAnnotatorId}
                showHuman={showHuman}
                showLLM={showLLM}
                showAI={showAI}
                showSimilarityScores={showSimilarityScores}
                showIcdRanks={showIcdRanks}
                showDiagnosisHelp={showDiagnosisHelp}
                showModelReasoning={showModelReasoning}
                visibleStages={visibleStages}
                existingAnnotations={displayExistingAnnotations}
                annotators={visibleAnnotators}
                modelReasoning={modelReasoningByPatient[patient.id] ?? null}
                />
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  )
}
