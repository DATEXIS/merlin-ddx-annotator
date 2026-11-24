import { useEffect, useState } from 'react'

interface Props {
  current: number
  total: number
  name: string
  onPrev: () => void
  onNext: () => void
  onJump?: (index: number) => void
}

export function PatientNav({ current, total, name, onPrev, onNext, onJump }: Props) {
  // Local draft of the case number so a clinician can type a target (e.g. 350)
  // and jump straight there instead of stepping with the arrows. Kept in sync
  // with the actual position; committed on Enter or blur, clamped to range.
  const [draft, setDraft] = useState(String(current + 1))
  useEffect(() => {
    setDraft(String(current + 1))
  }, [current])

  const commitJump = () => {
    const parsed = Number.parseInt(draft, 10)
    if (Number.isNaN(parsed) || !onJump) {
      setDraft(String(current + 1))
      return
    }
    const clamped = Math.max(1, Math.min(parsed, total))
    setDraft(String(clamped))
    if (clamped - 1 !== current) {
      onJump(clamped - 1)
    }
  }

  return (
    <div className="flex items-center gap-4">
      <button
        onClick={onPrev}
        disabled={current === 0}
        className="p-2 rounded-full hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        aria-label="Previous patient"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
      </button>

      <span className="text-base font-semibold text-gray-800 min-w-[220px] text-center">
        {name}
      </span>
      <span className="text-sm text-gray-400 flex items-center gap-1" aria-label="Patient position">
        <input
          type="number"
          min={1}
          max={total}
          value={draft}
          onChange={event => setDraft(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') {
              event.currentTarget.blur()   // triggers onBlur -> commitJump
            }
          }}
          onBlur={commitJump}
          disabled={!onJump}
          aria-label="Jump to case number"
          title="Type a case number and press Enter to jump"
          className="w-14 text-center text-sm text-gray-700 border border-gray-300 rounded px-1 py-0.5 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:border-transparent disabled:bg-transparent"
        />
        <span>/ {total}</span>
      </span>

      <button
        onClick={onNext}
        disabled={current === total - 1}
        className="p-2 rounded-full hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        aria-label="Next patient"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </button>
    </div>
  )
}
