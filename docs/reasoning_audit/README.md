# Reasoning audit (42 admissions)

Two clinicians rated diagnosis-stage (V2) and ICD-coding-stage (V4) rationales of 42 admissions. Each pair showed a MERLIN-DDx generator–verifier loop rationale next to a zero-shot rationale. The clinicians were blinded to condition, verifier score and loop outcome (paper, Appendix B; serving artifacts documented in the protocol). Study co-author Dennis Fast additionally confirmed on 2026-11-27 that all annotation studies, including this audit, were conducted blinded. This audit was released in v1.0.0. Its interface, analysis, documents and results are unchanged in v1.1.0. Since v1.2.0, the audit screen and backend also serve new study formats; the historical audit inputs are rendered and validated as before, and its analysis, documents and results are unchanged.

The audit's documents stay at their v1.0 locations so that existing links keep working:

| Document | Content |
|---|---|
| [Protocol](../protocol.md) | What was fixed before rating and what was documented afterwards; discrepancies with the paper |
| [Rubric](../rubric.md) and [config/rubric.json](../../config/rubric.json) | Exact question wording and answer options |
| [Walkthrough](../annotation_walkthrough.md) | The audit screen step by step, with screenshots on synthetic cases |
| [Results](../../results/README.md) | Cohort-level results, agreement statistics, contingency matrices |
| [Reproducibility](../reproducibility.md) | What can be reproduced from which data |
| [Data access](../data_access.md) | Public, credentialed and internal material |
| [Workflow figure](../assets/evaluation_workflow.svg) | Blinding, rating and unblinding |

In the interface, the audit is the *reasoning audit* view of the study application.

- **v1.0:** a separate shell opened it directly.
- **Since v1.1.0:** the application opens on the DDx annotation views, as it did in the study. Choose *reasoning audit* in the view selector to open the audit.
- **No DDx cohort:** when the data root holds no DDx cohort, as with the credentialed audit inputs, the v1.0 audit-only shell opens instead.
