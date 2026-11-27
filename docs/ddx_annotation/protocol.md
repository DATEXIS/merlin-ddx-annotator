# DDx annotation protocol (pilot and 350-case study)

This page states what is known about how the clinician DDx annotation was carried out. Each element is marked with its source:

- **[code]**: the interface and analysis code in this repository, verified;
- **[records]**: the stored annotation records, verified;
- **[investigators]**: confirmed by the study investigators on 2026-11-24, with actual blinding of the 350-case study additionally confirmed by co-author Dennis Fast on 2026-11-27; no contemporaneous written instruction document was recovered;
- **[manuscript]**: stated in the MERLIN-DDx paper only.

## 1. Task

Clinician co-authors confirmed the clinically correct diagnosis of an admission, given its chief complaint and the fixed WikiDoc candidate list of that complaint [manuscript]. In the interface, the clinician checks one or more candidates. A diagnosis that is missing from the list is added in the *Other Disease* row and checked there [code]. There is no explicit "no", confidence rating or comment field [code].

The paper attributes two marking rules to the reviewers: "mark every documented diagnosis that fits" for the first two reviewers, and "only the single most likely diagnosis" for the third [manuscript]. No written instruction stating either rule was recovered. The paper infers the third reviewer's rule from the data.

## 2. Cohorts

**Pilot.** 70 admissions, 10 for each of seven chief complaints (abdominal pain, back pain, chest pain, cough, diarrhea, dyspnea, headache). 35 come from the training split and 35 from the test split [records]. The procedure that selected them was not recovered.

**350-case study.** 350 admissions, 50 per chief complaint, all from the test split [records]. They were drawn by [`scripts/sample_blind_annotation.py`](../../scripts/sample_blind_annotation.py) [code]:

- **Frame.** The test split of the case pool, minus the 70 pilot admissions.
- **Stratification.** By chief complaint and cosine-top disease.
- **Allocation.** At least one case per disease, then a round-robin equal fill. The sample is disease-balanced rather than prevalence-representative. A per-case prevalence weight is recorded but not used in the analysis.
- **Seed.** 20260711.

The file names of this script ("blind annotation sample") are historical and do not show how the cases were annotated (see section 4).

The pilot and the study share no admission. The superseded verification view drew its 70 cases from the 350 ([docs/verification/](../verification/README.md)).

## 3. Candidate list and automated references

- **Candidate list.** Every case shows all WikiDoc diseases of its chief complaint (19 to 74), ranked by cosine similarity to the discharge-diagnosis text. Candidate *dN* is the *N*-th in that order. The interface shows the first ten and expands the rest on request [code].
- **Cosine reference.** The first candidate [code].
- **ICD reference.** The candidate whose WikiDoc ICD-10 pattern matches the earliest coder-assigned ICD code of the admission [code].

The clinician task did not ask clinicians to choose between the two references. The references are compared with the clinicians' selections afterwards.

## 4. Information available to the clinicians

Three things are kept apart here: the investigator-confirmed study conduct, what the interface did, and what can be independently checked afterwards.

### 4.1 Instructions [investigators]

Clinicians were instructed to hide:

- the MERLIN model predictions;
- the other clinicians' annotations.

**350-case study:** On 2026-11-27, study co-author Dennis Fast confirmed that clinicians actually conducted the annotation blinded to MERLIN model predictions and the other clinicians' annotations, not merely that they were instructed to do so [investigators]. This is retrospective investigator confirmation, not evidence from interaction logs or technically enforced masking. It does not establish the information regime of the earlier pilot.

The full discharge summary, including the discharge diagnosis and the coder-assigned ICD codes, was available **by design**. The task is retrospective reference annotation: it confirms the diagnosis the admission was mapped to, so it is not an admission-time diagnostic task.

No written instruction document for the pilot or the 350-case study was recovered.

### 4.2 Interface behaviour [code]

| Element | Shown | Default when the page loads |
|---|---|---|
| Discharge summary, all sections except Attending, Facility and Followup Instructions; admission-time sections highlighted | yes, each section collapsible | collapsed |
| Labs, discharge diagnosis, coder ICD codes with descriptions | separate collapsible panels | collapsed |
| MERLIN model ranks (Llama-3.3-70B, Qwen3-32B, MedGemma-27B; V1 / V2 / V3 / V4) with V2–V4 reasoning on hover | switch *MERLIN predictions* | **on** |
| Other clinicians' marks | switch *Human annotators* | **on** |
| Frontier-model marks (data for the pilot only) | switch *AI annotators* | off |
| Cosine score and ICD rank of each candidate | checkboxes | off |
| WikiDoc diagnosis help on hover | checkbox | on |
| Pop-up when another clinician saves a change during the session (names the clinician and the diagnosis) | always, whatever the switches | — |

- **Switch state.** The interface does not remember the switch settings: every page load starts from the defaults above.
- **Not enforced.** Hiding model predictions and other clinicians' marks was the clinician's action. The interface did not enforce it.
- **Evaluation mode.** With no annotator selected, the interface shows everything and records nothing.

### 4.3 What the records can and cannot show [records]

- **What is stored.** The annotation store holds each clinician's current selections per case and the time of the last save. It holds no interaction log: switch settings, opened panels and viewing order are not recorded.
- **Blinding confirmed by investigator, not independently logged.** The conduct of the 350-case study was confirmed on 2026-11-27 (section 4.1). The stored records alone cannot independently establish switch settings, viewing order, or whether information was inadvertently exposed.
- **Order of saves.** Clinician 1's last save of a case precedes Clinician 2's in 230 of their 236 shared cases, and precedes Clinician 3's in all 121 of theirs. So in most shared cases another clinician's marks already existed when the later clinician annotated, and the default view would have shown them had the clinicians not hidden them. This is evidence about the interface default, not evidence that the marks were actually viewed.

### 4.4 Pilot: a different account in the analysis code

The study's pilot report generator describes a different regime for the pilot. It is not published here because it hard-codes interpretive text about the pilot results; see [CHANGES_FROM_STUDY.md](../../CHANGES_FROM_STUDY.md).

- **Train split:** annotated with the discharge diagnoses, ICD codes and model predictions visible.
- **Test split:** annotated "blinded" to them.

This account differs from section 4.1 for the train split and for the discharge information. No other document resolves the difference. The analysis therefore keeps the two pilot splits apart, as the original code does, and the published code no longer labels either split "blinded".

### 4.5 Interface version

The repository history starts on 16 July 2026, during the pilot, so the interface of the first pilot days was not recovered.

From that date on, the DDx view differs from the released one only by two things:

- the position field for jumping to a case, added on 10 September;
- code paths for the later audit and verification views.

Display defaults and storage are unchanged.

The application code released in v1.1.0 (`src/App.tsx` and its components) is the version of 17 September 2026. Since v1.2.0, `src/App.tsx` and the audit screen are extended for new studies; the DDx views of the historical cohorts are unaffected. Those archived sources rebuild byte for byte the bundle that was served during the reasoning audit ([CHANGES_FROM_STUDY.md](../../CHANGES_FROM_STUDY.md)). Which build was deployed during the DDx annotation was not recorded.

## 5. Recorded data [code, records]

- **Annotation record.** One JSON record per clinician and case:

  ```json
  {"annotatorId": "...", "patientId": "<case>", "updatedAt": "<UTC>", "annotations": {"d3": true, "o1": true}}
  ```

  `true` means checked. `false` only means a box was checked and then unchecked again: there is no explicit negative.
- **Added diagnoses.** These are stored per case (`o1`, `o2`, …) with their label, creator and time. They are shared, so every clinician of that case can check an added diagnosis.
- **Saving.** Records are saved with the *Save* button, on leaving a case, and automatically every 30 seconds after a change.

## 6. Aggregation

There was no consensus or adjudication step. Every clinician's records are analysed separately and compared pairwise. The scoring rules are in [analysis.md](analysis.md).

## 7. Not recovered or not included

| Item | Status |
|---|---|
| Written annotation instructions (pilot, 350-case study) | Not recovered; the instructions and actual blinding of the 350-case study are investigator-confirmed (section 4.1) |
| Interaction logs (switch settings, panels opened) | Never recorded |
| Selection procedure of the 70 pilot cases | Not recovered |
| Case pool used by the original pilot analysis | Not recovered. The available pool contains 62 of the 70 pilot cases, so pilot reference-agreement results cover the analysable cases (see results) |
| Earlier agreement analysis used for the submitted manuscript | Not recovered. Published values come from the code in this repository on the final records |
| Data preparation (candidate lists, model runs, frontier-model runners) | Not included |
