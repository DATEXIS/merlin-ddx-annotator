# Verification view (superseded design, no data)

The study code contains a third annotation design, the *verification (70)* view. It was meant to ask a clinician two questions about Qwen3-32B rationales for 70 cases drawn from the 350-case study:

- is the rationale grounded in the admission information?
- does it clinically support its diagnosis or ICD code?

It was set up on 16–17 September 2026 and then superseded by the 42-admission reasoning audit ([docs/reasoning_audit/](../reasoning_audit/README.md)).

**It collected no judgments.** The records created for it contain no answered question. It is not a study and has no results.

What this release contains of it:

- **Frontend.** The study's application code still includes the view (`src/components/VerificationPanel.tsx`, `src/hooks/useVerificationAnnotations.ts`). The view is hidden from the view selector, as it was in the study. These files ship only because the unchanged application imports them.
- **Backend.** The backend endpoints (`/api/verification70…`) are part of the unchanged `merlin_ddx/sync_api.py`.
- **Data.** No verification cases, inputs or records are included. Without a `verification70.json` file the endpoints answer "missing data file".

The case list and the script that built it are not released, because the design was not used.
