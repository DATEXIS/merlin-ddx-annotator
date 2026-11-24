import type { NoteSection } from '../types'

interface Props {
  sections: NoteSection[]
  admissionOnly?: boolean
}

const HIDDEN_SECTIONS = new Set([
  'Attending',
  'Facility',
  'Followup Instructions',
])

const ADMISSION_TIME_SECTIONS = new Set([
  'Allergies',
  'Chief Complaint',
  'History of Present Illness',
  'Past Medical History',
  'Social History',
  'Family History',
  'Physical Exam',
  'Medications on Admission',
])

function displaySections(sections: NoteSection[]) {
  const next = sections.filter(section => !HIDDEN_SECTIONS.has(section.title))
  const medicationsIndex = next.findIndex(section => section.title === 'Medications on Admission')
  const pertinentResultsIndex = next.findIndex(section => section.title === 'Pertinent Results')

  if (medicationsIndex !== -1 && pertinentResultsIndex !== -1 && medicationsIndex > pertinentResultsIndex) {
    const [medications] = next.splice(medicationsIndex, 1)
    next.splice(pertinentResultsIndex, 0, medications)
  }

  return next
}

export function DischargeNote({ sections, admissionOnly = false }: Props) {
  const visibleSections = displaySections(sections).filter(
    section => !admissionOnly || ADMISSION_TIME_SECTIONS.has(section.title),
  )

  return (
    <div className="flex flex-col gap-1">
      <div className="mb-2 flex items-center gap-2 px-1 text-xs text-gray-600">
        <span className="h-3 w-3 rounded-sm border border-green-200 bg-green-50" aria-hidden="true" />
        <span>Sections known at admission time</span>
      </div>

      {visibleSections.map((section, i) => {
        const isAdmissionTime = ADMISSION_TIME_SECTIONS.has(section.title)
        return (
          <details key={`${section.title}-${i}`} open={admissionOnly} className="group rounded-lg border border-gray-200 bg-white overflow-hidden">
            <summary className={`flex items-center gap-2 px-4 py-3 cursor-pointer list-none select-none transition-colors ${
              isAdmissionTime ? 'bg-green-50 hover:bg-green-100' : 'hover:bg-gray-50'
            }`}>
              <svg
                className={`w-4 h-4 transition-transform duration-200 group-open:rotate-90 shrink-0 ${
                  isAdmissionTime ? 'text-green-600' : 'text-gray-400'
                }`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
              <span className={`text-sm font-medium ${isAdmissionTime ? 'text-green-900' : 'text-gray-700'}`}>
                {section.title}
              </span>
            </summary>
            <div className="px-4 pb-4 pt-2 text-sm text-gray-600 whitespace-pre-line border-t border-gray-100">
              {section.content}
            </div>
          </details>
        )
      })}
    </div>
  )
}
