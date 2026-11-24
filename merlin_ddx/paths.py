from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = PROJECT_ROOT / "data"


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @property
    def source_dir(self) -> Path:
        return self.root / "source"

    @property
    def processed_dir(self) -> Path:
        return self.root / "processed"

    @property
    def reference_dir(self) -> Path:
        return self.root / "reference"

    @property
    def app_dir(self) -> Path:
        return self.root / "app"

    @property
    def annotations_dir(self) -> Path:
        return self.root / "annotations"

    @property
    def combined(self) -> Path:
        return self.source_dir / "combined.pq"

    @property
    def combined_fixed(self) -> Path:
        return self.source_dir / "combined_fixed.pq"

    @property
    def instructions(self) -> Path:
        return self.source_dir / "instructions.pq"

    @property
    def combined_fixed_json(self) -> Path:
        return self.processed_dir / "combined_fixed_json.pq"

    @property
    def instructions_fixed_json(self) -> Path:
        return self.processed_dir / "instructions_fixed_json.pq"

    @property
    def combined_frontier_llms(self) -> Path:
        return self.processed_dir / "combined_frontier_llms.pq"

    @property
    def patients_json(self) -> Path:
        return self.app_dir / "patients.json"

    @property
    def metrics_json(self) -> Path:
        return self.app_dir / "metrics.json"

    @property
    def model_reasoning_json(self) -> Path:
        return self.app_dir / "model_reasoning.json"

    @property
    def annotators_json(self) -> Path:
        return self.app_dir / "annotators.json"

    @property
    def annotation_overlays_json(self) -> Path:
        return self.app_dir / "annotation_overlays.json"

    @property
    def custom_diagnoses_dir(self) -> Path:
        return self.root / "custom_diagnoses"

    @property
    def medical_schemes_dir(self) -> Path:
        return self.reference_dir / "medical_schemes"

    @property
    def diagnosis_schema_dir(self) -> Path:
        return self.medical_schemes_dir / "diagnoses"

    @property
    def mimic_iv_dir(self) -> Path:
        return self.reference_dir / "mimic-iv"

    @property
    def icd_codes_10(self) -> Path:
        return self.mimic_iv_dir / "icd_codes_10.csv"


def data_paths(data_root: Path | str | None = None) -> DataPaths:
    root = Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT
    return DataPaths(root.resolve())
