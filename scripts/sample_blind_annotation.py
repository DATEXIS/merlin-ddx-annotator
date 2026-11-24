#!/usr/bin/env python3
"""Draw the disease-balanced annotation sample for the scaled-up study.

Design (every decision is justified inline below):
  * Frame  = TEST split only. The models are trained on `train` and tuned on
    `dev`, so those splits are in-sample and would give an optimistically
    biased, non-generalising estimate (data leakage). Only `test` is clean.
  * Pool   = data/source/combined_1_4.pq, which is already the high-quality
    (match_category 0-2) set; cat 3/-1 cases were dropped upstream.
  * Exclude the cases already annotated in the pilot, so this sweep is an
    independent set and no case is annotated twice.
  * Stratify by (Chief Complaint, GT disease). We EQUALISE diseases: guarantee
    >=1 case per disease, then fill the remaining budget round-robin across
    diseases so rare diagnoses carry the same weight as common ones. This makes
    the sample a coverage / full-differential stress test rather than a
    prevalence-representative one -- an explicit, intended choice.
  * Reversibility: we still record a per-case `prevalence_weight` (inverse
    inclusion probability). Ignoring it gives the disease-balanced metric you
    asked for; applying it recovers a prevalence-weighted metric post hoc.
  * Output is saved SEPARATELY and is NOT merged with the pilot dataset.

Usage:
    python scripts/sample_blind_annotation.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# --- Fixed parameters: pre-register these so the sample is reproducible. ----- #
SEED = 20260711            # any fixed value; makes the draw deterministic
TARGET_PER_CHIEF = 50      # 50 x 7 chief complaints = 350 cases
GT_COL = "disease"         # cosine-top WikiDoc disease: a deterministic,
                           # model-INDEPENDENT label. Used only as the
                           # stratification variable, never as ground truth
                           # (the clinician provides the reference later).

ROOT = Path(__file__).resolve().parents[1]
POOL_PQ = ROOT / "data/source/combined_1_4.pq"
PATIENTS_JSON = ROOT / "data/app/patients.json"          # the pilot cases
OUT_CSV = ROOT / "data/processed/blind_annotation_sample_test.csv"
OUT_META = ROOT / "data/processed/blind_annotation_sample_test.meta.json"


def chief_key(chief: str) -> str:
    # Match the id convention used in patients.json ("<hadm_id>-abdominal_pain").
    return str(chief).strip().replace(" ", "_").lower()


def main() -> None:
    rng = np.random.default_rng(SEED)

    # 1) Load the pool. It has three rows per admission (one per gen_model); the
    #    case-level fields we sample on (split, Chief Complaint, GT disease) are
    #    identical across those rows, so we collapse to ONE row per hadm_id --
    #    the admission is the unit of annotation, not the model row.
    df = pd.read_parquet(POOL_PQ)
    keep = ["hadm_id", "split", "Chief Complaint", GT_COL]
    for opt in ("subject_id", "note_id"):        # carried through if present,
        if opt in df.columns:                    # useful later for building the
            keep.append(opt)                     # annotation-app records
    df = df[keep].drop_duplicates("hadm_id").copy()
    df["hadm_id"] = df["hadm_id"].astype(int)

    # 2) Keep TEST only (train/dev are contaminated by training/tuning).
    df = df[df["split"] == "test"].copy()

    # 3) Drop cases already annotated in the pilot (exclude by hadm_id).
    pilot = pd.DataFrame(json.loads(PATIENTS_JSON.read_text()))
    pilot_hadm = set(pilot["hadm_id"].astype(int))
    n_before = len(df)
    df = df[~df["hadm_id"].isin(pilot_hadm)].copy()
    print(f"[pool] test cases: {n_before} -> {len(df)} after removing "
          f"{n_before - len(df)} pilot-annotated cases")

    # 4) Normalise the stratifiers. Drop rows with no GT disease (can't place
    #    them in a pair); this is rare and only affects malformed rows.
    df["chief"] = df["Chief Complaint"].map(chief_key)
    df[GT_COL] = df[GT_COL].astype(str).str.strip()
    df = df[df[GT_COL].notna() & (df[GT_COL] != "") & (df[GT_COL].str.lower() != "nan")]

    selected: list[dict] = []
    summary: list[dict] = []

    # 5) Sample independently within each chief complaint (fixed quota each).
    for chief in sorted(df["chief"].unique()):
        g = df[df["chief"] == chief]

        # Group the chief's cases by GT disease = the (chief, disease) pairs.
        # Shuffle cases within each disease so the specific case picked is random
        # (not an artefact of row order), using the seeded RNG.
        pools: dict[str, list[dict]] = {}
        for disease, sub in g.groupby(GT_COL):
            recs = sub.to_dict("records")
            order = rng.permutation(len(recs))
            pools[disease] = [recs[i] for i in order]

        diseases = list(pools.keys())
        pool_size = {d: len(pools[d]) for d in diseases}          # eligible pop
        # Shuffle the order in which diseases are visited each round, so that
        # when the budget doesn't divide evenly the "extra" cases fall on a
        # random subset of diseases rather than always the first ones.
        visit_order = [diseases[i] for i in rng.permutation(len(diseases))]

        target = min(TARGET_PER_CHIEF, len(g))    # never ask for more than exist
        if target < TARGET_PER_CHIEF:
            print(f"[warn] {chief}: only {target} cases available (< "
                  f"{TARGET_PER_CHIEF}); taking all of them")

        # 6) Round-robin draw. Pass 1 takes one case from every disease
        #    (guarantees >=1 per pair, i.e. full coverage, since #diseases <=
        #    target here). Passes 2,3,... add one more per disease in rotation,
        #    which distributes the remaining budget as EQUALLY as possible
        #    across diseases -> equal weight to rare diagnoses.
        pointer = {d: 0 for d in diseases}          # next unused case per disease
        picked_from = {d: 0 for d in diseases}       # how many taken per disease
        chief_selected: list[dict] = []
        while len(chief_selected) < target:
            progressed = False                       # detect an exhausted pool
            for d in visit_order:
                if len(chief_selected) >= target:
                    break
                if pointer[d] < pool_size[d]:         # this disease still has cases
                    rec = dict(pools[d][pointer[d]])
                    pointer[d] += 1
                    picked_from[d] += 1
                    rec["disease_pick_order"] = picked_from[d]   # 1 = coverage pass
                    chief_selected.append(rec)
                    progressed = True
            if not progressed:                        # every pool drained early
                break

        # Now that per-disease counts are final, attach pool size + pick count so
        # the prevalence weight can be computed (needs the final selected_from_pair).
        for rec in chief_selected:
            rec["pool_pair_size"] = pool_size[rec[GT_COL]]
            rec["selected_from_pair"] = picked_from[rec[GT_COL]]
        selected.extend(chief_selected)

        n_take = len(chief_selected)
        per_disease = [picked_from[d] for d in diseases if picked_from[d] > 0]
        summary.append({
            "chief": chief, "selected": n_take, "diseases_covered": len(per_disease),
            "min_per_disease": min(per_disease), "max_per_disease": max(per_disease),
        })

    out = pd.DataFrame(selected)

    # 7) Build the case id in the same "{hadm}-{chief}" convention as the app.
    out["id"] = out["hadm_id"].astype(str) + "-" + out["chief"]

    # 8) Reversible weighting. Each case's inclusion probability WITHIN its pair
    #    is selected_from_pair / pool_pair_size (cases within a pair are equally
    #    likely). The Horvitz-Thompson weight is the inverse -- pool_pair_size /
    #    selected_from_pair -- so weighted metrics estimate the prevalence-
    #    representative population. Leave it unused for the balanced metric.
    out["prevalence_weight"] = out["pool_pair_size"] / out["selected_from_pair"]

    cols = ["id", "hadm_id", "chief", "split", GT_COL,
            "pool_pair_size", "selected_from_pair", "disease_pick_order",
            "prevalence_weight"]
    cols += [c for c in ("subject_id", "note_id") if c in out.columns]
    out = out[cols].sort_values(["chief", GT_COL, "disease_pick_order"]).reset_index(drop=True)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)

    # 9) Sidecar metadata for pre-registration / provenance.
    meta = {
        "seed": SEED, "target_per_chief": TARGET_PER_CHIEF, "gt_column": GT_COL,
        "frame": "test split only (train/dev excluded: models trained on train, tuned on dev)",
        "pool_file": str(POOL_PQ.relative_to(ROOT)),
        "excluded_pilot_cases": len(pilot_hadm),
        "allocation": "coverage (>=1 per disease) + round-robin equal fill",
        "total_selected": int(len(out)),
        "note": "prevalence_weight recovers a prevalence-weighted estimate; "
                "omit it for the intended disease-balanced estimate. Not merged "
                "with the pilot dataset.",
    }
    OUT_META.write_text(json.dumps(meta, indent=2))

    # --- report ------------------------------------------------------------- #
    sm = pd.DataFrame(summary)
    sm.loc["TOTAL"] = ["TOTAL", sm["selected"].sum(), sm["diseases_covered"].sum(),
                       sm["min_per_disease"].min(), sm["max_per_disease"].max()]
    print("\nPer-chief allocation (disease-balanced):")
    print(sm.to_string(index=False))
    print(f"\n[out] {OUT_CSV.relative_to(ROOT)}  ({len(out)} cases)")
    print(f"[out] {OUT_META.relative_to(ROOT)}")
    dup = out["hadm_id"].duplicated().sum()
    print(f"[check] duplicate hadm_ids in sample: {dup}  |  "
          f"overlap with pilot: {len(set(out['hadm_id']) & pilot_hadm)}")


if __name__ == "__main__":
    main()
