#!/usr/bin/env python
"""Run the clinician-audit interface on the synthetic demonstration cases.

    npm ci && npm run build
    python scripts/run_demo.py                 # http://127.0.0.1:8765
    python scripts/run_demo.py --with-ratings  # preload the synthetic ratings

The synthetic data root is copied to ``.demo/data_root`` (git-ignored) so that
saving answers never modifies the committed examples; ``--reset`` starts over.
No PhysioNet credentials, external services, cluster access or GPU are needed.

The unchanged study backend (``merlin_ddx.sync_api``) serves the built frontend
and stores answers as one JSON record per annotator and admission under
``.demo/data_root/rebuttal_audit_annotations/<annotator>/``.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SYNTHETIC = ROOT / "examples" / "synthetic"


def prepare(data_root: Path, *, reset: bool, with_ratings: bool) -> Path:
    if reset and data_root.exists():
        shutil.rmtree(data_root)
    if not data_root.exists():
        shutil.copytree(SYNTHETIC / "data_root", data_root)
    if with_ratings:
        for rater_dir in sorted((SYNTHETIC / "ratings").iterdir()):
            target = data_root / "rebuttal_audit_annotations" / rater_dir.name
            target.mkdir(parents=True, exist_ok=True)
            for record in rater_dir.glob("*.json"):
                shutil.copy2(record, target / record.name)
    return data_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-root", type=Path, default=ROOT / ".demo" / "data_root",
                        help="working copy of the synthetic data root (created if absent)")
    parser.add_argument("--static-dir", type=Path, default=ROOT / "dist", help="built frontend (npm run build)")
    parser.add_argument("--reset", action="store_true", help="discard saved demo answers first")
    parser.add_argument("--with-ratings", action="store_true", help="preload the synthetic raters' answers")
    args = parser.parse_args()
    if not (args.static_dir / "index.html").is_file():
        parser.error(f"No built frontend in {args.static_dir}; run `npm ci && npm run build` first")
    data_root = prepare(args.data_root.resolve(), reset=args.reset, with_ratings=args.with_ratings)

    import uvicorn
    from merlin_ddx.sync_api import create_app

    app = create_app(data_root=data_root, sync_git=False, static_dir=args.static_dir.resolve())
    print(f"Synthetic clinician-audit demo: http://{args.host}:{args.port}/  (data: {data_root})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
