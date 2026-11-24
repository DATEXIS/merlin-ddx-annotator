import { Fragment, useState } from 'react'
import { AnnotationIcon } from './AnnotationIcon'
import { HoverCard } from './HoverCard'
import { diagnosisHelpByLabel } from '../config/diagnosisHelp'
import type { DiagnosisHelp } from '../config/diagnosisHelp'
import type {
  Annotator,
  CustomDiagnosis,
  Diagnosis,
  ExistingAnnotation,
  ModelDiagnosisReasoning,
  MyAnnotations,
  PatientModelReasoning,
  ReasoningStage,
  VerifierStage,
} from '../types'

const ROW_H = 'h-[2.75rem]'
const MIN_ROW_H = 'min-h-[2.75rem]'
const DX_NAME_COL_W = 360
const DX_COSSIM_COL_W = 128
const DX_ICD_RANK_COL_W = 80
const ME_COL_W = 56
const ANNOTATOR_COL_W = 112
const COLLAPSE_AFTER = 10
const STAGES: VerifierStage[] = ['v1', 'v2', 'v3', 'v4']
const REASONING_STAGES: ReasoningStage[] = ['v2', 'v3', 'v4']

interface Props {
  diagnoses: Diagnosis[]
  myAnnotations: MyAnnotations
  onToggle: (diagnosisId: string) => void
  customDiagnoses: CustomDiagnosis[]
  onAddCustomDiagnosis: (label: string) => void
  onRemoveCustomDiagnosis: (diagnosisId: string) => void
  canAnnotate: boolean
  showHuman: boolean
  showLLM: boolean
  showAI: boolean
  showSimilarityScores: boolean
  showIcdRanks: boolean
  showDiagnosisHelp: boolean
  showModelReasoning: boolean
  visibleStages: Record<VerifierStage, boolean>
  existingAnnotations: ExistingAnnotation[]
  annotators: Annotator[]
  modelReasoning: PatientModelReasoning | null
}

function DiagnosisHelpContent({ help }: { help: DiagnosisHelp }) {
  return (
    <>
      <div className="border-b border-gray-100 px-4 py-3">
        <div className="text-sm font-semibold text-gray-900">{help.title}</div>
        <div className="mt-1 text-xs leading-5 text-gray-600">{help.summary}</div>
      </div>
      <div className="flex flex-col gap-3 px-4 py-3">
        {help.sections.map(section => (
          <section
            key={section.title}
            className="grid grid-cols-[7.5rem_1fr] gap-3 border-b border-gray-100 pb-3 last:border-0 last:pb-0"
          >
            <div className="text-xs font-semibold text-gray-700">{section.title}</div>
            <ul className="flex min-w-0 flex-col gap-1 text-xs leading-5 text-gray-600">
              {section.items.map(item => (
                <li key={item} className="flex gap-2">
                  <span className="mt-[0.45rem] h-1 w-1 shrink-0 rounded-full bg-gray-400" aria-hidden="true" />
                  <span className="min-w-0">{item}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <div className="border-t border-gray-100 px-4 py-2 text-[11px] leading-4 text-gray-500">
        Source: {help.sourceLabel}
      </div>
    </>
  )
}

function DiagnosisLabel({
  diagnosis,
  showDiagnosisHelp,
}: {
  diagnosis: Diagnosis
  showDiagnosisHelp: boolean
}) {
  const help = showDiagnosisHelp ? diagnosisHelpByLabel[diagnosis.label] : undefined

  if (!help) {
    return (
      <span className="text-sm text-gray-800 min-w-0 whitespace-normal break-words">
        {diagnosis.label}
      </span>
    )
  }

  return (
    <HoverCard
      ariaLabel={`Diagnosis help: ${diagnosis.label}`}
      className="text-sm text-gray-800 min-w-0 whitespace-normal break-words decoration-dotted underline-offset-4 hover:underline focus:underline focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 rounded-sm"
      content={<DiagnosisHelpContent help={help} />}
    >
      {diagnosis.label}
    </HoverCard>
  )
}

function ModelReasoningContent({
  annotator,
  diagnosis,
  modelName,
  reasoning,
  visibleStages,
}: {
  annotator: Annotator
  diagnosis: Diagnosis
  modelName: string
  reasoning: ModelDiagnosisReasoning
  visibleStages: Record<VerifierStage, boolean>
}) {
  const entries = REASONING_STAGES.flatMap(stage => {
    const entry = reasoning[stage]
    return entry && visibleStages[stage] ? [{ stage, entry }] : []
  })

  return (
    <>
      <div className="border-b border-gray-100 px-4 py-3">
        <div className="text-sm font-semibold text-gray-900">
          {annotator.name} · {diagnosis.label}
        </div>
        <div className="mt-1 text-xs text-gray-500">{modelName}</div>
      </div>
      <div className="flex flex-col divide-y divide-gray-100 px-4">
        {entries.map(({ stage, entry }) => (
          <section key={stage} className="py-3">
            <div className="mb-1.5 flex flex-wrap items-center gap-2">
              <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs font-semibold uppercase text-blue-700">
                {stage}
              </span>
              <span className="text-xs font-medium text-gray-700">Rank {entry.rank}</span>
              {entry.icdCode && (
                <span className="font-mono text-xs text-gray-500">{entry.icdCode}</span>
              )}
            </div>
            <p className="text-sm leading-5 text-gray-700">{entry.reason}</p>
            {entry.sharedWith && entry.sharedWith.length > 0 && (
              <p className="mt-2 text-xs leading-4 text-amber-700">
                This ICD prediction also maps to {entry.sharedWith.join(', ')}.
              </p>
            )}
          </section>
        ))}
      </div>
    </>
  )
}

function ModelRankCell({
  annotator,
  diagnosis,
  rankLabel,
  reasoning,
  modelName,
  visibleStages,
  formatRankLabel,
}: {
  annotator: Annotator
  diagnosis: Diagnosis
  rankLabel: string
  reasoning: ModelDiagnosisReasoning | undefined
  modelName: string | undefined
  visibleStages: Record<VerifierStage, boolean>
  formatRankLabel: (rankLabel: string) => string
}) {
  const hasVisibleReasoning = REASONING_STAGES.some(
    stage => visibleStages[stage] && reasoning?.[stage],
  )
  const label = formatRankLabel(rankLabel)

  if (!reasoning || !modelName || !hasVisibleReasoning) {
    return (
      <span className="text-sm font-medium tabular-nums text-gray-700 whitespace-nowrap">
        {label}
      </span>
    )
  }

  return (
    <HoverCard
      ariaLabel={`Model reasoning: ${annotator.name} ${diagnosis.label}`}
      wrapperClassName="h-full w-full"
      className="flex h-full w-full items-center justify-center rounded-sm text-sm font-medium tabular-nums text-gray-700 whitespace-nowrap decoration-dotted underline-offset-4 hover:underline focus:underline focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500"
      content={(
        <ModelReasoningContent
          annotator={annotator}
          diagnosis={diagnosis}
          modelName={modelName}
          reasoning={reasoning}
          visibleStages={visibleStages}
        />
      )}
    >
      {label}
    </HoverCard>
  )
}

export function DiagnosesPanel({
  diagnoses,
  myAnnotations,
  onToggle,
  customDiagnoses,
  onAddCustomDiagnosis,
  onRemoveCustomDiagnosis,
  canAnnotate,
  showHuman,
  showLLM,
  showAI,
  showSimilarityScores,
  showIcdRanks,
  showDiagnosisHelp,
  showModelReasoning,
  visibleStages,
  existingAnnotations,
  annotators,
  modelReasoning,
}: Props) {
  const [showRemainingDiagnoses, setShowRemainingDiagnoses] = useState(false)
  const [newOtherLabel, setNewOtherLabel] = useState('')

  const commitNewOtherDiagnosis = () => {
    const trimmed = newOtherLabel.trim()
    if (!trimmed) {
      return
    }
    onAddCustomDiagnosis(trimmed)
    setNewOtherLabel('')
  }

  const visibleAnnotators = annotators.filter(
    a =>
      (a.type === 'human' && showHuman) ||
      (a.type === 'llm' && showLLM) ||
      (a.type === 'ai' && showAI),
  )

  const getAnnotation = (annotatorId: string, diagnosisId: string) => {
    return (
      existingAnnotations.find(
        a => a.annotatorId === annotatorId && a.diagnosisId === diagnosisId,
      ) ?? null
    )
  }

  const formatRankLabel = (rankLabel: string) => {
    const parts = rankLabel.split('/').map(part => part.trim())
    return STAGES
      .map((stage, index) => (visibleStages[stage] ? parts[index] ?? '_' : null))
      .filter((part): part is string => part !== null)
      .join(' / ')
  }

  const gridTemplateColumns = [
    `${DX_NAME_COL_W}px`,
    ...(showSimilarityScores ? [`${DX_COSSIM_COL_W}px`] : []),
    ...(showIcdRanks ? [`${DX_ICD_RANK_COL_W}px`] : []),
    ...(canAnnotate ? [`${ME_COL_W}px`] : []),
    ...visibleAnnotators.map(() => `${ANNOTATOR_COL_W}px`),
  ].join(' ')

  const topDiagnoses = diagnoses.slice(0, COLLAPSE_AFTER)
  const remainingDiagnoses = diagnoses.slice(COLLAPSE_AFTER)
  const customDiagnosisRows: Diagnosis[] = customDiagnoses.map((custom, index) => ({
    id: custom.id,
    label: custom.label,
    rank: index + 1,
  }))
  const renderDiagnosisRow = (dx: Diagnosis, onRemove?: () => void) => {
    const annotationByAnnotator = new Map(
      visibleAnnotators.map(annotator => [annotator.id, getAnnotation(annotator.id, dx.id)]),
    )

    return (
    <Fragment key={dx.id}>
      <div
        key={`${dx.id}-diagnosis`}
        className={`${MIN_ROW_H} flex items-center px-3 gap-3 border-b border-gray-100 hover:bg-gray-50 transition-colors`}
      >
        <span className="text-xs text-gray-400 w-4 shrink-0">{dx.rank}</span>
        <DiagnosisLabel diagnosis={dx} showDiagnosisHelp={showDiagnosisHelp} />
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Remove ${dx.label}`}
            title="Remove this diagnosis"
            className="ml-auto flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-gray-300 hover:bg-red-50 hover:text-red-500"
          >
            ×
          </button>
        )}
      </div>
      {showSimilarityScores && (
        <div
          key={`${dx.id}-score`}
          className={`${MIN_ROW_H} flex items-center justify-end px-3 border-b border-l border-gray-100 hover:bg-gray-50 transition-colors`}
        >
          <span className="text-xs tabular-nums text-gray-500">
            {typeof dx.score === 'number' ? dx.score.toFixed(3) : ''}
          </span>
        </div>
      )}
      {showIcdRanks && (
        <div
          key={`${dx.id}-icd`}
          className={`${MIN_ROW_H} flex items-center justify-end px-3 border-b border-l border-gray-100 hover:bg-gray-50 transition-colors`}
        >
          <span className="text-xs tabular-nums text-gray-500">
            {typeof dx.icd_rank === 'number' ? dx.icd_rank : '_'}
          </span>
        </div>
      )}
      {canAnnotate && (
        <div
          key={`${dx.id}-me`}
          className={`${MIN_ROW_H} flex items-center justify-center px-3 border-b border-l border-gray-100 hover:bg-gray-50 transition-colors`}
        >
          <input
            type="checkbox"
            aria-label={`My annotation ${dx.label}`}
            checked={!!myAnnotations[dx.id]}
            onChange={() => onToggle(dx.id)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer shrink-0"
          />
        </div>
      )}
      {visibleAnnotators.map(annotator => (
        <div
          key={`${dx.id}-${annotator.id}`}
          className={`${MIN_ROW_H} flex items-center justify-center px-3 border-b border-l border-gray-100 hover:bg-gray-50 transition-colors`}
        >
          {annotationByAnnotator.get(annotator.id)?.rankLabel ? (
            <ModelRankCell
              annotator={annotator}
              diagnosis={dx}
              rankLabel={annotationByAnnotator.get(annotator.id)?.rankLabel ?? ''}
              reasoning={
                showModelReasoning
                  ? modelReasoning?.models[annotator.id]?.diagnoses[dx.id]
                  : undefined
              }
              modelName={
                showModelReasoning
                  ? modelReasoning?.models[annotator.id]?.modelName
                  : undefined
              }
              visibleStages={visibleStages}
              formatRankLabel={formatRankLabel}
            />
          ) : (
            <AnnotationIcon
              value={annotationByAnnotator.get(annotator.id)?.value ?? null}
              label={`${annotator.name} ${dx.label}`}
            />
          )}
        </div>
      ))}
    </Fragment>
    )
  }

  return (
    <div className="overflow-x-auto">
      <div className="grid transition-all duration-300" style={{ gridTemplateColumns }}>
        <div className={`${ROW_H} flex items-center px-3 border-b border-gray-200`}>
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Diagnoses
          </span>
        </div>
        {showSimilarityScores && (
          <div className={`${ROW_H} flex items-center justify-end px-3 border-b border-l border-gray-200`}>
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              diagnosis_cossim
            </span>
          </div>
        )}
        {showIcdRanks && (
          <div className={`${ROW_H} flex items-center justify-end px-3 border-b border-l border-gray-200`}>
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              icd_rank
            </span>
          </div>
        )}
        {canAnnotate && (
          <div className={`${ROW_H} flex items-center justify-center px-3 border-b border-l border-gray-200`}>
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              Me
            </span>
          </div>
        )}
        {visibleAnnotators.map(annotator => (
          <div
            key={annotator.id}
            className={`${ROW_H} flex items-center justify-center px-3 border-b border-l border-gray-200`}
          >
            <span className="text-xs font-semibold text-gray-500 whitespace-nowrap">
              {annotator.name}
            </span>
          </div>
        ))}

        {topDiagnoses.map(dx => renderDiagnosisRow(dx))}
        {remainingDiagnoses.length > 0 && (
          <div
            className="h-10 flex items-center justify-center px-3 border-b border-gray-100 bg-gray-50"
            style={{ gridColumn: '1 / -1' }}
          >
            <button
              type="button"
              onClick={() => setShowRemainingDiagnoses(value => !value)}
              className="text-xs font-medium text-blue-700 hover:text-blue-800"
            >
              {showRemainingDiagnoses
                ? `Hide ${remainingDiagnoses.length} diagnoses after top 10`
                : `Show ${remainingDiagnoses.length} more diagnoses`}
            </button>
          </div>
        )}
        {showRemainingDiagnoses && remainingDiagnoses.map(dx => renderDiagnosisRow(dx))}

        <div
          className="h-8 flex items-center px-3 border-b border-t border-gray-200 bg-gray-50"
          style={{ gridColumn: '1 / -1' }}
        >
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Other Disease
          </span>
        </div>

        {customDiagnosisRows.map(dx => renderDiagnosisRow(
          dx,
          canAnnotate ? () => onRemoveCustomDiagnosis(dx.id) : undefined,
        ))}

        {canAnnotate && (
          <>
            <div
              key="add-other-diagnosis-name"
              className={`${MIN_ROW_H} flex items-center px-3 gap-2 border-b border-gray-100`}
            >
              <input
                type="text"
                value={newOtherLabel}
                onChange={event => setNewOtherLabel(event.target.value)}
                onKeyDown={event => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    commitNewOtherDiagnosis()
                  }
                }}
                placeholder="Diagnosis not in the list above..."
                aria-label="Add a diagnosis not in the WikiDoc list"
                className="w-full min-w-0 rounded-sm border border-gray-200 px-2 py-1 text-sm text-gray-800 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <button
                type="button"
                onClick={commitNewOtherDiagnosis}
                disabled={!newOtherLabel.trim()}
                aria-label="Add other disease"
                title="Add other disease"
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-gray-300 text-sm font-semibold text-gray-500 hover:border-blue-500 hover:text-blue-600 disabled:cursor-not-allowed disabled:opacity-40"
              >
                +
              </button>
            </div>
            {showSimilarityScores && (
              <div
                key="add-other-diagnosis-score"
                className={`${MIN_ROW_H} border-b border-l border-gray-100`}
              />
            )}
            {showIcdRanks && (
              <div
                key="add-other-diagnosis-icd"
                className={`${MIN_ROW_H} border-b border-l border-gray-100`}
              />
            )}
            <div
              key="add-other-diagnosis-me"
              className={`${MIN_ROW_H} border-b border-l border-gray-100`}
            />
            {visibleAnnotators.map(annotator => (
              <div
                key={`add-other-diagnosis-${annotator.id}`}
                className={`${MIN_ROW_H} border-b border-l border-gray-100`}
              />
            ))}
          </>
        )}
      </div>
    </div>
  )
}
