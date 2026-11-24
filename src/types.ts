export type AnnotationValue = 'yes' | null

export interface NoteSection {
  title: string
  content: string
}

export interface Diagnosis {
  id: string
  label: string
  rank: number
  score?: number
  icd_rank?: number
}

export interface GroundTruthIcdCode {
  code: string
  longDescription: string
}

export type VerifierStage = 'v1' | 'v2' | 'v3' | 'v4'
export type ReasoningStage = Exclude<VerifierStage, 'v1'>

export interface ModelReasoningEntry {
  rank: number
  reason: string
  icdCode?: string
  sharedWith?: string[]
}

export interface ModelDiagnosisReasoning {
  v2?: ModelReasoningEntry
  v3?: ModelReasoningEntry
  v4?: ModelReasoningEntry
}

export interface ModelReasoning {
  modelName: string
  diagnoses: Record<string, ModelDiagnosisReasoning>
}

export interface PatientModelReasoning {
  patientId: string
  models: Record<string, ModelReasoning>
}

export interface MrrAt10Row {
  modelId: string
  model: string
  mrr: Record<VerifierStage, number | null>
  datapoints: Record<VerifierStage, number>
}

export interface MetricsData {
  globalMrrAt10: MrrAt10Row[]
  stages: VerifierStage[]
  note: string
}

export interface Annotator {
  id: string
  name: string
  type: 'human' | 'llm' | 'ai'
  active?: boolean
}

export interface ExistingAnnotation {
  annotatorId: string
  diagnosisId: string
  value: AnnotationValue
  rank?: number
  rankLabel?: string
}

export interface Patient {
  id: string
  note_id: string
  subject_id: string
  hadm_id: string
  name: string
  chief_complaint?: string
  split?: 'train' | 'test'
  // Cohort id from the backend: 'pilot' (original 70 cases) or 'test350'
  // (blind-annotation sweep). Absent records are treated as 'pilot'.
  dataset?: string
  labs?: string
  dischargeDiagnosis?: string
  groundTruthIcdCodes?: GroundTruthIcdCode[]
  sections: NoteSection[]
  diagnoses: Diagnosis[]
  mrrAt10?: MrrAt10Row[]
  existingAnnotations: ExistingAnnotation[]
}

// Map of diagnosisId -> checked (true) or explicitly unchecked (false/undefined)
export type MyAnnotations = Record<string, boolean>

// Stored per patient: patientId -> MyAnnotations
export type AnnotationStore = Record<string, MyAnnotations>

// A free-text diagnosis not present in the WikiDoc candidate list for this
// patient. Shared across all annotators (like the fixed WikiDoc list) so any
// annotator can check an existing entry or add a new one; storage/annotation
// of it reuses the same diagnosisId-keyed mechanism as regular diagnoses.
export interface CustomDiagnosis {
  id: string
  label: string
  createdBy: string
  createdAt: string
}

export type SyncStatus = 'idle' | 'loading' | 'saving' | 'saved' | 'autosaved' | 'offline' | 'error'

export interface AnnotationPayload {
  annotatorId: string
  patientId: string
  updatedAt: string
  annotations: MyAnnotations
}

export type VerificationJudgment = 'yes' | 'no' | 'unclear'
export type VerificationQuestion = 'grounding' | 'clinicalSupport'
export type VerificationItemId = 'v2' | 'a' | 'b'

export interface VerificationCase {
  patientId: string
  chiefComplaint: string
  mainDiagnosis: { diseaseName: string; v2Reasoning: string | null }
  items: {
    id: 'a' | 'b'
    icdCode: string
    icdDescription: string
    icdDescriptionCode?: string
    rationale: string
  }[]
}

export type VerificationAnswers = Partial<Record<VerificationItemId, Partial<Record<VerificationQuestion, VerificationJudgment>>>>

export interface VerificationAnnotationPayload {
  annotatorId: string
  patientId: string
  updatedAt: string
  answers: VerificationAnswers
}
