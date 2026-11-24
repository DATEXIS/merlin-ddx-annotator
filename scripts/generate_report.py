"""HTML helpers for the DDx-annotation reports (public subset).

The study version of this module also assembled the pilot report from the outputs of
scripts/analyse_annotations.py. That report body hard-codes interpretive statements
about the pilot results, which are not released, so only the formatting helpers and
the page template that scripts/analyse_scaleup_annotations.py imports are kept here.
The functions below are unchanged from the study version.
"""

from __future__ import annotations

import base64

import html

import json

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

DIR = ROOT / "reports/annotation_analysis"

OUT = DIR / "report.html"

SPLITS = ["train", "test"]

LABEL = {"train": "Train", "test": "Test"}


def suffix(split: str) -> str:
    return "" if split == "all" else f"_{split}"


def load_csv(name: str, split: str) -> pd.DataFrame:
    return pd.read_csv(DIR / f"{name}{suffix(split)}.csv")


def img(name: str, split: str, width: str = "100%") -> str:
    path = DIR / f"{name}{suffix(split)}.png"
    if not path.exists():
        return f"<p class='missing'>[missing figure: {path.name}]</p>"
    b64 = base64.b64encode(path.read_bytes()).decode()
    return (f"<img loading='lazy' style='width:{width};max-width:100%' "
            f"src='data:image/png;base64,{b64}' alt='{name}'>")


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def df_to_table(df: pd.DataFrame, floatfmt: dict | None = None) -> str:
    floatfmt = floatfmt or {}
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            if c in floatfmt and isinstance(v, (int, float)):
                cells.append(f"<td>{floatfmt[c](v)}</td>")
            elif isinstance(v, float):
                cells.append(f"<td>{v:.3f}</td>")
            else:
                cells.append(f"<td>{html.escape(str(v))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def stage_table(split: str) -> str:
    df = load_csv("stage_model_metrics", split)
    df = df.copy()
    df["Hit@1 [95% CI]"] = df.apply(
        lambda r: f"{r['hit@1']:.2f} [{r['hit@1_lo']:.2f}, {r['hit@1_hi']:.2f}]", axis=1)
    df["MRR [95% CI]"] = df.apply(
        lambda r: f"{r['mrr']:.2f} [{r['mrr_lo']:.2f}, {r['mrr_hi']:.2f}]", axis=1)
    df["model"] = df["model"].str.split("-").str[0]
    show = df[["model", "stage", "Hit@1 [95% CI]", "hit@3", "hit@5", "hit@10", "MRR [95% CI]"]]
    show = show.rename(columns={"model": "Model", "stage": "Stage",
                                "hit@3": "Hit@3", "hit@5": "Hit@5", "hit@10": "Hit@10"})
    return df_to_table(show, {"Hit@3": lambda v: f"{v:.2f}", "Hit@5": lambda v: f"{v:.2f}",
                              "Hit@10": lambda v: f"{v:.2f}"})


def paired_table(split: str) -> str:
    df = load_csv("paired_tests", split).copy()
    df["mcnemar_p"] = df["mcnemar_p"].map(lambda p: f"{p:.3f}")
    df["wilcoxon_p"] = df["wilcoxon_p"].map(lambda p: f"{p:.3f}")
    df = df.rename(columns={"stage": "Stage", "model_a": "A", "model_b": "B",
                            "a_only": "A only", "b_only": "B only",
                            "mcnemar_p": "McNemar p", "wilcoxon_p": "Wilcoxon p"})
    return df_to_table(df)


def kappa_table(split: str) -> str:
    df = load_csv("kappa", split).copy()
    df = df.rename(columns={"pair": "Rater pair", "kappa": "κ"})
    return df_to_table(df, {"κ": lambda v: f"{v:.2f}"})


def method(text: str) -> str:
    return f"<div class='method'><span class='tag'>What it measures &amp; why</span>{text}</div>"


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MERLIN DDx — Clinician Annotation Analysis</title>
<style>
  :root { --fg:#1a1d21; --muted:#5c6672; --line:#e3e7ec; --accent:#0072B2;
          --assessbg:#f0f7fb; --assessborder:#0072B2; --overallbg:#faf7f0;
          --paperbg:#f2f8f2; --paperborder:#2e7d32; --warn:#b45309; }
  * { box-sizing: border-box; }
  body { font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         color: var(--fg); max-width: 960px; margin: 0 auto; padding: 2rem 1.25rem 5rem; }
  header h1 { font-size: 1.7rem; margin: 0 0 .3rem; letter-spacing: -.01em; }
  .sub { color: var(--muted); margin: .15rem 0 0; font-size: .95rem; }
  .sub.warn { color: var(--warn); }
  h2 { font-size: 1.25rem; margin: 2.4rem 0 .8rem; padding-bottom: .35rem;
       border-bottom: 2px solid var(--line); }
  h3 { font-size: 1rem; color: var(--muted); margin: 1.2rem 0 .5rem; }
  section.summary, section.overall, section.protocols { border: 1px solid var(--line);
       border-radius: 10px; padding: .5rem 1.4rem 1.2rem; margin-top: 2rem; }
  section.summary { background: var(--assessbg); }
  section.overall { background: var(--overallbg); }
  section.protocols { background: #fbfbfa; }
  .lead { font-size: .95rem; color: var(--muted); }
  ul, ol { padding-left: 1.3rem; } li { margin: .35rem 0; }
  table { border-collapse: collapse; width: 100%; margin: .8rem 0; font-size: .88rem;
          display: block; overflow-x: auto; }
  th, td { border: 1px solid var(--line); padding: .4rem .6rem; text-align: right;
           white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  thead th { background: #f5f7f9; font-weight: 600; }
  tbody tr:nth-child(even) { background: #fafbfc; }
  .assess { background: var(--assessbg); border-left: 4px solid var(--assessborder);
            border-radius: 0 6px 6px 0; padding: .8rem 1.1rem; margin: 1rem 0; font-size: .95rem; }
  .method { background: #f6f7f9; border-left: 4px solid #8a94a0;
            border-radius: 0 6px 6px 0; padding: .8rem 1.1rem; margin: 1rem 0; font-size: .92rem; }
  .method .tag { color: #667180; }
  .paper { background: var(--paperbg); border-left: 4px solid var(--paperborder);
           border-radius: 0 6px 6px 0; padding: .8rem 1.1rem; margin: 1rem 0; font-size: .93rem; }
  .paper .tag { color: var(--paperborder); }
  .formula { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            background: #eceef1; padding: .05rem .3rem; border-radius: 3px; font-size: .88em; }
  .tag { display: inline-block; font-size: .7rem; font-weight: 700; letter-spacing: .06em;
            text-transform: uppercase; color: var(--accent); margin-right: .6rem; }
  .method dl { margin: .5rem 0 0; } .method dt { font-weight: 600; margin-top: .5rem; }
  .method dd { margin: .1rem 0 0; }
  .proto-grid { display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0; }
  .proto { flex: 1 1 320px; border: 1px solid var(--line); border-radius: 8px;
           padding: .3rem 1rem 1rem; background: #fff; }
  .proto h3 { color: var(--fg); }
  .proto .role { font-size: .9rem; color: var(--muted); margin-bottom: 0; }
  .imgrow { display: flex; flex-direction: column; gap: 1.4rem; align-items: stretch; }
  .imgrow figure { width: 100%; margin: 0; }
  figcaption { font-size: .75rem; color: var(--muted); text-transform: uppercase;
            letter-spacing: .05em; margin-bottom: .2rem; }
  img { border: 1px solid var(--line); border-radius: 6px; background: #fff; }
  details { margin: .6rem 0; } summary { cursor: pointer; color: var(--accent); font-size: .9rem; }
  code { background: #f0f2f4; padding: .1rem .35rem; border-radius: 4px; font-size: .85em; }
  .foot { color: var(--muted); font-size: .82rem; margin-top: 1.4rem; }
  .missing { color: #b00; font-style: italic; }
</style></head>
<body>
{{BODY}}
</body></html>"""
