import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AuditApp } from './AuditApp'

// The study's entry point rendered <App /> (src/App.tsx, unchanged here). App opens on the
// DDx annotation views and cannot reach its "reasoning audit" view without DDx cases, so a
// data root holding only the reasoning-audit inputs falls back to the audit-only shell.
async function hasDdxCases(): Promise<boolean> {
  try {
    const response = await fetch('/api/patients')
    if (!response.ok) return false
    const patients: unknown = await response.json()
    return Array.isArray(patients) && patients.length > 0
  } catch {
    return false
  }
}

void hasDdxCases().then(ddx => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      {ddx ? <App /> : <AuditApp />}
    </StrictMode>,
  )
})
