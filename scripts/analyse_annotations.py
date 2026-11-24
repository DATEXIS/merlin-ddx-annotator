#!/usr/bin/env python3
"""Analyse a clinician's annotations against the two automated ground-truth
signals in combined_fixed.pq, and produce paper-grade figures.

Ground-truth signals
---------------------
1. Cosine GT   - `disease` = diseases[0] = top cosine match of a WikiDoc DDx
                 disease to the free-text "Discharge Diagnosis".
2. ICD GT      - the candidate disease whose WikiDoc icd10_regex matches the
                 earliest (most principal) code in the coder-assigned ICD_CODES.
3. Clinician GT- the diagnoses the clinician marked True (dN -> diseases[N-1]).

Stages scored (all per-model, matching scripts/extract_notes.py):
  V1 - dot-product of the model's own extracted symptom vector (v1_preds)
       against each WikiDoc disease's feature vector, top-10 by score.
  V2 - working diagnosis, ranked disease list.
  V3 - working diagnosis after labs, ranked disease list.
  V4 - predicted ICD codes.
Note: V1 is genuinely per-model (each model extracts symptoms differently
from the note) - it is NOT the same as the model-independent `diseases`/
`diseases_cossim_scores` cosine-to-discharge-text ordering used for Cosine GT.

Usage:
    python scripts/analyse_annotations.py                 # fetch + compute + plot
    python scripts/analyse_annotations.py --offline       # use last local snapshot
    ANNOTATOR=clinician1 python scripts/analyse_annotations.py
"""
from __future__ import annotations

import argparse
import ast
import base64
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import binomtest, wilcoxon

BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 12345

ROOT = Path(__file__).resolve().parents[1]
# combined_fixed.pq was superseded; combined_1_3.pq is its verified equivalent
# (reproduces the 2026-07-08 report metrics exactly)
PARQUET = ROOT / "data/source/combined_1_3.pq"
DIAG_DIR = ROOT / "data/reference/medical_schemes/diagnoses"
SNAP_DIR = ROOT / "data/app"
OUT_DIR = ROOT / "reports/annotation_analysis"

API_URL = os.environ.get("APP_URL", "")
AUTH_USER = os.environ.get("AUTH_USER", "")
AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "")
ANNOTATOR = os.environ.get("ANNOTATOR", "clinician1")
KS = [1, 3, 5, 10]

# Okabe-Ito colour-blind-safe palette
CB = {
    "blue": "#0072B2", "orange": "#E69F00", "green": "#009E73",
    "vermilion": "#D55E00", "purple": "#CC79A7", "sky": "#56B4E9",
    "yellow": "#F0E442", "grey": "#999999", "black": "#000000",
}
MODEL_COLORS = {"Llama-3.3-70B-Instruct": CB["blue"], "Qwen3-32B": CB["orange"],
                "medgemma-27b-it": CB["green"]}


# --------------------------------------------------------------------------- #
# Fetch                                                                        #
# --------------------------------------------------------------------------- #
def fetch_annotations(offline: bool) -> list[dict]:
    latest_snap = SNAP_DIR / "annotations_snapshot_latest.json"
    if offline:
        if not latest_snap.exists():
            sys.exit("No local snapshot found; run once online first.")
        print(f"[fetch] offline -> {latest_snap}")
        return json.loads(latest_snap.read_text())

    url = f"{API_URL}/api/annotations"
    cred = base64.b64encode(f"{AUTH_USER}:{AUTH_PASSWORD}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {cred}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except Exception as exc:  # noqa: BLE001 - fall back to snapshot
        print(f"[fetch] cluster unreachable ({exc}); trying local snapshot")
        return fetch_annotations(offline=True)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    (SNAP_DIR / f"annotations_snapshot_{stamp}.json").write_text(json.dumps(data, indent=2))
    latest_snap.write_text(json.dumps(data, indent=2))
    print(f"[fetch] {len(data)} records from cluster -> snapshot {stamp}")
    return data


def fetch_custom_diagnoses(patient_ids: list[str], offline: bool) -> dict[str, list[dict]]:
    """Resolve patient-scoped custom ('oN') diagnosis ids to their free-text
    labels. Only called for patients whose marks actually reference an 'o' id."""
    latest_snap = SNAP_DIR / "custom_diagnoses_snapshot_latest.json"
    if offline:
        return json.loads(latest_snap.read_text()) if latest_snap.exists() else {}
    if not patient_ids:
        return {}

    cred = base64.b64encode(f"{AUTH_USER}:{AUTH_PASSWORD}".encode()).decode()
    headers = {"Authorization": f"Basic {cred}"}
    result: dict[str, list[dict]] = {}
    for pid in patient_ids:
        req = urllib.request.Request(f"{API_URL}/api/custom-diagnoses/{pid}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result[pid] = json.load(resp)
        except Exception:  # noqa: BLE001
            result[pid] = []
    latest_snap.write_text(json.dumps(result, indent=2))
    return result


# --------------------------------------------------------------------------- #
# Parsing helpers                                                              #
# --------------------------------------------------------------------------- #
def parse_list(value) -> list:
    """Recover a list from either a real sequence or a Python-repr string."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, np.ndarray)):
        return list(value)
    if isinstance(value, str):
        try:
            out = ast.literal_eval(value)
            return list(out) if isinstance(out, (list, tuple)) else []
        except (ValueError, SyntaxError):
            return []
    return []


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def norm_icd(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(code).upper())


def icd_cat(code: str) -> str:
    """ICD-10 3-character category, e.g. K353 -> K35 (coder codes are billing-
    specific; models predict category level, so matching is done here)."""
    return norm_icd(code)[:3]


def chief_key(chief: str) -> str:
    return str(chief).strip().replace(" ", "_").lower()


_REGEX_CACHE: dict[str, dict[str, re.Pattern]] = {}


def icd_regexes(chief: str) -> dict[str, re.Pattern]:
    key = chief_key(chief)
    if key in _REGEX_CACHE:
        return _REGEX_CACHE[key]
    path = DIAG_DIR / f"{key}.csv"
    out: dict[str, re.Pattern] = {}
    if path.exists():
        d = pd.read_csv(path)
        if {"Disease", "icd10_regex"}.issubset(d.columns):
            for _, r in d.iterrows():
                pat = r["icd10_regex"]
                if isinstance(pat, str) and pat.strip():
                    try:
                        out[str(r["Disease"])] = re.compile(pat.strip())
                    except re.error:
                        pass
    _REGEX_CACHE[key] = out
    return out


def icd_rank_of(disease: str, icd_codes: list[str], regexes: dict) -> int | None:
    """Position (1-based) of the first ICD code matching the disease regex."""
    pat = regexes.get(disease)
    if pat is None:
        return None
    for rank, code in enumerate((norm_icd(c) for c in icd_codes), start=1):
        if pat.search(code):
            return rank
    return None


TOP_N_RANKS = 10  # matches scripts/extract_notes.py's TOP_N_RANKS
_VECTOR_CACHE: dict[str, dict[str, np.ndarray]] = {}


def wikidoc_vectors(chief: str) -> dict[str, np.ndarray]:
    """Disease -> symptom feature vector, mirrors extract_notes.py's
    load_wikidoc_vectors (same source CSV, same column selection)."""
    key = chief_key(chief)
    if key in _VECTOR_CACHE:
        return _VECTOR_CACHE[key]
    path = DIAG_DIR / f"{key}.csv"
    vectors: dict[str, np.ndarray] = {}
    if path.exists():
        d = pd.read_csv(path)
        vector_cols = [c for c in d.columns if c not in {"Disease", "Synonyms", "icd10_regex"}]
        if vector_cols:
            for _, r in d.iterrows():
                vectors[str(r["Disease"])] = r[vector_cols].astype(int).to_numpy()
    _VECTOR_CACHE[key] = vectors
    return vectors


def v1_rank_for_model(v1_preds: list[int], chief: str) -> list[str]:
    """Per-model V1 ranking: dot-product the model's own extracted symptom
    vector against each WikiDoc disease's feature vector, top-10 by score
    (ties broken alphabetically) - exact mirror of extract_notes.py's
    build_dotpro_rank_map, which is what the app actually shows as V1 rank."""
    vectors = wikidoc_vectors(chief)
    if not vectors or not v1_preds:
        return []
    preds = np.array(v1_preds, dtype=int)
    scored = [(label, int(np.dot(preds, vec))) for label, vec in vectors.items()
              if len(vec) == len(preds)]
    if not scored:
        return []
    scored.sort(key=lambda item: (-item[1], item[0]))
    return [norm(label) for label, _ in scored[:TOP_N_RANKS]]


# --------------------------------------------------------------------------- #
# Build per-case table                                                         #
# --------------------------------------------------------------------------- #
def build_cases(annotations: list[dict], df: pd.DataFrame, offline: bool) -> list[dict]:
    ann = {r["patientId"]: r["annotations"] for r in annotations
           if r["annotatorId"] == ANNOTATOR and r["annotations"]}
    by_hadm = {h: g for h, g in df.groupby("hadm_id")}

    # 'oN' ids are patient-scoped, clinician-added diagnoses not in the WikiDoc
    # list (see src/components/DiagnosesPanel.tsx "Other Disease" section) -
    # resolve their free-text labels via the custom-diagnoses endpoint.
    pids_with_custom = [pid for pid, marks in ann.items()
                         if any(k.startswith("o") for k in marks)]
    custom_by_pid = fetch_custom_diagnoses(pids_with_custom, offline)
    if pids_with_custom:
        print(f"[custom] resolved other-disease labels for {len(pids_with_custom)} case(s)")

    cases = []
    for pid, marks in ann.items():
        hadm = int(pid.split("-")[0])
        if hadm not in by_hadm:
            continue
        grp = by_hadm[hadm]
        base = grp.iloc[0]
        diseases = [str(x) for x in parse_list(base["diseases"])]
        cossim = [float(x) for x in parse_list(base["diseases_cossim_scores"])]
        icd_codes = [str(x) for x in parse_list(base["ICD_CODES"])]
        regexes = icd_regexes(base["Chief Complaint"])
        custom_labels = {item["id"]: item["label"] for item in custom_by_pid.get(pid, [])}

        # clinician GT: explicitly-labelled candidates (WikiDoc 'dN' + custom 'oN')
        labeled = {}  # disease -> bool
        clinician_true = []
        for k, v in marks.items():
            if k.startswith("d"):
                idx = int(k[1:]) - 1
                if 0 <= idx < len(diseases):
                    label = diseases[idx]
                else:
                    continue
            elif k.startswith("o"):
                label = custom_labels.get(k)
                if label is None:
                    continue
            else:
                continue
            labeled[label] = bool(v)
            if v:
                clinician_true.append(label)

        # ICD GT: candidate with smallest icd_rank
        icd_ranked = [(d, icd_rank_of(d, icd_codes, regexes)) for d in diseases]
        icd_ranked = [(d, r) for d, r in icd_ranked if r is not None]
        icd_gt = min(icd_ranked, key=lambda t: t[1])[0] if icd_ranked else None
        # full ICD-derived ranking: candidates ordered by the position of the
        # first coder ICD code their regex matches (stable sort keeps cosine
        # order as the tie-break); used for the GT hit@k baselines
        icd_ranking = [norm(d) for d, _ in sorted(icd_ranked, key=lambda t: t[1])]

        per_model = {}
        for _, row in grp.iterrows():
            v1_preds = [int(x) for x in parse_list(row["v1_preds"])]
            per_model[row["gen_model"]] = {
                "v1": v1_rank_for_model(v1_preds, base["Chief Complaint"]),
                "v2": [norm(x) for x in parse_list(row["v2_preds"])],
                "v3": [norm(x) for x in parse_list(row["v3_preds"])],
                "v4": [icd_cat(x) for x in parse_list(row["v4_preds"])],
            }

        cases.append({
            "pid": pid, "hadm": hadm,
            "chief": chief_key(base["Chief Complaint"]),
            "split": base["split"],
            "diseases": [norm(d) for d in diseases],
            "cossim": cossim,
            "cosine_gt": norm(diseases[0]) if diseases else None,
            "icd_gt": norm(icd_gt) if icd_gt else None,
            "icd_ranking": icd_ranking,
            "icd_reachable": bool(icd_ranked),
            "true_icd": list(dict.fromkeys(icd_cat(c) for c in icd_codes)),
            "clinician_true": [norm(d) for d in clinician_true],
            "clinician_labeled": {norm(d): b for d, b in labeled.items()},
            "per_model": per_model,
        })
    return cases


# --------------------------------------------------------------------------- #
# Ranking metrics                                                             #
# --------------------------------------------------------------------------- #
def best_rank(ranked: list[str], targets: list[str]) -> int | None:
    """1-based rank of the earliest target in the ranked list (None if absent)."""
    ranks = [ranked.index(t) + 1 for t in targets if t in ranked]
    return min(ranks) if ranks else None


def hit_at_k(ranks: list[int | None], k: int) -> float:
    valid = [r for r in ranks]
    return np.mean([1.0 if (r is not None and r <= k) else 0.0 for r in valid]) if valid else 0.0


def mrr(ranks: list[int | None]) -> float:
    return np.mean([1.0 / r if r else 0.0 for r in ranks]) if ranks else 0.0


# --------------------------------------------------------------------------- #
# Statistics: bootstrap CIs, paired tests, chance-corrected agreement          #
# --------------------------------------------------------------------------- #
def bootstrap_ci(cases: list[dict], stat_fn, n_boot: int = BOOTSTRAP_N,
                 alpha: float = 0.05) -> tuple[float, float]:
    """Case-level bootstrap 95% CI. Resamples cases (the unit of analysis) with
    replacement; the point estimate is stat_fn on the real sample."""
    if not cases:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    idx = np.arange(len(cases))
    stats = []
    for _ in range(n_boot):
        sample = [cases[i] for i in rng.choice(idx, size=len(idx), replace=True)]
        stats.append(stat_fn(sample))
    lo, hi = np.percentile(stats, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return (float(lo), float(hi))


def stage_hit1(cases: list[dict], model: str, stage: str) -> float:
    ranks = [best_rank(case_ranked(c, model, stage), c["clinician_true"]) for c in cases]
    return hit_at_k(ranks, 1)


def _v4_ranks(cases: list[dict], model: str) -> list[int | None]:
    return [best_rank(c["per_model"][model]["v4"], clinician_icd_targets(c))
            if clinician_icd_targets(c) else None for c in cases]


def stage_mrr(cases: list[dict], model: str, stage: str) -> float:
    if stage == "V4":
        return mrr(_v4_ranks(cases, model))
    ranks = [best_rank(case_ranked(c, model, stage), c["clinician_true"]) for c in cases]
    return mrr(ranks)


def v4_hit1(cases: list[dict], model: str) -> float:
    return hit_at_k(_v4_ranks(cases, model), 1)


def mcnemar_v4(cases: list[dict], model_a: str, model_b: str) -> dict:
    b = c = 0
    for case in cases:
        tgt = clinician_icd_targets(case)
        a_hit = (best_rank(case["per_model"][model_a]["v4"], tgt) == 1) if tgt else False
        b_hit = (best_rank(case["per_model"][model_b]["v4"], tgt) == 1) if tgt else False
        if a_hit and not b_hit:
            b += 1
        elif b_hit and not a_hit:
            c += 1
    n_disc = b + c
    p = binomtest(min(b, c), n_disc, 0.5).pvalue if n_disc else 1.0
    return {"a_only": b, "b_only": c, "p": p}


def wilcoxon_v4(cases: list[dict], model_a: str, model_b: str) -> float:
    ra = [1.0 / r if r else 0.0 for r in _v4_ranks(cases, model_a)]
    rb = [1.0 / r if r else 0.0 for r in _v4_ranks(cases, model_b)]
    if all(x == y for x, y in zip(ra, rb)):
        return 1.0
    try:
        return float(wilcoxon(ra, rb, zero_method="wilcox").pvalue)
    except ValueError:
        return float("nan")


def mcnemar_hit1(cases: list[dict], model_a: str, model_b: str, stage: str) -> dict:
    """Exact McNemar (binomial) on paired top-1 hit between two models."""
    b = c = 0
    for case in cases:
        a_hit = best_rank(case_ranked(case, model_a, stage), case["clinician_true"]) == 1
        b_hit = best_rank(case_ranked(case, model_b, stage), case["clinician_true"]) == 1
        if a_hit and not b_hit:
            b += 1
        elif b_hit and not a_hit:
            c += 1
    n_disc = b + c
    p = binomtest(min(b, c), n_disc, 0.5).pvalue if n_disc else 1.0
    return {"a_only": b, "b_only": c, "p": p}


def wilcoxon_rr(cases: list[dict], model_a: str, model_b: str, stage: str) -> float:
    """Wilcoxon signed-rank p-value on paired reciprocal ranks."""
    def rr(case, model):
        r = best_rank(case_ranked(case, model, stage), case["clinician_true"])
        return 1.0 / r if r else 0.0
    ra = [rr(c, model_a) for c in cases]
    rb = [rr(c, model_b) for c in cases]
    if all(x == y for x, y in zip(ra, rb)):
        return 1.0
    try:
        return float(wilcoxon(ra, rb, zero_method="wilcox").pvalue)
    except ValueError:
        return float("nan")


def _case_universe(case: dict, extra: set[str]) -> set[str]:
    return set(case["diseases"]) | set(case["clinician_true"]) | extra


def cohen_kappa_binary(cases: list[dict], pos_a, pos_b) -> float:
    """Cohen's kappa between two raters, each labelling every candidate in a
    case's universe as positive/negative. pos_a/pos_b(case) -> set of positives."""
    a11 = a10 = a01 = a00 = 0
    for case in cases:
        sa, sb = set(pos_a(case)), set(pos_b(case))
        universe = _case_universe(case, sa | sb)
        for cand in universe:
            ca, cb = cand in sa, cand in sb
            if ca and cb:
                a11 += 1
            elif ca and not cb:
                a10 += 1
            elif cb and not ca:
                a01 += 1
            else:
                a00 += 1
    total = a11 + a10 + a01 + a00
    if not total:
        return float("nan")
    p_o = (a11 + a00) / total
    p_yes_a, p_yes_b = (a11 + a10) / total, (a11 + a01) / total
    p_e = p_yes_a * p_yes_b + (1 - p_yes_a) * (1 - p_yes_b)
    return (p_o - p_e) / (1 - p_e) if p_e != 1 else float("nan")


def fleiss_kappa_top1(cases: list[dict], models: list[str], stage: str) -> float:
    """Fleiss' kappa across models on their top-1 pick per candidate."""
    rows = []  # each row = [n_positive, n_negative] over the models for one item
    m = len(models)
    for case in cases:
        tops = {model: (case_ranked(case, model, stage) or [None])[0] for model in models}
        universe = _case_universe(case, set(t for t in tops.values() if t))
        for cand in universe:
            pos = sum(1 for model in models if tops[model] == cand)
            rows.append((pos, m - pos))
    if not rows:
        return float("nan")
    n_items = len(rows)
    p_j = np.array([sum(r[0] for r in rows), sum(r[1] for r in rows)]) / (n_items * m)
    p_i = [(pos * (pos - 1) + neg * (neg - 1)) / (m * (m - 1)) for pos, neg in rows]
    p_bar = np.mean(p_i)
    p_e = np.sum(p_j ** 2)
    return (p_bar - p_e) / (1 - p_e) if p_e != 1 else float("nan")


# --------------------------------------------------------------------------- #
# Paired model-vs-ICD tests (test split only)                                  #
# --------------------------------------------------------------------------- #
# Question: does a model agree with the clinician more often than the
# ICD-derived label does, on the same cases? Both the model's top-1 diagnosis
# and the ICD-GT are single diagnosis labels matched to the clinician's
# confirmed diagnosis, so the comparison is paired per case (McNemar) and the
# effect size is a paired accuracy / kappa difference with a bootstrap CI.
# V4 is excluded on purpose: it predicts ICD *codes*, not a diagnosis, so it
# does not live in the same label space as ICD-GT and the contrast is undefined.
MVI_STAGES = ["V1", "V2", "V3"]


def _mvi_model_correct(case: dict, model: str, stage: str) -> bool:
    return best_rank(case_ranked(case, model, stage), case["clinician_true"]) == 1


def _mvi_icd_correct(case: dict) -> bool:
    return case["icd_gt"] is not None and case["icd_gt"] in case["clinician_true"]


def _holm(pvals: np.ndarray) -> np.ndarray:
    """Holm-Bonferroni adjusted p-values (no statsmodels dependency)."""
    pvals = np.asarray(pvals, dtype=float)
    m = len(pvals)
    order = np.argsort(pvals)
    adj = np.empty(m)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * pvals[idx])
        adj[idx] = min(running, 1.0)
    return adj


def _mvi_kappa_model(cases: list[dict], model: str, stage: str) -> float:
    return cohen_kappa_binary(
        cases, lambda c: set(c["clinician_true"]),
        lambda c: {(case_ranked(c, model, stage) or [None])[0]} - {None})


def _mvi_kappa_icd(cases: list[dict]) -> float:
    return cohen_kappa_binary(
        cases, lambda c: set(c["clinician_true"]), lambda c: {c["icd_gt"]} - {None})


def bootstrap_delta_acc(cases: list[dict], model: str, stage: str,
                        n_boot: int = BOOTSTRAP_N) -> tuple[float, float]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    mc = np.array([_mvi_model_correct(c, model, stage) for c in cases], dtype=float)
    ic = np.array([_mvi_icd_correct(c) for c in cases], dtype=float)
    idx = np.arange(len(cases))
    deltas = [mc[s].mean() - ic[s].mean()
              for s in (rng.choice(idx, size=len(idx), replace=True) for _ in range(n_boot))]
    lo, hi = np.percentile(deltas, [2.5, 97.5])
    return float(lo), float(hi)


def bootstrap_delta_kappa(cases: list[dict], model: str, stage: str,
                          n_boot: int = BOOTSTRAP_N) -> tuple[float, float, float, float]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    observed = _mvi_kappa_model(cases, model, stage) - _mvi_kappa_icd(cases)
    idx = np.arange(len(cases))
    deltas = []
    for _ in range(n_boot):
        sample = [cases[i] for i in rng.choice(idx, size=len(idx), replace=True)]
        deltas.append(_mvi_kappa_model(sample, model, stage) - _mvi_kappa_icd(sample))
    deltas = np.array(deltas)
    lo, hi = np.percentile(deltas, [2.5, 97.5])
    p = min(1.0, 2 * min(float(np.mean(deltas <= 0)), float(np.mean(deltas >= 0))))
    return float(observed), float(lo), float(hi), p


def paired_model_vs_icd(cases: list[dict]) -> pd.DataFrame:
    """One row per (stage, model): paired accuracy + kappa difference of the
    model vs the ICD label, both scored against the clinician."""
    conf = [c for c in cases if c["clinician_true"]]
    models = sorted({m for c in conf for m in c["per_model"]})
    rows = []
    for stage in MVI_STAGES:
        for model in models:
            mc = [_mvi_model_correct(c, model, stage) for c in conf]
            ic = [_mvi_icd_correct(c) for c in conf]
            b = sum(1 for m_, i_ in zip(mc, ic) if m_ and not i_)   # model only
            c_ = sum(1 for m_, i_ in zip(mc, ic) if i_ and not m_)  # ICD only
            n_disc = b + c_
            p_mc = binomtest(b, n_disc, 0.5, alternative="two-sided").pvalue if n_disc else 1.0
            da_lo, da_hi = bootstrap_delta_acc(conf, model, stage)
            dk, dk_lo, dk_hi, dk_p = bootstrap_delta_kappa(conf, model, stage)
            rows.append({
                "stage": stage, "model": model.split("-")[0],
                "model_acc": float(np.mean(mc)), "icd_acc": float(np.mean(ic)),
                "delta_acc": float(np.mean(mc)) - float(np.mean(ic)),
                "delta_acc_lo": da_lo, "delta_acc_hi": da_hi,
                "b_model_only": b, "c_icd_only": c_, "discordant_n": n_disc,
                "mcnemar_p": p_mc,
                "delta_kappa": dk, "kappa_lo": dk_lo, "kappa_hi": dk_hi, "kappa_boot_p": dk_p,
            })
    df = pd.DataFrame(rows)
    df["mcnemar_p_holm"] = np.nan
    df["significant_holm"] = False
    for stage in MVI_STAGES:                          # Holm within each stage family
        mask = df["stage"] == stage
        adj = _holm(df.loc[mask, "mcnemar_p"].to_numpy())
        df.loc[mask, "mcnemar_p_holm"] = adj
        df.loc[mask, "significant_holm"] = adj < 0.05
    df.attrs["n_conf"] = len(conf)
    df.attrs["n_no_icd"] = sum(1 for c in conf if c["icd_gt"] is None)
    return df


# --------------------------------------------------------------------------- #
# Metrics                                                                      #
# --------------------------------------------------------------------------- #
def compute_metrics(cases: list[dict]) -> dict:
    n = len(cases)
    res: dict = {"n_cases": n}

    # M3 recall ceiling ------------------------------------------------------ #
    # confirmed  = clinician marked >=1 diagnosis true (WikiDoc or custom 'other')
    # in_list    = that confirmed diagnosis is actually reachable from the
    #              WikiDoc candidate list a model could have predicted from
    has_true = [c for c in cases if c["clinician_true"]]
    in_list = [c for c in has_true if set(c["clinician_true"]) & set(c["diseases"])]
    res["ceiling_confirmed"] = len(has_true) / n
    res["ceiling_true_in_list"] = len(in_list) / n
    res["ceiling_icd_reachable"] = np.mean([c["icd_reachable"] for c in cases])
    ceil_by_cc = {}
    for cc in sorted({c["chief"] for c in cases}):
        sub = [c for c in cases if c["chief"] == cc]
        sub_in_list = [c for c in sub if set(c["clinician_true"]) & set(c["diseases"])]
        ceil_by_cc[cc] = (len(sub_in_list) / len(sub) if sub else 0.0, len(sub))
    res["ceiling_by_cc"] = ceil_by_cc

    # Restrict GT comparisons to cases where clinician confirmed a diagnosis
    conf = has_true

    # M1 automated GT agreement -------------------------------------------- #
    both = [c for c in cases if c["icd_gt"] is not None]
    res["icd_vs_cosine_agree"] = (
        np.mean([c["cosine_gt"] == c["icd_gt"] for c in both]), len(both))

    # M2 clinician adjudication -------------------------------------------- #
    res["clinician_vs_cosine_agree"] = (
        np.mean([c["cosine_gt"] in c["clinician_true"] for c in conf]), len(conf))
    res["clinician_vs_cosine_ci"] = bootstrap_ci(
        conf, lambda cc: np.mean([c["cosine_gt"] in c["clinician_true"] for c in cc]) if cc else 0.0)
    icd_conf = [c for c in conf if c["icd_gt"] is not None]
    res["clinician_vs_icd_agree"] = (
        np.mean([c["icd_gt"] in c["clinician_true"] for c in icd_conf]), len(icd_conf))
    res["clinician_vs_icd_ci"] = bootstrap_ci(
        icd_conf, lambda cc: np.mean([c["icd_gt"] in c["clinician_true"] for c in cc]) if cc else 0.0)
    # tie-break where the two automated GTs disagree
    disagree = [c for c in icd_conf if c["cosine_gt"] != c["icd_gt"]]
    backs_cosine = sum(c["cosine_gt"] in c["clinician_true"] for c in disagree)
    backs_icd = sum(c["icd_gt"] in c["clinician_true"] for c in disagree)
    res["tiebreak"] = {
        "n_disagree": len(disagree), "backs_cosine": backs_cosine,
        "backs_icd": backs_icd, "backs_neither": len(disagree) - backs_cosine - backs_icd,
    }

    # M4/M6 stage x model accuracy against clinician GT (+ bootstrap 95% CIs) - #
    models = sorted({m for c in cases for m in c["per_model"]})
    stage_rows = []
    for model in models:
        for stage in ["V1", "V2", "V3"]:
            ranks = [best_rank(case_ranked(c, model, stage), c["clinician_true"]) for c in conf]
            h1_lo, h1_hi = bootstrap_ci(conf, lambda cc, m=model, s=stage: stage_hit1(cc, m, s))
            mrr_lo, mrr_hi = bootstrap_ci(conf, lambda cc, m=model, s=stage: stage_mrr(cc, m, s))
            stage_rows.append({
                "model": model, "stage": stage,
                **{f"hit@{k}": hit_at_k(ranks, k) for k in KS},
                "hit@1_lo": h1_lo, "hit@1_hi": h1_hi,
                "mrr": mrr(ranks), "mrr_lo": mrr_lo, "mrr_hi": mrr_hi,
            })
        # V4: ICD codes vs coder ICD (3-char category)
        ranks_v4 = [best_rank(c["per_model"][model]["v4"], clinician_icd_targets(c))
                    if clinician_icd_targets(c) else None for c in conf]
        h1_lo, h1_hi = bootstrap_ci(conf, lambda cc, m=model: v4_hit1(cc, m))
        mrr_lo, mrr_hi = bootstrap_ci(conf, lambda cc, m=model: stage_mrr(cc, m, "V4"))
        stage_rows.append({
            "model": model, "stage": "V4",
            **{f"hit@{k}": hit_at_k(ranks_v4, k) for k in KS},
            "hit@1_lo": h1_lo, "hit@1_hi": h1_hi,
            "mrr": mrr(ranks_v4), "mrr_lo": mrr_lo, "mrr_hi": mrr_hi,
        })
    res["stage_model"] = pd.DataFrame(stage_rows)

    # GT hit@k baselines: the two automated GT signals read as *rankings* and
    # scored against the clinician, on the same confirmed cases as the models.
    # Cosine ranking = candidate list ordered by cosine to the discharge text;
    # ICD ranking = candidates ordered by principal-first coder ICD code match
    # (cases with no matching candidate count as misses, keeping the
    # denominator identical to the model rows).
    gt_rows = []
    for name, ranking_of in [("cosine-GT", lambda c: c["diseases"]),
                             ("ICD-GT", lambda c: c["icd_ranking"])]:
        ranks = [best_rank(ranking_of(c), c["clinician_true"]) for c in conf]
        h1_lo, h1_hi = bootstrap_ci(
            conf, lambda cc, f=ranking_of: hit_at_k(
                [best_rank(f(c), c["clinician_true"]) for c in cc], 1))
        gt_rows.append({
            "reference": name, "n": len(conf),
            **{f"hit@{k}": hit_at_k(ranks, k) for k in KS},
            "hit@1_lo": h1_lo, "hit@1_hi": h1_hi, "mrr": mrr(ranks),
        })
    res["gt_hit"] = pd.DataFrame(gt_rows)

    # Paired model comparisons (McNemar on Hit@1, Wilcoxon on reciprocal rank) - #
    paired_rows = []
    for stage in ["V2", "V3", "V4"]:
        for i, a in enumerate(models):
            for b in models[i + 1:]:
                if stage == "V4":
                    mc = mcnemar_v4(conf, a, b)
                    wp = wilcoxon_v4(conf, a, b)
                else:
                    mc = mcnemar_hit1(conf, a, b, stage)
                    wp = wilcoxon_rr(conf, a, b, stage)
                paired_rows.append({
                    "stage": stage, "model_a": a.split("-")[0], "model_b": b.split("-")[0],
                    "a_only": mc["a_only"], "b_only": mc["b_only"],
                    "mcnemar_p": mc["p"], "wilcoxon_p": wp,
                })
    res["paired"] = pd.DataFrame(paired_rows)

    # Chance-corrected agreement (Cohen's / Fleiss' kappa) at V3 --------------- #
    kappa_rows = []
    for model in models:
        k = cohen_kappa_binary(
            conf, lambda c: set(c["clinician_true"]),
            lambda c, m=model: {(case_ranked(c, m, "V3") or [None])[0]} - {None})
        kappa_rows.append({"pair": f"clinician vs {model.split('-')[0]} (V3 top-1)", "kappa": k})
    kappa_rows.append({
        "pair": "clinician vs cosine-GT",
        "kappa": cohen_kappa_binary(conf, lambda c: set(c["clinician_true"]),
                                    lambda c: {c["cosine_gt"]}),
    })
    kappa_rows.append({
        "pair": "clinician vs ICD-GT",
        "kappa": cohen_kappa_binary(icd_conf, lambda c: set(c["clinician_true"]),
                                    lambda c: {c["icd_gt"]}),
    })
    kappa_rows.append({
        "pair": "models mutual (Fleiss, V3 top-1)",
        "kappa": fleiss_kappa_top1(conf, models, "V3"),
    })
    res["kappa"] = pd.DataFrame(kappa_rows)

    # sensitivity: model ranking (V2 Hit@1) under cosine vs clinician GT ---- #
    sens = {}
    for model in models:
        r_kon, r_cos = [], []
        for c in conf:
            ranked = c["per_model"][model]["v2"]
            r_kon.append(best_rank(ranked, c["clinician_true"]))
            r_cos.append(best_rank(ranked, [c["cosine_gt"]]))
        sens[model] = {"clinician_hit@1": hit_at_k(r_kon, 1),
                       "cosine_hit@1": hit_at_k(r_cos, 1)}
    res["sensitivity_v2"] = sens

    # M5 calibration: cosine score of the clinician-true diagnosis vs every
    # OTHER candidate in the same confirmed case (the differential's distractors).
    pos, neg = [], []
    for c in conf:
        true_set = set(c["clinician_true"])
        for d, score in zip(c["diseases"], c["cossim"]):
            (pos if d in true_set else neg).append(score)
    res["calib"] = {"pos": pos, "neg": neg, "auc": auc_score(pos, neg)}

    res["models"] = models
    return res


def case_ranked(case: dict, model: str, stage: str) -> list[str]:
    return case["per_model"][model][stage.lower()]


def clinician_icd_targets(case: dict) -> list[str]:
    """Map the clinician's true diagnoses to ICD codes via the WikiDoc regex,
    approximated here by the true coder ICD codes the clinician's dx should match."""
    # Best available proxy: the admission's true ICD codes (coder-assigned).
    return case["true_icd"]


def auc_score(pos: list[float], neg: list[float]) -> float | None:
    if not pos or not neg:
        return None
    wins = sum(1 for p in pos for q in neg if p > q)
    ties = sum(1 for p in pos for q in neg if p == q)
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


# --------------------------------------------------------------------------- #
# Plots                                                                        #
# --------------------------------------------------------------------------- #
def set_style():
    plt.rcParams.update({
        "figure.dpi": 120, "savefig.dpi": 300, "font.size": 11,
        "font.family": "DejaVu Sans", "axes.spines.top": False,
        "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.25,
        "axes.axisbelow": True, "legend.frameon": False,
    })


def save(fig, name, tag=""):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    full_name = f"{name}_{tag}" if tag else name
    for ext in ("png", "pdf"):
        fig.savefig(OUT_DIR / f"{full_name}.{ext}", bbox_inches="tight")
    plt.close(fig)
    print(f"[plot] {full_name}.png / .pdf")


def plot_gt_agreement(res, tag=""):
    labels = ["ICD vs Cosine", "Clinician vs Cosine", "Clinician vs ICD"]
    vals = [res["icd_vs_cosine_agree"][0], res["clinician_vs_cosine_agree"][0],
            res["clinician_vs_icd_agree"][0]]
    ns = [res["icd_vs_cosine_agree"][1], res["clinician_vs_cosine_agree"][1],
          res["clinician_vs_icd_agree"][1]]
    fig, ax = plt.subplots(figsize=(6, 3.6))
    bars = ax.bar(labels, vals, color=[CB["grey"], CB["blue"], CB["orange"]], width=0.6)
    for b, v, m in zip(bars, vals, ns):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.0%}\n(n={m})",
                ha="center", va="bottom", fontsize=9)
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("Agreement rate")
    title = "Ground-truth agreement" + (f"  [{tag}]" if tag else "")
    ax.set_title(title, loc="left", fontweight="bold")
    save(fig, "01_gt_agreement", tag)


def plot_tiebreak(res, tag=""):
    t = res["tiebreak"]
    if t["n_disagree"] == 0:
        return
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    parts = ["Backs cosine", "Backs ICD", "Backs neither"]
    vals = [t["backs_cosine"], t["backs_icd"], t["backs_neither"]]
    ax.bar(parts, vals, color=[CB["blue"], CB["orange"], CB["grey"]], width=0.6)
    for i, v in enumerate(vals):
        ax.text(i, v + 0.05, str(v), ha="center", va="bottom")
    ax.set_ylabel("Cases")
    title = f"Clinician tie-break where ICD≠Cosine (n={t['n_disagree']})" + (f"  [{tag}]" if tag else "")
    ax.set_title(title, loc="left", fontweight="bold")
    save(fig, "02_tiebreak", tag)


def plot_hit_curves(res, tag=""):
    df = res["stage_model"]
    gt = res["gt_hit"].set_index("reference")
    gt_styles = {"cosine-GT": (CB["grey"], "--"), "ICD-GT": (CB["black"], ":")}
    stages = ["V1", "V2", "V3"]
    fig, axes = plt.subplots(1, len(stages), figsize=(11, 3.6), sharey=True)
    for ax, stage in zip(axes, stages):
        for model in res["models"]:
            row = df[(df.model == model) & (df.stage == stage)].iloc[0]
            ys = [row[f"hit@{k}"] for k in KS]
            ax.plot(KS, ys, marker="o", label=model.split("-")[0],
                    color=MODEL_COLORS.get(model, CB["black"]))
        for ref, (color, ls) in gt_styles.items():
            ys = [gt.loc[ref, f"hit@{k}"] for k in KS]
            ax.plot(KS, ys, ls=ls, marker="s", ms=3, lw=1.2, label=ref,
                    color=color, alpha=0.8)
        ax.set_title(stage, fontweight="bold")
        ax.set_xlabel("k")
        ax.set_xticks(KS)
        ax.set_ylim(0, 1.05)
    axes[0].set_ylabel("Hit@k vs clinician GT")
    axes[-1].legend(loc="lower right", fontsize=8)
    suptitle = "Rank accuracy per stage and model" + (f"  [{tag}]" if tag else "")
    fig.suptitle(suptitle, x=0.01, y=1.04, ha="left", fontweight="bold")
    fig.tight_layout()
    save(fig, "03_hit_at_k", tag)


def plot_mrr(res, tag=""):
    df = res["stage_model"]
    stages = ["V1", "V2", "V3", "V4"]
    models = res["models"]
    x = np.arange(len(stages))
    w = 0.25
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    for i, model in enumerate(models):
        rows = [df[(df.model == model) & (df.stage == s)].iloc[0] for s in stages]
        vals = [r["mrr"] for r in rows]
        lo = [r["mrr"] - r["mrr_lo"] for r in rows]
        hi = [r["mrr_hi"] - r["mrr"] for r in rows]
        ax.bar(x + (i - 1) * w, vals, w, label=model.split("-")[0],
               color=MODEL_COLORS.get(model, CB["black"]),
               yerr=[lo, hi], capsize=2, error_kw={"elinewidth": 0.8, "alpha": 0.7})
    ax.set_xticks(x)
    ax.set_xticklabels(stages)
    ax.set_ylabel("MRR vs clinician GT")
    ax.set_ylim(0, 1.05)
    title = "Mean reciprocal rank by stage (95% CI)" + (f"  [{tag}]" if tag else "")
    ax.set_title(title, loc="left", fontweight="bold")
    ax.legend(fontsize=9, ncol=3)
    save(fig, "04_mrr", tag)


def plot_progression(res, tag=""):
    df = res["stage_model"]
    stages = ["V1", "V2", "V3"]
    fig, ax = plt.subplots(figsize=(6, 3.8))
    for model in res["models"]:
        ys = [df[(df.model == model) & (df.stage == s)]["hit@1"].iloc[0] for s in stages]
        ax.plot(stages, ys, marker="o", label=model.split("-")[0],
                color=MODEL_COLORS.get(model, CB["black"]))
    ax.set_ylabel("Hit@1 vs clinician GT")
    ax.set_ylim(0, 1.05)
    title = "Does the true diagnosis climb across stages?" + (f"  [{tag}]" if tag else "")
    ax.set_title(title, loc="left", fontweight="bold")
    ax.legend(fontsize=9)
    save(fig, "05_stage_progression", tag)


def plot_calibration(res, tag=""):
    c = res["calib"]
    fig, ax = plt.subplots(figsize=(6, 3.8))
    bins = np.linspace(0, max(c["pos"] + c["neg"] + [0.01]), 16)
    ax.hist(c["neg"], bins=bins, alpha=0.6, density=True,
            label=f"other candidates (n={len(c['neg'])})", color=CB["vermilion"])
    ax.hist(c["pos"], bins=bins, alpha=0.6, density=True,
            label=f"clinician-true (n={len(c['pos'])})", color=CB["green"])
    ax.set_xlabel("Cosine similarity to discharge diagnosis")
    ax.set_ylabel("Density")
    title = "Clinician-true dx vs other candidates"
    if c["auc"] is not None:
        title += f"  (AUC={c['auc']:.2f})"
    if tag:
        title += f"  [{tag}]"
    ax.set_title(title, loc="left", fontweight="bold")
    ax.legend(fontsize=9)
    save(fig, "06_calibration", tag)


def plot_ceiling(res, tag=""):
    cc = res["ceiling_by_cc"]
    names = sorted(cc)
    vals = [cc[k][0] for k in names]
    ns = [cc[k][1] for k in names]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    bars = ax.bar(names, vals, color=CB["sky"], width=0.6)
    for b, v, m in zip(bars, vals, ns):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.0%}\n(n={m})",
                ha="center", va="bottom", fontsize=8)
    ax.axhline(res["ceiling_true_in_list"], ls="--", color=CB["black"],
               label=f"overall {res['ceiling_true_in_list']:.0%}")
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Confirmed dx reachable from WikiDoc list")
    title = "Recall ceiling by chief complaint" + (f"  [{tag}]" if tag else "")
    ax.set_title(title, loc="left", fontweight="bold")
    ax.tick_params(axis="x", rotation=30)
    ax.legend(fontsize=9)
    save(fig, "07_recall_ceiling", tag)


def plot_kappa(res, tag=""):
    kdf = res["kappa"]
    labels = list(kdf["pair"])
    vals = list(kdf["kappa"])
    colors = [CB["grey"] if "models mutual" in p or "GT" in p else CB["purple"] for p in labels]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    y = np.arange(len(labels))
    ax.barh(y, vals, color=colors, height=0.6)
    for i, v in enumerate(vals):
        ax.text(v + 0.01 if v >= 0 else v - 0.01, i, f"{v:.2f}",
                va="center", ha="left" if v >= 0 else "right", fontsize=9)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, max(1.0, max(vals) + 0.1))
    ax.set_xlabel("Cohen's / Fleiss' κ (chance-corrected agreement)")
    title = "Inter-rater agreement" + (f"  [{tag}]" if tag else "")
    ax.set_title(title, loc="left", fontweight="bold")
    save(fig, "08_kappa", tag)


SHORT_COLORS = {"Llama": CB["blue"], "Qwen3": CB["orange"], "medgemma": CB["green"]}


def plot_model_vs_icd(df, tag=""):
    """Two panels: paired Δaccuracy and Δκ of each model vs the ICD label,
    both scored against the clinician, with 95% CIs. A star marks a
    model that significantly beats ICD (McNemar p<0.05 / bootstrap κ CI ≠ 0)."""
    stages = MVI_STAGES
    models = list(dict.fromkeys(df["model"]))
    x = np.arange(len(stages))
    w = 0.8 / max(len(models), 1)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))

    panels = [
        ("delta_acc", "delta_acc_lo", "delta_acc_hi", "mcnemar_p",
         "Δ accuracy  (model − ICD)", "Paired accuracy difference vs ICD"),
        ("delta_kappa", "kappa_lo", "kappa_hi", None,
         "Δ κ  (model − ICD)", "Paired Cohen's κ difference vs ICD"),
    ]
    for ax, (val, lo, hi, pcol, ylab, ptitle) in zip(axes, panels):
        for i, m in enumerate(models):
            sub = df[df.model == m]
            vals, errlo, errhi, sig = [], [], [], []
            for s in stages:
                r = sub[sub.stage == s].iloc[0]
                vals.append(r[val])
                errlo.append(r[val] - r[lo])
                errhi.append(r[hi] - r[val])
                sig.append((r[pcol] < 0.05) if pcol else (r[lo] > 0 or r[hi] < 0))
            offs = x + (i - (len(models) - 1) / 2) * w
            ax.bar(offs, vals, w, label=m, color=SHORT_COLORS.get(m, CB["black"]),
                   yerr=[errlo, errhi], capsize=2, error_kw={"elinewidth": 0.8, "alpha": 0.7})
            for xo, v, hii, star in zip(offs, vals, errhi, sig):
                if star:
                    ax.text(xo, v + hii + 0.02, "*", ha="center", va="bottom",
                            fontsize=13, fontweight="bold")
        ax.axhline(0, color=CB["black"], lw=0.9)
        ax.set_xticks(x)
        ax.set_xticklabels(stages)
        ax.set_ylabel(ylab)
        ax.set_title(ptitle, loc="left", fontsize=10, fontweight="bold")
    axes[0].legend(fontsize=9, ncol=3, loc="lower right")
    suptitle = "Model vs ICD agreement with the clinician" + (f"  [{tag}]" if tag else "")
    fig.suptitle(suptitle, x=0.01, y=1.03, ha="left", fontweight="bold")
    fig.text(0.01, -0.03, "* significant difference from ICD (McNemar p<0.05 left / bootstrap κ CI "
             "excludes 0 right); positive bar = model agrees with the clinician MORE than ICD, "
             "negative = less.", fontsize=8, color=CB["grey"], ha="left")
    fig.tight_layout()
    save(fig, "09_model_vs_icd", tag)


# --------------------------------------------------------------------------- #
# Report                                                                       #
# --------------------------------------------------------------------------- #
def print_report(res, tag=""):
    def pct(t):
        return f"{t[0]:.1%} (n={t[1]})"
    label = f"  |  split={tag}" if tag else ""
    print("\n" + "=" * 62)
    print(f"CLINICIAN ANNOTATION ANALYSIS  |  {ANNOTATOR}  |  {res['n_cases']} cases{label}")
    print("=" * 62)
    print("\n[Recall ceiling]")
    print(f"  clinician confirmed a diagnosis    : {res['ceiling_confirmed']:.1%}")
    print(f"  ...and it's in the WikiDoc list    : {res['ceiling_true_in_list']:.1%} "
          "(no model can exceed this)")
    print(f"  a candidate reachable by ICD regex : {res['ceiling_icd_reachable']:.1%}")
    print("\n[M1 automated ground-truth agreement]")
    print(f"  ICD  vs Cosine : {pct(res['icd_vs_cosine_agree'])}")
    def ci(key):
        lo, hi = res[key]
        return f"[{lo:.1%}, {hi:.1%}]"
    print("\n[M2 clinician adjudication]  (95% bootstrap CI)")
    print(f"  Clinician vs Cosine : {pct(res['clinician_vs_cosine_agree'])}  {ci('clinician_vs_cosine_ci')}")
    print(f"  Clinician vs ICD    : {pct(res['clinician_vs_icd_agree'])}  {ci('clinician_vs_icd_ci')}")
    t = res["tiebreak"]
    print(f"  tie-break (ICD≠Cosine, n={t['n_disagree']}): "
          f"cosine={t['backs_cosine']}  icd={t['backs_icd']}  neither={t['backs_neither']}")
    print("\n[M4 stage x model]  V1-V3: vs clinician dx | V4: predicted ICD "
          "vs coder ICD (3-char category); hit@1 shown with 95% bootstrap CI")
    sm = res["stage_model"].copy()
    sm["hit@1 [95% CI]"] = sm.apply(
        lambda r: f"{r['hit@1']:.2f} [{r['hit@1_lo']:.2f},{r['hit@1_hi']:.2f}]", axis=1)
    sm["mrr [95% CI]"] = sm.apply(
        lambda r: f"{r['mrr']:.2f} [{r['mrr_lo']:.2f},{r['mrr_hi']:.2f}]", axis=1)
    with pd.option_context("display.width", 140):
        print(sm[["model", "stage", "hit@1 [95% CI]", "hit@3", "hit@5",
                  "hit@10", "mrr [95% CI]"]].round(3).to_string(index=False))
    print("\n[GT hit@k baselines]  automated GT rankings scored against the clinician")
    with pd.option_context("display.width", 140):
        print(res["gt_hit"].round(3).to_string(index=False))
    print("\n[Paired model comparison]  McNemar (Hit@1) + Wilcoxon (recip. rank), p-values")
    with pd.option_context("display.width", 140):
        pv = res["paired"].copy()
        pv["mcnemar_p"] = pv["mcnemar_p"].map(lambda p: f"{p:.3f}")
        pv["wilcoxon_p"] = pv["wilcoxon_p"].map(lambda p: f"{p:.3f}")
        print(pv.to_string(index=False))
    print("\n[Chance-corrected agreement]  Cohen's / Fleiss' kappa")
    for _, r in res["kappa"].iterrows():
        print(f"  {r['pair']:38s} kappa = {r['kappa']:.3f}")
    print("\n[M4 sensitivity: V2 Hit@1 under cosine vs clinician GT]")
    for m, d in res["sensitivity_v2"].items():
        print(f"  {m:24s} clinician={d['clinician_hit@1']:.2f}  cosine={d['cosine_hit@1']:.2f}")
    c = res["calib"]
    auc = f"{c['auc']:.3f}" if c["auc"] is not None else "n/a"
    print(f"\n[M5 calibration] cosine AUC (clinician-true>false) = {auc}  "
          f"(pos={len(c['pos'])}, neg={len(c['neg'])})")
    (OUT_DIR).mkdir(parents=True, exist_ok=True)
    suffix = f"_{tag}" if tag else ""
    res["stage_model"].to_csv(OUT_DIR / f"stage_model_metrics{suffix}.csv", index=False)
    res["paired"].to_csv(OUT_DIR / f"paired_tests{suffix}.csv", index=False)
    res["kappa"].to_csv(OUT_DIR / f"kappa{suffix}.csv", index=False)
    res["gt_hit"].to_csv(OUT_DIR / f"gt_hit_at_k{suffix}.csv", index=False)
    summary = {
        "split": tag or "all",
        "excluded_cc": res.get("excluded_cc", []),
        "n_cases": res["n_cases"],
        "ceiling_confirmed": res["ceiling_confirmed"],
        "ceiling_true_in_list": res["ceiling_true_in_list"],
        "ceiling_icd_reachable": res["ceiling_icd_reachable"],
        "icd_vs_cosine_agree": res["icd_vs_cosine_agree"],
        "clinician_vs_cosine_agree": res["clinician_vs_cosine_agree"],
        "clinician_vs_cosine_ci": res["clinician_vs_cosine_ci"],
        "clinician_vs_icd_agree": res["clinician_vs_icd_agree"],
        "clinician_vs_icd_ci": res["clinician_vs_icd_ci"],
        "tiebreak": res["tiebreak"],
        "sensitivity_v2": res["sensitivity_v2"],
        "calib_auc": res["calib"]["auc"],
        "calib_pos": len(res["calib"]["pos"]),
        "calib_neg": len(res["calib"]["neg"]),
        "ceiling_by_cc": {k: list(v) for k, v in res["ceiling_by_cc"].items()},
    }
    (OUT_DIR / f"summary{suffix}.json").write_text(json.dumps(summary, indent=2))
    print(f"\n[out] metrics + figures in {OUT_DIR}")


def print_model_vs_icd(df):
    print("\n" + "=" * 62)
    print("PAIRED MODEL vs ICD  |  TEST split only  |  "
          f"n={df.attrs.get('n_conf', '?')} confirmed "
          f"({df.attrs.get('n_no_icd', 0)} without an ICD label)")
    print("=" * 62)
    show = df.copy()
    show["Δacc [95% CI]"] = show.apply(
        lambda r: f"{r['delta_acc']:+.2f} [{r['delta_acc_lo']:+.2f},{r['delta_acc_hi']:+.2f}]", axis=1)
    show["Δκ [95% CI]"] = show.apply(
        lambda r: f"{r['delta_kappa']:+.2f} [{r['kappa_lo']:+.2f},{r['kappa_hi']:+.2f}]", axis=1)
    show["McNemar p (Holm)"] = show.apply(
        lambda r: f"{r['mcnemar_p']:.3f} ({r['mcnemar_p_holm']:.3f})", axis=1)
    cols = ["stage", "model", "model_acc", "icd_acc", "Δacc [95% CI]",
            "b_model_only", "c_icd_only", "McNemar p (Holm)", "Δκ [95% CI]", "kappa_boot_p"]
    with pd.option_context("display.width", 160):
        print(show[cols].round(3).to_string(index=False))
    df.to_csv(OUT_DIR / "model_vs_icd_test.csv", index=False)
    print(f"[out] model_vs_icd_test.csv in {OUT_DIR}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="use last local snapshot instead of hitting the cluster")
    ap.add_argument("--exclude-cc", action="append", default=[], metavar="CHIEF",
                    help="chief complaint(s) to drop from the analysis, e.g. headache "
                         "(repeatable)")
    args = ap.parse_args()
    excluded = [chief_key(cc) for cc in args.exclude_cc]

    annotations = fetch_annotations(args.offline)
    if not PARQUET.exists():
        sys.exit(f"Missing {PARQUET}")
    df = pd.read_parquet(PARQUET)
    cases = build_cases(annotations, df, args.offline)
    if not cases:
        sys.exit("No annotated cases matched the parquet.")
    print(f"[build] {len(cases)} annotated cases matched to {PARQUET.name}")
    if excluded:
        before = len(cases)
        cases = [c for c in cases if c["chief"] not in excluded]
        print(f"[filter] excluded chief complaint(s) {excluded}: "
              f"{before} -> {len(cases)} cases")
        if not cases:
            sys.exit("All cases excluded by --exclude-cc.")

    splits = {
        "all": cases,
        "train": [c for c in cases if c["split"] == "train"],
        "test": [c for c in cases if c["split"] == "test"],
    }
    set_style()
    for tag, split_cases in splits.items():
        if not split_cases:
            print(f"[skip] no annotated cases for split={tag}")
            continue
        res = compute_metrics(split_cases)
        res["excluded_cc"] = excluded
        file_tag = "" if tag == "all" else tag
        plot_gt_agreement(res, file_tag)
        plot_tiebreak(res, file_tag)
        plot_hit_curves(res, file_tag)
        plot_mrr(res, file_tag)
        plot_progression(res, file_tag)
        plot_calibration(res, file_tag)
        plot_ceiling(res, file_tag)
        plot_kappa(res, file_tag)
        print_report(res, file_tag)
        # Paired model-vs-ICD: test split only (see docs/ddx_annotation/protocol.md,
        # 'Information shown to the clinicians').
        if tag == "test":
            mvi = paired_model_vs_icd(split_cases)
            plot_model_vs_icd(mvi, file_tag)
            print_model_vs_icd(mvi)


if __name__ == "__main__":
    main()
