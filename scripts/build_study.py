#!/usr/bin/env python3
"""Build a study from an explicit JSON configuration and freeze input hashes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_annotation_cases import build as paired
from build_single_reasoning_cases import build as single
from build_reference_cases import build as reference
from build_label_comparison_cases import build as comparison
from build_ddx_cases import build as ddx
from export_annotations import read_json
from merlin_ddx.annotation_store import write_json_atomic

BUILDERS = {"paired_reasoning": paired, "single_reasoning": single,
            "reference_label": reference, "label_comparison": comparison, "ddx": ddx}
RUBRIC = "baseline-v1.2"


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ("app", "source") for p in sorted((root / folder).rglob("*"))
            if p.is_file() and p.name != "annotation_overlays.json"}


def freeze(study):
    study = Path(study)
    path = study / "private_analysis" / "manifest.json"
    manifest = read_json(path)
    fingerprint = hashes(study / "annotation_inputs")
    keys = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((study / "private_analysis").glob("*key*.json"))}
    if len(keys) != 1:
        raise ValueError("Expected exactly one private study allocation key")
    if "input_hashes" in manifest:
        if manifest["input_hashes"] != fingerprint or manifest.get("key_hashes") != keys:
            raise ValueError("Prepared inputs changed after freezing")
        return manifest
    manifest.update(rubric_version=RUBRIC, input_hashes=fingerprint, key_hashes=keys, manifest_version=1)
    write_json_atomic(path, manifest)
    return manifest


def build(config, out):
    config = dict(config)
    mode = config.pop("study_type")
    if mode not in BUILDERS:
        raise ValueError("Unknown study type")
    if config.pop("rubric_version", RUBRIC) != RUBRIC:
        raise ValueError("Experimental rubric configuration is not supported by this release")
    BUILDERS[mode](out=out, **config)
    return freeze(out)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--verify", action="store_true")
    a = p.parse_args()
    if a.verify:
        if a.config or "input_hashes" not in read_json(a.out / "private_analysis" / "manifest.json"):
            p.error("Verification requires an already frozen study")
        result = freeze(a.out)
    else:
        if not a.config:
            p.error("--config is required to build")
        result = build(read_json(a.config), a.out)
    print(f"{result['study_type']}: frozen study inputs verified.")


if __name__ == "__main__":
    main()
