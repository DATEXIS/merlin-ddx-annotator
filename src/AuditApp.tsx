import { useCallback, useEffect, useState } from 'react'
import { RebuttalAudit } from './components/RebuttalAudit'
import type { Annotator } from './types'

// Public shell for the MERLIN-DDx clinician-audit interface.
//
// During the study, clinicians opened the general annotator application and switched
// to its "reasoning audit" view, which renders <RebuttalAudit>. That component, the
// annotator selector it contains and the backend it talks to are unchanged here; only
// this thin shell replaces the general application, whose other views (train, test,
// test (350)) served a different annotation study and are not part of this release.
// The selected annotator is remembered under the same browser-storage key as before.
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
      .then(setAnnotators)
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
      The train, test and test (350) views belonged to a separate annotation study and are not part of this release.
      <button type="button" onClick={() => setShowViewNotice(false)} className="ml-2 font-medium text-blue-700">Dismiss</button>
    </div>}
  </>
}
