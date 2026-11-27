# MERLIN-DDx clinician audit of generated rationales: protocol

Study: `merlin-ddx-clinician-audit-batch1` · release 1.0.0-rc1 · status: **incomplete**

This protocol was reconstructed from the original audit artifacts: the blinded pair file served to clinicians, the hidden allocation key, the deployed clinician interface and server validation, the raw rating exports, and the original analysis code and outputs. An internal pre-rating protocol (self-dated 16 September 2026) also survives, but it specifies a different design from the one executed (section 9). Each element below is therefore tagged with its evidence:

- **[pre-rating]**: documented in an artifact that demonstrably existed before the first rating was saved;
- **[protocol]**: stated in the internal pre-rating protocol (no independent timestamp);
- **[observed]**: established from the evaluation data themselves;
- **[analysis]**: introduced or finalized when the ratings were analyzed;
- **[manuscript]**: stated in the manuscript only;
- **[not documented]**: no surviving evidence.

## 1. Objective

To judge, independently of the pipeline's verifiers, whether rationales produced inside the MERLIN-DDx generator-verifier loop are better than zero-shot rationales from the same generator for the same admission and stage [manuscript]. Clinicians assessed, for every rationale, whether its stated facts are supported by the patient information and whether they clinically support the stated target, and, for every pair, which target is more appropriate and which rationale is clinically better [pre-rating].

## 2. Sample and unit of evaluation

- 42 admissions, 7 chief complaints with 6 admissions each [observed].
- Two pipeline stages per admission [observed]: V2, the diagnosis (differential-diagnosis) stage, and V4, the coding (ICD prediction) stage. The symptom stage was not audited.
- One pair per admission and stage: 84 pairs and 168 rationales (84 V2, 84 V4) [observed].
- Loop outcome of the in-loop rationale: V2 31 accepted / 11 rejected; V4 22 accepted / 20 rejected [observed]. The admissions were selected rather than drawn at random from all pipeline outputs, so rates do not estimate prevalence.
- Identical displayed targets in both arms: V2 29 of 42 pairs, V4 14 of 42 pairs [observed].
- Source split of all audited admissions in the pipeline data: `test` [observed]. The manuscript describes them as dev admissions; see section 9.
- Sampling frame, inclusion and exclusion rules, and the random procedure used to draw these 42 admissions [not documented]: the code that built the pair files was not recovered. The pre-rating protocol describes a different frame (60 dev admissions per stage, 30 per loop outcome, traces of at least 40 words) [protocol] that the executed batch does not follow. Only the resulting balance (six admissions per complaint, loop outcomes as above) is known; the review response called the sample 'enriched' without stating the rule.

## 3. Compared conditions

- **loop**: the stage rationale from the generator-verifier construction trace of Qwen3-32B. All 84 of 84 in-loop rationales occur verbatim in the stored Qwen3-32B pipeline outputs for the same admission and stage, and their verifier scores match the stored scores (84/84) [observed].
- **zero_shot**: a rationale for the same admission and stage from the same generator (Qwen3-32B) and prompts without the verifier loop, taken from a base evaluation run that drew 4 candidates and kept the first valid JSON [protocol]. The outputs of that run were not recovered: 0 of 84 zero-shot texts can be traced to stored generator outputs, so model version, prompt and settings cannot be verified for this arm [not documented]. The loop draws up to 30 candidates per round for up to 4 rounds and keeps the best-scoring one, so the contrast is loop (budget plus selection) against single-pass generation [protocol].

## 4. Blinding and randomization

Study co-author Dennis Fast confirmed on 2026-11-27 that all MERLIN-DDx annotation studies, including this rationale audit, were conducted blinded [investigator confirmation]. For this audit, blinding concerns condition, verifier score and loop outcome, as independently supported by the serving artifacts below.

- Clinicians saw each pair as "Response A" and "Response B"; arm identity, verifier score and loop outcome were held in a separate allocation key that was never deployed to the serving storage [pre-rating; verified on the serving volume].
- A/B position of the in-loop rationale: V2 24 A / 18 B; V4 25 A / 17 B [observed]. The randomization procedure and seed [not documented].
- Answers were stored separately per annotator, and the interface displayed only the answers of the annotator selected in it [pre-rating]. Access was not technically restricted per clinician: the annotator selector listed all clinicians behind one shared login [pre-rating].

## 5. Clinician instructions and review procedure

The clinician-facing questions, answer options and enabling rules are reproduced verbatim in [rubric.md](rubric.md) / [`config/rubric.json`](../config/rubric.json) [pre-rating]. Per admission, the admission note was shown next to the V2 pair and the V4 pair. For each response, the clinician answered Q1 and Q2 (Yes/No/Unclear). After all four judgments of a pair, the clinician chose the more appropriate target (only when the two targets differed) and the clinically better rationale; an optional comment could be added. Answers were saved automatically per admission. No written instructions beyond the on-screen wording were recovered [not documented].

Two clinicians rated all 84 pairs; each completed every pair under their own annotator ID [observed]. All records were saved on 2026-09-17 (UTC) [observed].

## 6. Missing data

- Missing required responses: 0 of 922 expected [observed].
- Target preference not applicable (identical targets): 86 rater-pair cells [observed].
- Unclear answers are retained as a category; the primary composite counts them as not valid; a sensitivity analysis excluded a rater's paired judgment when either arm had an Unclear Q1 or Q2 [analysis].
- The original analysis refuses to run unless every required response is present [analysis].

## 7. Aggregation and statistical methods

- Composite validity: a rationale is valid only if Q1 = Yes and Q2 = Yes [pre-rating definition in an earlier protocol draft for a different design; implemented at analysis].
- Rates pool both clinicians' judgments (denominator = 2 x rationales per stage and arm). The primary contrast is loop minus zero-shot validity, in percentage points, within admission [analysis].
- 95% intervals: admission-cluster percentile bootstrap, 10,000 replicates, seed 20260917; both arms and both clinicians of an admission are resampled together. For per-clinician accepted-versus-rejected contrasts the same resampling keeps V2 and V4 of an admission together [analysis].
- Accepted versus rejected: in-loop rationales only, per clinician and stage, accepted minus rejected validity (between admissions) [analysis].
- Verifier score: Spearman correlation between the continuous loop verifier score and the binary Q2 = Yes (and composite) judgment, per clinician and stage; exploratory [analysis].
- Inter-rater agreement: raw agreement and unweighted Cohen's kappa on the original categories, per stage; see [results/agreement_statistics.md](../results/agreement_statistics.md) [pre-rating plan in an earlier draft; implemented at analysis].
- Preferences: shares of loop-preferred, zero-shot-preferred and equal/equivalent judgments; exact sign tests on non-tied judgments are descriptive only [analysis].

## 8. Timeline of procedures

| Element | Evidence | Relative to rating |
|---|---|---|
| Pair files (blinded + key) built | file timestamps 2026-09-16T15:04:53Z | before |
| Interface wording and server rules | source last modified 2026-09-17T05:11:31Z; serving pod created 2026-09-17T05:12:58Z with a bundle containing every rubric string | before |
| First and last saved ratings | 2026-09-17T06:23:40Z to 2026-09-17T11:06:27Z | — |
| Single-clinician unblinded preliminary analysis | report written 2026-09-17T10:52:01Z; the other clinician's last saved record 2026-09-17T11:06:27Z | before the other clinician's last two saves |
| Final analysis code and run | code last modified 2026-09-17T13:00:26Z; report 2026-09-17T13:00:34Z | after |

The rating interface, questions and answer options were fixed before rating. The analysis implementation was finalized after all ratings were saved; the primary tables are identical across all three final analysis runs, which differ only in secondary discharge-reference analyses not reported in the paper. A preliminary analysis of one clinician's completed ratings that joined the allocation key was written about 14 minutes before the other clinician's last two saved records; the artifacts cannot show whether those saves were edits, and there is no evidence that the second clinician had access to it.

## 9. Deviations, discrepancies and open items

Deviations of the executed audit from the internal pre-rating protocol:

| Element | Pre-rating protocol | Executed |
|---|---|---|
| Sampling frame | 917 dev admissions | 42 held-out test admissions |
| Sample | 30 admissions per loop outcome, V2 and V4 drawn separately (60 per stage) | 6 per chief complaint, V2 and V4 from the same admission; 31/11 and 22/20 accepted/rejected |
| Instrument | three 1-5 items: evidence support, conclusion support, clinical soundness | Q1 and Q2 (Yes/No/Unclear) per rationale; target and rationale preference per pair |
| Raters | two raters on the full sample, a third on a 40-trace overlap | two raters on every pair |
| Primary analysis | paired test of the mean item score, accepted vs zero-shot; difference-in-differences | loop minus zero-shot composite validity with admission-cluster bootstrap |
| Agreement | kappa / ICC on the overlap, reported first | raw agreement and Cohen's kappa per stage |

Open items:

- `pair_builder` (missing evidence): The code that sampled the 42 admissions and built the blinded/keyed pair files (2026-09-16 15:04 UTC) was not found. The pre-rating protocol names a seeded sampling script for its own, different frame (60 dev admissions per stage); that script was not found either (local projects, knowledge base, default branches of the DATEXIS pipeline repositories), and the executed batch does not follow its frame.
- `zero_shot_generation` (missing evidence): The pre-rating protocol defines the zero-shot condition as the same generator (Qwen3-32B) and prompts without the loop, taken from a base evaluation run (4 candidates, first valid JSON). The outputs of that run were not found; none of the 84 zero-shot texts occurs in the stored loop-construction outputs of any model. The served texts, word counts and a recorded zero-shot verifier score exist.
- `protocol_deviation` (missing evidence): A pre-rating protocol (internal, self-dated 2026-09-16, no independent timestamp) specified a different study - 60 dev admissions per stage sampled 30 per loop outcome, three 1-5 items (evidence support, conclusion support, clinical soundness), a third rater on a 40-trace overlap, and a paired analysis of the mean item score. The executed audit used 42 held-out test admissions, binary Q1/Q2 plus two preferences, two raters on everything and a binary composite with an admission-cluster bootstrap. The deviations are not documented in a dated amendment.
- `mimic_version` (missing evidence): MIMIC-IV release version is not recorded in the audit artifacts (repository mentions both 2.2 and 3.1).
- `checkpoint_volume_not_inspected` (missing evidence): A large experiment-checkpoint volume on the cluster is not mounted by any running workload and was not inspected (read-only discovery); it may hold zero-shot generation outputs.
- `claim:generator` (unverified claim): Appendix B: zero_shot_rationales_traced_to_generator_outputs: expected 84, observed 0
- `claim:dev_split` (manuscript discrepancy): Appendix B: source_split_values: expected ['dev'], observed ['test']
- `claim:criteria_and_preregistration` (manual review): The three named criteria are the 1-5 items of the pre-rating protocol, which were not used. Clinicians answered two per-rationale questions (Q1 evidence grounding, Q2 support for the target; Yes/No/Unclear) plus two pairwise preferences; there was no clinical-soundness rating. The rating interface and questions predate the first rating, but sample, instrument and analysis deviate from the pre-rating protocol, the executed analysis was implemented after all ratings, and a single-clinician unblinded preliminary analysis was written before the other clinician's last two saves.
