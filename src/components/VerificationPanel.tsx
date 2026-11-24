import type {
  VerificationAnswers,
  VerificationCase,
  VerificationItemId,
  VerificationJudgment,
  VerificationQuestion,
} from '../types'
import { Toggle } from './Toggle'

const QUESTIONS: { id: VerificationQuestion; label: string; help: string }[] = [
  {
    id: 'grounding',
    label: 'Are the clinical facts stated in the rationale supported by the admission information?',
    help: 'Assess only information available at admission.',
  },
  {
    id: 'clinicalSupport',
    label: 'Do those facts clinically support the stated ICD diagnosis?',
    help: 'Judge the reasoning, not whether the diagnosis was coded at discharge.',
  },
]

const CHOICES: { value: VerificationJudgment; label: string }[] = [
  { value: 'yes', label: 'Yes' },
  { value: 'no', label: 'No' },
  { value: 'unclear', label: 'Unclear' },
]

function JudgmentQuestions({ caseData, itemId, answers, onAnswer, canAnnotate }: {
  caseData: VerificationCase
  itemId: VerificationItemId
  answers: VerificationAnswers
  onAnswer: (itemId: VerificationItemId, question: VerificationQuestion,
    value: VerificationJudgment) => void
  canAnnotate: boolean
}) {
  return (
    <div className="border-t border-gray-100 px-4 py-4 flex flex-col gap-5">
      {QUESTIONS.map(question => (
        <fieldset key={question.id}>
          <legend className="text-sm font-medium text-gray-900">
            {itemId === 'v2' && question.id === 'clinicalSupport'
              ? 'Do those facts clinically support the stated diagnosis?'
              : question.label}
          </legend>
          <p className="mt-1 text-xs text-gray-500">{question.help}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {CHOICES.map(choice => {
              const selected = answers[itemId]?.[question.id] === choice.value
              return (
                <label key={choice.value} className={`cursor-pointer rounded-md border px-3 py-1.5 text-sm transition-colors ${
                  selected ? 'border-blue-600 bg-blue-50 text-blue-800' : 'border-gray-200 text-gray-700 hover:bg-gray-50'
                } ${!canAnnotate ? 'cursor-not-allowed opacity-60' : ''}`}>
                  <input
                    type="radio"
                    name={`${caseData.patientId}-${itemId}-${question.id}`}
                    value={choice.value}
                    checked={selected}
                    disabled={!canAnnotate}
                    onChange={() => onAnswer(itemId, question.id, choice.value)}
                    className="mr-2 accent-blue-600"
                  />
                  {choice.label}
                </label>
              )
            })}
          </div>
        </fieldset>
      ))}
    </div>
  )
}

export function VerificationPanel({ caseData, answers, onAnswer, canAnnotate,
  showV2, showV4, onToggleV2, onToggleV4 }: {
  caseData: VerificationCase
  answers: VerificationAnswers
  onAnswer: (itemId: VerificationItemId, question: VerificationQuestion,
    value: VerificationJudgment) => void
  canAnnotate: boolean
  showV2: boolean
  showV4: boolean
  onToggleV2: (value: boolean) => void
  onToggleV4: (value: boolean) => void
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-blue-900">Rationale verification</h2>
          <div className="flex items-center gap-4">
            <Toggle label="V2" checked={showV2} onChange={onToggleV2} />
            <Toggle label="V4" checked={showV4} onChange={onToggleV4} />
          </div>
        </div>
        <p className="mt-1 text-sm text-blue-800">
          Read the admission information on the left. For each visible rationale, answer both questions.
        </p>
        {!canAnnotate && <p className="mt-2 text-sm font-medium text-amber-800">Select an annotator to record answers.</p>}
      </div>

      {showV2 && <section aria-label="V2 main diagnosis"
        className="rounded-lg border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-100 px-4 py-3 flex flex-wrap items-center gap-3">
          <span className="rounded bg-blue-800 px-2 py-0.5 text-xs font-semibold text-white">Qwen V2</span>
          <h3 className="text-sm font-semibold text-gray-900">{caseData.mainDiagnosis.diseaseName}</h3>
        </div>
        <p className="whitespace-pre-wrap px-4 py-4 text-sm leading-6 text-gray-800">
          {caseData.mainDiagnosis.v2Reasoning
            ?? 'Qwen did not provide V2 reasoning for this verified main diagnosis.'}
        </p>
        {caseData.mainDiagnosis.v2Reasoning && <JudgmentQuestions
          caseData={caseData} itemId="v2" answers={answers}
          onAnswer={onAnswer} canAnnotate={canAnnotate}
        />}
      </section>}

      {showV4 && caseData.items.map(item => (
        <section key={item.id} aria-label={`Rationale ${item.id.toUpperCase()}`}
          className="rounded-lg border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-100 px-4 py-3 flex flex-wrap items-center gap-3">
            <span className="rounded bg-gray-900 px-2 py-0.5 text-xs font-semibold text-white">
              Rationale {item.id.toUpperCase()}
            </span>
            <div className="min-w-0">
              <span className="font-mono text-sm font-semibold text-gray-900">{item.icdCode}</span>
              <p className="mt-0.5 text-sm text-gray-600">
                {item.icdDescriptionCode
                  ? `Closest catalog category ${item.icdDescriptionCode}: ${item.icdDescription}`
                  : item.icdDescription}
              </p>
            </div>
          </div>
          <p className="whitespace-pre-wrap px-4 py-4 text-sm leading-6 text-gray-800">{item.rationale}</p>
          <JudgmentQuestions caseData={caseData} itemId={item.id} answers={answers}
            onAnswer={onAnswer} canAnnotate={canAnnotate} />
        </section>
      ))}
    </div>
  )
}
