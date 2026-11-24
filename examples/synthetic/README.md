# Synthetic demonstration cases

**Everything here is synthetic.** The five admissions, notes, rationales, allocations and ratings were written by hand for this repository. None is derived from, paraphrased from or modelled on a MIMIC-IV record or on a rationale evaluated in the study, and no rating comes from a clinician. Synthetic notes start with `SYNTHETIC CASE - not a real patient.`; synthetic comments start with `SYNTHETIC:`.

## Files

| Path | Content | Role in the study |
|---|---|---|
| `demo_cases.json` | Single source of everything below | — |
| `data_root/` | What the server reads: annotator list, blinded pair file, admission notes, ICD-10-CM catalog subset | The rating server's data |
| `allocation_key.csv` | Which response is loop / zero-shot, verifier score, loop outcome | The allocation key, kept outside the server's data (blinding) |
| `ratings/<rater>/<case>.json` | Synthetic answers in the app's export format | Clinician exports |
| `expected/demo_summary.{json,md}` | Aggregates and agreement for the synthetic ratings | Analysis output (illustration only) |
| `icd10cm_order_2026_subset.txt` | The nine ICD-10-CM FY2026 lines the cases need (public domain, CDC/NCHS) | Source of the catalog zip |

`scripts/build_synthetic_demo.py` regenerates `data_root/`, `allocation_key.csv` and `ratings/` from `demo_cases.json` and validates every rating with the study's server rules; `scripts/demo_summary.py` regenerates `expected/`. Tests fail if either is out of date.

## What the cases demonstrate

| Case | Complaint | V2 pair | V4 pair |
|---|---|---|---|
| SYN001 | chest pain | grounded NSTEMI vs pericarditis rationale citing findings absent from the note | identical code `I21.4` (target question not shown); one rationale cites ST elevation that is not there |
| SYN002 | dyspnea | decompensated heart failure vs pneumonia rationale with invented fever and consolidation | `I50.9` vs the more specific, supported `I50.23` (specificity preference) |
| SYN003 | abdominal pain | identical target; one rationale claims a positive pregnancy test the note contradicts | `K35.80` vs over-specific `K35.32` (perforation not documented) |
| SYN004 | headache | migraine rationale contradicting the imaging vs subarachnoid hemorrhage | `I60.2` vs `I60.9` with a rationale that misreports the aneurysm location |
| SYN005 | vertigo | cerebellar stroke vs vestibular neuritis with contradicted exam findings | invalid code `R42.0` (closest catalog category shown) vs supported `I63.542` |

Across the ten pairs: both stages; the loop response in position A and in position B; loop-accepted and loop-rejected pairs; better and worse responses in both arms; every answer category (Yes / No / Unclear; A / B / Equally appropriate; A / B / Equivalent); not-applicable target questions; comments; and agreement as well as disagreement between the two synthetic raters. The synthetic results (`expected/demo_summary.md`) illustrate the procedure and say nothing about the study.

The full-size dataset that the original analysis requires (42 admissions, 84 pairs) is generated on demand by `scripts/make_synthetic_analysis_fixture.py`; it contains placeholder words, not clinical text.
