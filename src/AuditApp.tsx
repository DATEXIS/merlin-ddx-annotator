import { useCallback, useEffect, useState } from 'react'
import { RebuttalAudit } from './components/RebuttalAudit'
import type { Annotator } from './types'

// Audit-only shell, used when the data root holds no DDx annotation cohort (for example
// the credentialed audit inputs). With DDx cohorts present, src/main.tsx renders the
// study's own application (src/App.tsx), whose "reasoning audit" view shows the same
// <RebuttalAudit> screen. The screen and its backend are unchanged; the selected
// annotator is remembered under the same browser-storage key as in the study.
const SELECTED_ANNOTATOR_KEY = 'ddx-selected-annotator'

function readSelected(): string {
  try { return localStorage.getItem(SELECTED_ANNOTATOR_KEY) ?? '' } catch { return '' }
}

export function AuditApp() {
  const [annotators, setAnnotators] = useState<Annotator[]>([])
  const [annotatorId, setAnnotatorId] = useState(readSelected)
  const [error, setError] = useState('')
  const [showViewNotice, setShowViewNotice] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/annotators', { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(`Annotator list unavailable (${response.status})`)
        return response.json() as Promise<Annotator[]>
      })
      .then(items => { setAnnotators(items); setAnnotatorId(previous => items.some(a => a.id === previous) ? previous : items.length === 1 ? items[0].id : '') })
      .catch(cause => { if (!controller.signal.aborted) setError(String(cause)) })
    return () => controller.abort()
  }, [])

  const changeAnnotator = useCallback((id: string) => {
    setAnnotatorId(id)
    try {
      if (id) localStorage.setItem(SELECTED_ANNOTATOR_KEY, id)
      else localStorage.removeItem(SELECTED_ANNOTATOR_KEY)
    } catch { /* selection still works for this session */ }
  }, [])

  return <>
    {error && <p role="alert" className="bg-red-50 px-5 py-2 text-sm text-red-700">{error}</p>}
    <RebuttalAudit annotators={annotators} annotatorId={annotatorId} onAnnotatorChange={changeAnnotator}
      onViewChange={() => setShowViewNotice(true)} />
    {showViewNotice && <div role="status"
      className="fixed bottom-4 right-4 z-50 max-w-sm rounded-lg border border-gray-200 bg-white px-4 py-3 text-sm text-gray-700 shadow-lg">
      The DDx annotation views (train, test, test (350)) need the DDx cohort files, which this data root does not contain.
      <button type="button" onClick={() => setShowViewNotice(false)} className="ml-2 font-medium text-blue-700">Dismiss</button>
    </div>}
  </>
}
