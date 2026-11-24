#!/usr/bin/env python3
"""Analyse the 350-case scale-up annotation sweep and produce a report under
reports/annotation_analysis_3500/, structured like reports/annotation_analysis/
but tagged by *annotator* instead of by *split*.

Design differences from scripts/analyse_annotations.py (the pilot analysis):
  * Frame  = the 350 cases drawn by scripts/sample_blind_annotation.py
    (data/processed/blind_annotation_sample_test.csv), all `test` split,
    disease-balanced across the 7 chief complaints. This is NOT the same 70
    cases the pilot used - the pilot cases are explicitly excluded from the
    draw (see the sample's .meta.json) so nothing is annotated twice.
  * Pool   = data/source/combined_1_4.pq. IMPORTANT: this pool's `test` split
    also contains the 70 pilot admissions, so every case is filtered down to
    the 350-case frame by hadm_id before any metric is computed - otherwise a
    clinician's old pilot annotations would silently leak into the scale-up
    numbers.
  * Multiple human annotators (clinician1/2/3, auto-discovered from
    data/app/annotators.json) are analysed side by side rather than a single
    hard-coded ANNOTATOR, plus a new inter-annotator reliability section
    (Cohen's kappa per pair + Fleiss' kappa across all raters) on whatever
    overlap subset exists - the pilot report's headline limitation was that
    every number rested on one clinician; this is what closes that gap.
  * No prevalence weighting is applied: the sample meta note is explicit that
    the disease-balanced (unweighted) read is the intended primary estimate.

All ranking/statistics/plotting code is reused directly from
scripts/analyse_annotations.py and scripts/generate_report.py by importing
them as modules and pointing their OUT_DIR/DIR globals at the new report
directory - no metric logic is duplicated.

Usage:
    python scripts/analyse_scaleup_annotations.py             # fetch + compute + report
    python scripts/analyse_scaleup_annotations.py --offline
    python scripts/analyse_scaleup_annotations.py --exclude-cc headache
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))  # so `import merlin_ddx` works when run directly
import analyse_annotations as base  # noqa: E402
import generate_report as repbase  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402  (Agg backend already set by `base`)

OUT_DIR = ROOT / "reports/annotation_analysis_350"
POOL_PQ = ROOT / "data/source/combined_1_4.pq"
SAMPLE_CSV = ROOT / "data/processed/blind_annotation_sample_test.csv"
SAMPLE_META = ROOT / "data/processed/blind_annotation_sample_test.meta.json"
ANNOTATORS_JSON = ROOT / "data/app/annotators.json"

# Reuse the pilot modules' plotting/report helpers by redirecting their
# module-level output-directory globals; none of their function bodies need
# to change.
base.OUT_DIR = OUT_DIR
repbase.DIR = OUT_DIR
repbase.OUT = OUT_DIR / "report.html"


# --------------------------------------------------------------------------- #
# Roster / frame                                                              #
# --------------------------------------------------------------------------- #
def active_human_annotators() -> tuple[list[str], dict[str, str]]:
    roster = json.loads(ANNOTATORS_JSON.read_text())
    humans = [r for r in roster if r.get("type") == "human" and r.get("active")]
    return [r["id"] for r in humans], {r["id"]: r["name"] for r in humans}


def load_sample_frame() -> pd.DataFrame:
    return pd.read_csv(SAMPLE_CSV)


# --------------------------------------------------------------------------- #
# Inter-annotator reliability (new - the pilot had only one rater)            #
# --------------------------------------------------------------------------- #
def compute_reliability(
    cases_by_annotator: dict[str, dict[str, dict]], annotators: list[str]
) -> tuple[pd.DataFrame, float | None, int]:
    """Pairwise Cohen's kappa + Fleiss' kappa (all raters), candidate-level,
    on whatever subset of cases each pair/all raters have both annotated so
    far. Reuses base.cohen_kappa_binary; the Fleiss math is the same p_bar/p_e
    formula as base.fleiss_kappa_top1, generalised from top-1 model picks to
    full confirmed-diagnosis mark sets."""
    rows = []
    for i, a in enumerate(annotators):
        for b in annotators[i + 1:]:
            common = set(cases_by_annotator.get(a, {})) & set(cases_by_annotator.get(b, {}))
            if not common:
                rows.append({"pair": f"{a} vs {b}", "n": 0, "kappa": float("nan")})
                continue
            paired = [
                {**cases_by_annotator[a][pid], "_b_true": cases_by_annotator[b][pid]["clinician_true"]}
                for pid in common
            ]
            k = base.cohen_kappa_binary(
                paired, lambda c: set(c["clinician_true"]), lambda c: set(c["_b_true"]))
            rows.append({"pair": f"{a} vs {b}", "n": len(common), "kappa": k})
    rel_df = pd.DataFrame(rows, columns=["pair", "n", "kappa"])

    common_all = (
        set.intersection(*(set(cases_by_annotator.get(a, {})) for a in annotators))
        if annotators else set()
    )
    fleiss = None
    if len(annotators) >= 3 and common_all:
        m = len(annotators)
        item_rows = []
        for pid in common_all:
            ref = cases_by_annotator[annotators[0]][pid]
            trues = {a: set(cases_by_annotator[a][pid]["clinician_true"]) for a in annotators}
            universe = set(ref["diseases"])
            for s in trues.values():
                universe |= s
            for cand in universe:
                pos = sum(1 for a in annotators if cand in trues[a])
                item_rows.append((pos, m - pos))
        if item_rows:
            n_items = len(item_rows)
            p_j = np.array([sum(r[0] for r in item_rows), sum(r[1] for r in item_rows)]) / (n_items * m)
            p_i = [(pos * (pos - 1) + neg * (neg - 1)) / (m * (m - 1)) for pos, neg in item_rows]
            p_bar = np.mean(p_i)
            p_e = np.sum(p_j ** 2)
            fleiss = float((p_bar - p_e) / (1 - p_e)) if p_e != 1 else float("nan")
    return rel_df, fleiss, len(common_all)


def plot_reliability(rel_df: pd.DataFrame, fleiss: float | None, fleiss_n: int) -> None:
    fig, ax = plt.subplots(figsize=(7, max(2.2, 0.55 * max(len(rel_df), 1) + 1.2)))
    plot_df = rel_df.dropna(subset=["kappa"]) if not rel_df.empty else rel_df
    if plot_df.empty:
        ax.text(0.5, 0.5, "No overlapping annotations yet\n(no case annotated by 2+ raters)",
                ha="center", va="center", fontsize=11, color=base.CB["grey"], transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        y = np.arange(len(plot_df))
        vals = plot_df["kappa"].to_numpy()
        ax.barh(y, vals, color=base.CB["purple"], height=0.6)
        for i, (v, n) in enumerate(zip(vals, plot_df["n"])):
            ax.text(v + (0.01 if v >= 0 else -0.01), i, f"{v:.2f} (n={int(n)})",
                    va="center", ha="left" if v >= 0 else "right", fontsize=9)
        ax.set_yticks(y)
        ax.set_yticklabels(plot_df["pair"], fontsize=9)
        ax.invert_yaxis()
        ax.set_xlim(min(0, vals.min() - 0.1), max(1.0, vals.max() + 0.15))
        ax.set_xlabel("Cohen's κ (pairwise human agreement, candidate-level)")
    title = "Inter-annotator reliability (human vs human)"
    if fleiss is not None:
        title += f"  |  Fleiss' κ (all raters, n={fleiss_n}) = {fleiss:.2f}"
    ax.set_title(title, loc="left", fontweight="bold", fontsize=10)
    base.save(fig, "10_human_reliability")


# --------------------------------------------------------------------------- #
# Report                                                                       #
# --------------------------------------------------------------------------- #
def sec_img(name: str, aid: str, width: str = "100%") -> str:
    return repbase.img(name, aid, width)


def mvi_table_for(aid: str) -> str:
    df = repbase.load_csv("model_vs_icd", aid)
    out = pd.DataFrame({
        "Stage": df["stage"], "Model": df["model"],
        "Model acc": df["model_acc"], "ICD acc": df["icd_acc"],
        "Δacc [95% CI]": df.apply(
            lambda r: f"{r['delta_acc']:+.2f} [{r['delta_acc_lo']:+.2f}, {r['delta_acc_hi']:+.2f}]", axis=1),
        "b / c": df.apply(lambda r: f"{int(r['b_model_only'])} / {int(r['c_icd_only'])}", axis=1),
        "McNemar p (Holm)": df.apply(
            lambda r: f"{r['mcnemar_p']:.3f} ({r['mcnemar_p_holm']:.3f})", axis=1),
        "Δκ [95% CI]": df.apply(
            lambda r: f"{r['delta_kappa']:+.2f} [{r['kappa_lo']:+.2f}, {r['kappa_hi']:+.2f}]", axis=1),
        "κ boot p": df["kappa_boot_p"],
    })
    return repbase.df_to_table(out, {"Model acc": lambda v: f"{v:.2f}", "ICD acc": lambda v: f"{v:.2f}",
                                     "κ boot p": lambda v: f"{v:.3f}"})


def gt_hit_table_for(res: dict) -> str:
    fmt2 = lambda v: f"{v:.2f}"
    gt = res["gt_hit"].copy()
    gt["Hit@1 [95% CI]"] = gt.apply(
        lambda r: f"{r['hit@1']:.2f} [{r['hit@1_lo']:.2f}, {r['hit@1_hi']:.2f}]", axis=1)
    show = gt.rename(columns={"reference": "Reference", "hit@3": "Hit@3", "hit@5": "Hit@5",
                              "hit@10": "Hit@10", "mrr": "MRR"})
    show = show[["Reference", "n", "Hit@1 [95% CI]", "Hit@3", "Hit@5", "Hit@10", "MRR"]]
    return repbase.df_to_table(show, {"Hit@3": fmt2, "Hit@5": fmt2, "Hit@10": fmt2, "MRR": fmt2})


def annotator_section(aid: str, name: str, res: dict) -> str:
    n = res["n_cases"]
    p: list[str] = [
        f'<h3 id="ann-{html.escape(aid)}">{html.escape(name)} ({html.escape(aid)}) '
        f'&mdash; n={n} annotated, {repbase.pct(res["ceiling_confirmed"])} confirmed a diagnosis</h3>'
    ]

    p.append("<h4>Ground-truth agreement</h4>")
    p.append(sec_img("01_gt_agreement", aid))
    p.append(f"""<table><thead><tr><th>Comparison</th><th>Agreement</th></tr></thead><tbody>
      <tr><td>ICD vs Cosine (automated only)</td>
      <td>{repbase.pct(res['icd_vs_cosine_agree'][0])} (n={res['icd_vs_cosine_agree'][1]})</td></tr>
      <tr><td>{html.escape(name)} vs Cosine</td>
      <td>{repbase.pct(res['clinician_vs_cosine_agree'][0])} (n={res['clinician_vs_cosine_agree'][1]})</td></tr>
      <tr><td>{html.escape(name)} vs ICD</td>
      <td>{repbase.pct(res['clinician_vs_icd_agree'][0])} (n={res['clinician_vs_icd_agree'][1]})</td></tr>
      </tbody></table>""")

    p.append("<h4>Rank accuracy per stage and model (Hit@k), with automated-GT baselines</h4>")
    p.append(sec_img("03_hit_at_k", aid))
    p.append(gt_hit_table_for(res))

    p.append("<h4>Mean reciprocal rank &amp; full metric table (95% CI)</h4>")
    p.append(sec_img("04_mrr", aid))
    p.append(repbase.stage_table(aid))

    p.append("<h4>Stage progression</h4>")
    p.append(sec_img("05_stage_progression", aid))

    p.append("<h4>Cosine calibration</h4>")
    p.append(sec_img("06_calibration", aid))

    p.append("<h4>Recall ceiling</h4>")
    p.append(sec_img("07_recall_ceiling", aid))

    p.append("<h4>Chance-corrected agreement &amp; paired model significance</h4>")
    p.append(sec_img("08_kappa", aid))
    p.append(repbase.kappa_table(aid))
    p.append(repbase.paired_table(aid))

    p.append("<h4>Model vs ICD label (paired, per case)</h4>")
    p.append(sec_img("09_model_vs_icd", aid))
    p.append(mvi_table_for(aid))

    return "\n".join(p)


def annotator_placeholder(aid: str, name: str) -> str:
    return (f'<h3 id="ann-{html.escape(aid)}">{html.escape(name)} ({html.escape(aid)})</h3>'
            f'<p class="missing">No scale-up annotations yet for this rater. '
            f'Re-run this script once annotation begins.</p>')


def reliability_section(rel_df: pd.DataFrame, fleiss: float | None, fleiss_n: int) -> str:
    p = ["<h2>Inter-annotator reliability (human vs human)</h2>"]
    p.append(repbase.method('''<b>Metric:</b> Cohen&rsquo;s κ (candidate-level, same construction as the
    clinician-vs-model/GT κ in each annotator&rsquo;s Section&nbsp;8) between every pair of raters, on
    whichever cases both have annotated so far. <b>Fleiss&rsquo; κ</b> is the multi-rater generalisation
    across every listed annotator, restricted to cases everyone has annotated. <b>Why it&rsquo;s here:</b>
    the pilot report&rsquo;s single biggest caveat was that every number rested on one clinician; this
    section is what closes that gap once an overlap subset accumulates.'''))
    p.append(repbase.img("10_human_reliability", "all", "100%"))
    if not rel_df.empty:
        show = rel_df.copy()
        show["kappa"] = show["kappa"].map(lambda v: "n/a" if pd.isna(v) else f"{v:.2f}")
        show = show.rename(columns={"pair": "Rater pair", "n": "n overlap", "kappa": "κ"})
        p.append(repbase.df_to_table(show))
    else:
        p.append("<p class='missing'>Fewer than two annotators configured &mdash; no pairwise "
                 "reliability to compute.</p>")
    if fleiss is not None:
        p.append(f"<p><b>Fleiss&rsquo; κ across all listed raters</b> "
                 f"(n={fleiss_n} cases annotated by everyone): <b>{fleiss:.2f}</b>.</p>")
    else:
        p.append("<p class='missing'>Fleiss&rsquo; κ needs &ge;3 raters with a shared overlap "
                 "subset; not yet available.</p>")
    return "\n".join(p)


def build_report(
    annotators: list[str], names: dict[str, str], results: dict[str, dict],
    cases_by_annotator: dict[str, dict[str, dict]], rel_df: pd.DataFrame,
    fleiss: float | None, fleiss_n: int, meta: dict, excluded: list[str], n_sample: int,
) -> str:
    parts: list[str] = []
    p = parts.append
    total_annotated = sum(len(v) for v in cases_by_annotator.values())
    with_data = [a for a in annotators if a in results]
    excl_note = (f" &middot; <b>{', '.join(c.replace('_', ' ') for c in excluded)} excluded</b>"
                 if excluded else "")

    p(f"""<header>
      <h1>MERLIN&nbsp;DDx &mdash; Scale-up Annotation Analysis</h1>
      <p class="sub">{n_sample} disease-balanced test cases across 7 chief complaints
      &middot; annotators: {', '.join(f'{html.escape(names[a])} ({html.escape(a)})' for a in annotators)}
      {excl_note}</p>
      <p class="sub warn">{len(with_data)} of {len(annotators)} annotator(s) have scale-up annotations
      so far ({total_annotated} case-annotations total). Every section below is computed live from the
      current data &mdash; re-run <code>python scripts/analyse_scaleup_annotations.py</code> as annotation
      progresses to refresh.</p>
    </header>""")

    p(f"""<section class="protocols">
      <h2>Sample design</h2>
      <p>Pre-registered in <code>{_display_path(SAMPLE_META)}</code>:</p>
      <ul>
        <li><b>Frame:</b> {html.escape(meta['frame'])}</li>
        <li><b>Pool:</b> <code>{html.escape(meta['pool_file'])}</code></li>
        <li><b>Allocation:</b> {html.escape(meta['allocation'])} &mdash;
        {meta['target_per_chief']} cases per chief complaint &times; 7 = {meta['total_selected']}</li>
        <li><b>Stratification variable:</b> <code>{html.escape(meta['gt_column'])}</code>
        (cosine-top WikiDoc disease) &mdash; used only to balance the draw, never as ground truth</li>
        <li><b>Pilot overlap:</b> {meta['excluded_pilot_cases']} pilot cases excluded from the draw so
        no case is annotated twice</li>
        <li><b>Weighting:</b> {html.escape(meta['note'])}</li>
      </ul>
      {repbase.method('''Every metric below follows the pilot analysis conventions
      (<code>scripts/analyse_annotations.py</code>; the definitions are in
      <code>docs/ddx_annotation/analysis.md</code>). The one addition is
      <b>inter-annotator reliability</b> below, which a single-rater pilot could not compute.''')}
    </section>""")

    for aid in annotators:
        p("<section>")
        p(annotator_section(aid, names[aid], results[aid]) if aid in results
          else annotator_placeholder(aid, names[aid]))
        p("</section>")

    p(f"<section>{reliability_section(rel_df, fleiss, fleiss_n)}</section>")

    reliability_note = ("insufficient overlap yet to compute human-human agreement"
                        if rel_df.empty or rel_df["n"].sum() == 0
                        else "see the reliability section above")
    p(f"""<section class="overall">
      <h2>Status &amp; next steps</h2>
      <ul>
        <li><b>Coverage:</b> {total_annotated} of {len(annotators) * n_sample} possible
        (annotator &times; case) slots filled.</li>
        <li><b>Reliability:</b> {reliability_note}.</li>
        <li>Re-run this script (<code>python scripts/analyse_scaleup_annotations.py --offline</code>)
        after each annotation sync to refresh.</li>
      </ul>
      <p class="foot">Figures/tables regenerate from
      <code>scripts/analyse_scaleup_annotations.py</code>, reusing the metric and statistics functions
      in <code>scripts/analyse_annotations.py</code>. Output mirrors the structure of
      <code>reports/annotation_analysis/</code>, tagged by annotator id instead of by split.</p>
    </section>""")

    body = "\n".join(parts)
    template = repbase.TEMPLATE.replace(
        "<title>MERLIN DDx — Clinician Annotation Analysis</title>",
        "<title>MERLIN DDx — Scale-up Annotation Analysis</title>")
    return template.replace("{{BODY}}", body)


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #
def _display_path(path: Path) -> str:
    """Repo-relative path when possible, else the bare name — robust to inputs
    that live outside the repo (e.g. on a mounted volume)."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def load_annotations_from_tree(root: Path) -> list[dict]:
    """Build the annotation record list from a mounted annotation tree
    (root/annotations/{annotatorId}/{patientId}.json) — the exact layout the
    study backend writes — so the analysis runs on a copy of the data with no
    call back to the source app. Same record shape as GET /api/annotations."""
    from merlin_ddx.annotation_store import list_annotation_records
    from merlin_ddx.paths import data_paths
    records = list_annotation_records(data_paths(root))
    return [r.to_json() for r in records]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="use last local snapshot instead of hitting the cluster")
    ap.add_argument("--exclude-cc", action="append", default=[], metavar="CHIEF",
                    help="chief complaint(s) to drop from the analysis (repeatable)")
    ap.add_argument("--annotators", default=None,
                    help="comma-separated annotator ids, overriding the auto-discovered "
                         "active human list in data/app/annotators.json")
    # Path overrides so the analysis can run anywhere (e.g. off a mounted data
    # volume) without the repo's default layout. All optional.
    ap.add_argument("--pool-pq", type=Path, help="combined parquet (may be a 350-case subset)")
    ap.add_argument("--sample-csv", type=Path, help="blind_annotation_sample_test.csv")
    ap.add_argument("--sample-meta", type=Path, help="blind_annotation_sample_test.meta.json")
    ap.add_argument("--annotators-json", type=Path, help="annotators roster json")
    ap.add_argument("--diag-dir", type=Path, help="reference medical-scheme diagnoses dir")
    ap.add_argument("--out-dir", type=Path, help="output reports dir")
    ap.add_argument("--annotations-root", type=Path, metavar="ROOT",
                    help="read annotations from ROOT/annotations/**.json (the backend storage "
                         "layout) instead of fetching from the app; implies self-contained run")
    args = ap.parse_args()
    excluded = [base.chief_key(cc) for cc in args.exclude_cc]

    global POOL_PQ, SAMPLE_CSV, SAMPLE_META, ANNOTATORS_JSON, OUT_DIR
    if args.pool_pq:
        POOL_PQ = args.pool_pq
    if args.sample_csv:
        SAMPLE_CSV = args.sample_csv
    if args.sample_meta:
        SAMPLE_META = args.sample_meta
    if args.annotators_json:
        ANNOTATORS_JSON = args.annotators_json
    if args.diag_dir:
        base.DIAG_DIR = args.diag_dir
    if args.out_dir:
        OUT_DIR = args.out_dir
        base.OUT_DIR = OUT_DIR
        repbase.DIR = OUT_DIR
        repbase.OUT = OUT_DIR / "report.html"

    meta = json.loads(SAMPLE_META.read_text())
    expected_pool = (ROOT / meta["pool_file"]).resolve()
    if expected_pool != POOL_PQ.resolve():
        print(f"[warn] sample meta pool_file={meta['pool_file']!r} != "
              f"configured POOL_PQ={POOL_PQ}")

    sample = load_sample_frame()
    sample_hadm = set(sample["hadm_id"].astype(int))
    n_sample = len(sample)
    print(f"[frame] {n_sample} scale-up cases from {SAMPLE_CSV.name}")

    if args.annotators:
        annotators = [a.strip() for a in args.annotators.split(",") if a.strip()]
        names = {a: a for a in annotators}
    else:
        annotators, names = active_human_annotators()
    print(f"[annotators] {annotators}")

    if args.annotations_root:
        annotations = load_annotations_from_tree(args.annotations_root)
        print(f"[annotations] {len(annotations)} records from tree "
              f"{args.annotations_root}/annotations")
    else:
        annotations = base.fetch_annotations(args.offline)
    offline = args.offline or bool(args.annotations_root)
    if not POOL_PQ.exists():
        sys.exit(f"Missing pool parquet: {POOL_PQ}")
    df = pd.read_parquet(POOL_PQ)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base.set_style()

    cases_by_annotator: dict[str, dict[str, dict]] = {}
    results: dict[str, dict] = {}
    for aid in annotators:
        base.ANNOTATOR = aid
        all_cases = base.build_cases(annotations, df, offline)
        cases = [c for c in all_cases if c["hadm"] in sample_hadm]
        if excluded:
            before = len(cases)
            cases = [c for c in cases if c["chief"] not in excluded]
            print(f"[filter] {aid}: excluded {excluded}: {before} -> {len(cases)} cases")
        cases_by_annotator[aid] = {c["pid"]: c for c in cases}
        print(f"[build] {aid}: {len(cases)} scale-up cases annotated")
        if not cases:
            print(f"[skip] {aid}: no scale-up annotations yet")
            continue
        res = base.compute_metrics(cases)
        res["excluded_cc"] = excluded
        base.plot_gt_agreement(res, aid)
        base.plot_tiebreak(res, aid)
        base.plot_hit_curves(res, aid)
        base.plot_mrr(res, aid)
        base.plot_progression(res, aid)
        base.plot_calibration(res, aid)
        base.plot_ceiling(res, aid)
        base.plot_kappa(res, aid)
        base.print_report(res, aid)
        mvi = base.paired_model_vs_icd(cases)
        base.plot_model_vs_icd(mvi, aid)
        mvi.to_csv(OUT_DIR / f"model_vs_icd_{aid}.csv", index=False)
        results[aid] = res

    rel_df, fleiss, fleiss_n = compute_reliability(cases_by_annotator, annotators)
    rel_df.to_csv(OUT_DIR / "human_reliability.csv", index=False)
    plot_reliability(rel_df, fleiss, fleiss_n)
    pairwise = [{**row, "kappa": None if pd.isna(row["kappa"]) else row["kappa"]}
                for row in rel_df.to_dict("records")]
    (OUT_DIR / "reliability_summary.json").write_text(json.dumps({
        "annotators": annotators, "pairwise": pairwise,
        "fleiss_kappa_all": fleiss, "fleiss_n": fleiss_n,
    }, indent=2, allow_nan=False))

    html_out = build_report(annotators, names, results, cases_by_annotator,
                            rel_df, fleiss, fleiss_n, meta, excluded, n_sample)
    out_path = OUT_DIR / "report.html"
    out_path.write_text(html_out)
    size_kb = out_path.stat().st_size / 1024
    print(f"[report] {out_path}  ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
