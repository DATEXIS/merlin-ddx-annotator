#!/usr/bin/env python
"""Run the original DDx-annotation analysis on a local copy of the annotation store.

    python scripts/make_synthetic_ddx_fixture.py --out .demo/ddx_fixture
    python scripts/run_ddx_analysis.py pilot --fixture .demo/ddx_fixture --annotator synthetic_rater_1 --out .demo/ddx_pilot
    python scripts/run_ddx_analysis.py study --fixture .demo/ddx_fixture --out .demo/ddx_study
    python scripts/ddx_agreement.py --fixture .demo/ddx_fixture --out .demo/ddx_study/agreement.json

``pilot`` runs ``scripts/analyse_annotations.py`` (one annotator; all / train / test) on
the records of the pilot cohort (``--cohort``). The study's pilot run used a case
pool that contained only pilot admissions; when the pool also holds the 350-case
study, as here, the cohort restriction keeps the 350-case records out, which the
pilot script itself does not do;
``study`` runs ``scripts/analyse_scaleup_annotations.py`` (every annotator of the
350-case frame, plus pairwise Cohen's and Fleiss' kappa). Their code is the study's,
with the changes listed in CHANGES_FROM_STUDY.md; this wrapper only points their
module-level paths at the given inputs. In the study, the analysis read the
annotations and the clinician-added diagnoses from snapshots of the annotation
server; this wrapper writes the same two snapshot files from ``<data-root>/annotations``
and ``<data-root>/custom_diagnoses`` (the backend's storage layout), so nothing is
fetched over the network.

Inputs (``--fixture DIR`` fills all of them from make_synthetic_ddx_fixture.py output):
``--data-root`` annotation store, ``--pool`` case pool (parquet), ``--diagnoses``
candidate schemes, and for ``study`` also ``--sample-csv``, ``--sample-meta``,
``--annotators-json``.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def cohort_ids(path: Path | None) -> set[str] | None:
    """Case ids of a cohort file: a list of ids or a patients*.json list of records."""
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return {item if isinstance(item, str) else item["id"] for item in data}


def write_snapshots(data_root: Path, snapshot_dir: Path, cohort: set[str] | None = None) -> None:
    """The two server snapshots the original analysis reads in offline mode, optionally
    restricted to the annotation records of one cohort."""
    from merlin_ddx.annotation_store import list_annotation_records, list_custom_diagnoses
    from merlin_ddx.paths import data_paths

    paths = data_paths(data_root)
    records = [record.to_json() for record in list_annotation_records(paths)
               if cohort is None or record.patient_id in cohort]
    custom = {}
    for path in sorted(paths.custom_diagnoses_dir.glob("*.json")):
        custom[path.stem] = [item.to_json() for item in list_custom_diagnoses(paths, path.stem)]
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "annotations_snapshot_latest.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    (snapshot_dir / "custom_diagnoses_snapshot_latest.json").write_text(json.dumps(custom, indent=2), encoding="utf-8")


def resolve(args: argparse.Namespace) -> argparse.Namespace:
    if args.fixture:
        fixture = args.fixture
        args.data_root = args.data_root or fixture / "data_root"
        args.pool = args.pool or fixture / "pool.pq"
        args.diagnoses = args.diagnoses or fixture / "diagnoses"
        if args.command == "pilot":
            args.cohort = args.cohort or fixture / "pilot_cohort.json"
        if args.command == "study":
            args.sample_csv = args.sample_csv or fixture / "sample.csv"
            args.sample_meta = args.sample_meta or fixture / "sample.meta.json"
            args.annotators_json = args.annotators_json or fixture / "annotators.json"
    required = ["data_root", "pool", "diagnoses"] + (["sample_csv", "sample_meta", "annotators_json"]
                                                      if args.command == "study" else ["cohort"])
    missing = [name for name in required if getattr(args, name, None) is None]
    if missing:
        raise SystemExit(f"missing inputs: {', '.join('--' + m.replace('_', '-') for m in missing)}")
    return args


def run(args: argparse.Namespace) -> Path:
    os.environ.setdefault("MPLCONFIGDIR", str(args.out.resolve() / ".matplotlib"))
    import analyse_annotations as base

    out = args.out.resolve()
    snapshot = out / "_snapshot"
    write_snapshots(args.data_root.resolve(), snapshot, cohort_ids(args.cohort) if args.command == "pilot" else None)
    base.SNAP_DIR = snapshot
    base.DIAG_DIR = args.diagnoses.resolve()
    base.PARQUET = args.pool.resolve()
    base.OUT_DIR = out
    base._REGEX_CACHE.clear()
    base._VECTOR_CACHE.clear()
    excluded = [arg for cc in args.exclude_cc for arg in ("--exclude-cc", cc)]
    argv = sys.argv
    try:
        if args.command == "pilot":
            base.ANNOTATOR = args.annotator
            sys.argv = ["analyse_annotations.py", "--offline", *excluded]
            base.main()
        else:
            import analyse_scaleup_annotations as scaleup
            sys.argv = ["analyse_scaleup_annotations.py", "--offline",
                        "--annotations-root", str(args.data_root.resolve()), "--pool-pq", str(base.PARQUET),
                        "--sample-csv", str(args.sample_csv.resolve()), "--sample-meta", str(args.sample_meta.resolve()),
                        "--annotators-json", str(args.annotators_json.resolve()), "--diag-dir", str(base.DIAG_DIR),
                        "--out-dir", str(out), *excluded]
            if args.annotators:
                sys.argv += ["--annotators", args.annotators]
            scaleup.main()
    finally:
        sys.argv = argv
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("pilot", "study"))
    parser.add_argument("--fixture", type=Path, help="output directory of make_synthetic_ddx_fixture.py")
    parser.add_argument("--data-root", type=Path, help="annotation store: annotations/, custom_diagnoses/")
    parser.add_argument("--pool", type=Path, help="case pool parquet")
    parser.add_argument("--diagnoses", type=Path, help="directory of <chief_complaint>.csv candidate schemes")
    parser.add_argument("--sample-csv", type=Path, help="study: sampling frame")
    parser.add_argument("--sample-meta", type=Path, help="study: sampling metadata")
    parser.add_argument("--annotators-json", type=Path, help="study: annotator roster")
    parser.add_argument("--annotators", help="study: comma-separated annotator ids (default: active humans)")
    parser.add_argument("--annotator", default="synthetic_rater_1", help="pilot: the annotator to analyse")
    parser.add_argument("--cohort", type=Path,
                        help="pilot: the pilot cohort (patients.json, or a JSON list of case ids); only these "
                             "annotation records are analysed")
    parser.add_argument("--exclude-cc", action="append", default=[], metavar="CHIEF")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--quiet", action="store_true", help="suppress the pipeline's console report")
    args = resolve(parser.parse_args())
    with contextlib.redirect_stdout(open(os.devnull, "w")) if args.quiet else contextlib.nullcontext():
        out = run(args)
    print(f"[run_ddx_analysis] outputs in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
