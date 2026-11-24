import type { AnnotationValue } from '../types'

interface Props {
  value: AnnotationValue
  label?: string
}

export function AnnotationIcon({ value, label }: Props) {
  if (value === 'yes') {
    return (
      <span
        aria-label={label ? `${label}: annotated` : 'Annotated'}
        className="flex items-center justify-center w-6 h-6 rounded border-2 border-gray-400 text-gray-700"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
        </svg>
      </span>
    )
  }
  return (
    <span
      aria-label={label ? `${label}: not annotated` : 'Not annotated'}
      className="flex items-center justify-center w-6 h-6 rounded border-2 border-gray-200"
    />
  )
}
