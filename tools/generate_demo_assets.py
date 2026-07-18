from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

from tunewise.importing import OBSERVABLE_FIELDS, ObservableCanonicalizer


VERSIONS = {
    "canonicalizer_version": "tw-canonicalizer-v1",
    "dataset_version": "tw-dataset-v1",
    "evaluation_rule_version": "tw-evaluation-v1",
    "generator_version": "tw-generator-v1",
    "model_version": "tw-model-v1",
    "preprocessing_version": "tw-preprocessing-v1",
    "rule_set_version": "tw-rules-v1",
    "schema_version": "tw-schema-v1",
}
SCENARIO_REF = "scn_c9b8a8d6bd33f72e893f33da85dfeb8e"


def deterministic_noise(seed: int, sample_index: int, field: str) -> Decimal:
    digest = hashlib.sha256(f"{seed}:{sample_index}:{field}".encode("ascii")).digest()
    integer = int.from_bytes(digest[:8], "big")
    return (Decimal(integer) / Decimal(2**64 - 1)) * 2 - 1


def fixed(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), "f")


def build_rows(seed: int) -> list[list[str]]:
    started_at = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)
    rows: list[list[str]] = []
    baselines = {
        "vibration_rms": Decimal("0.018"),
        "repeat_position_error": Decimal("0.014"),
        "calibration_residual_x": Decimal("0.006"),
        "calibration_residual_y": Decimal("-0.004"),
        "mtf_center": Decimal("0.832"),
        "mtf_lt": Decimal("0.714"),
        "mtf_rt": Decimal("0.752"),
        "mtf_lb": Decimal("0.634"),
        "mtf_rb": Decimal("0.568"),
    }
    amplitudes = {
        "vibration_rms": Decimal("0.002"),
        "repeat_position_error": Decimal("0.0015"),
        "calibration_residual_x": Decimal("0.001"),
        "calibration_residual_y": Decimal("0.001"),
        "mtf_center": Decimal("0.003"),
        "mtf_lt": Decimal("0.004"),
        "mtf_rt": Decimal("0.004"),
        "mtf_lb": Decimal("0.004"),
        "mtf_rb": Decimal("0.004"),
    }
    for sample_index in range(24):
        row = {
            "sample_index": str(sample_index),
            "timestamp": (started_at + timedelta(seconds=sample_index))
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "x_offset": "0.100000",
            "y_offset": "-0.050000",
            "pitch": "0.250000",
            "roll": "-0.200000",
            "z_offset": "0.000000",
        }
        for field, baseline in baselines.items():
            row[field] = fixed(
                baseline + amplitudes[field] * deterministic_noise(seed, sample_index, field)
            )
        rows.append([row[field] for field in OBSERVABLE_FIELDS])
    return rows


def build_import_rules() -> dict:
    constraints = {}
    for field in ("x_offset", "y_offset", "pitch", "roll", "z_offset"):
        constraints[field] = {
            "nominal_value": "0.000000",
            "minimum": "-1.000000",
            "maximum": "1.000000",
            "step": "0.050000",
            "maximum_single_plan_delta": "0.100000" if field == "z_offset" else "0.200000",
        }
    return {
        "control_limits": {
            "snapshot_version": "tw-control-limits-v1",
            "rule_set_version": VERSIONS["rule_set_version"],
            "center_lower_limit": "0.720000",
            "corner_lower_limit": "0.620000",
            "asymmetry_limit": "0.120000",
            "corner_std_limit": "0.050000",
        },
        "parameter_constraints": {
            "snapshot_version": "tw-parameter-constraints-v1",
            "product_model": "TW-AA-PROTOTYPE-V1",
            "rule_set_version": VERSIONS["rule_set_version"],
            "constraints": constraints,
        },
        "replay_evaluation_rules": {
            "snapshot_version": VERSIONS["evaluation_rule_version"],
            "evaluation_rule_version": VERSIONS["evaluation_rule_version"],
            "center_regression_tolerance": "0.010000",
            "minimum_corner_min_improvement": "0.020000",
            "minimum_range_reduction": "0.020000",
            "minimum_std_reduction": "0.010000",
            "center_lower_limit": "0.720000",
            "corner_lower_limit": "0.620000",
            "asymmetry_limit": "0.120000",
        },
    }


def generate(output: Path, seed: int) -> None:
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "aa-demo-batch.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(OBSERVABLE_FIELDS)
        writer.writerows(build_rows(seed))
    csv_bytes = csv_path.read_bytes()
    canonical = ObservableCanonicalizer().canonicalize_csv(csv_bytes)
    rules_path = output / "import-rules.json"
    rules_path.write_text(
        json.dumps(build_import_rules(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    rules_bytes = rules_path.read_bytes()
    manifest = {
        "manifest_version": "1",
        "asset_id": "tw-aa-demo-v1",
        "station_id": "AA",
        "batch_id": "tw-aa-demo-batch-001",
        "product_model": "TW-AA-PROTOTYPE-V1",
        "csv_file": csv_path.name,
        "rules_file": rules_path.name,
        "random_seed": seed,
        "versions": VERSIONS,
        "raw_file_hash": hashlib.sha256(csv_bytes).hexdigest(),
        "rules_file_hash": hashlib.sha256(rules_bytes).hexdigest(),
        "canonical_observation_hash": canonical.sha256,
        "scenario_ref": SCENARIO_REF,
        "scenario_ref_hash": hashlib.sha256(SCENARIO_REF.encode("utf-8")).hexdigest(),
    }
    (output / "dataset-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 TuneWise 版本化 AA 演示资产。")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260718)
    arguments = parser.parse_args()
    generate(arguments.output, arguments.seed)


if __name__ == "__main__":
    main()
