from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256(payload: object) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def parameter_constraint_snapshot() -> dict:
    constraints = {}
    for name in ("x_offset", "y_offset", "pitch", "roll", "z_offset"):
        constraints[name] = {
            "nominal_value": "0.000000",
            "minimum": "-1.000000",
            "maximum": "1.000000",
            "step": "0.050000",
            "maximum_single_plan_delta": "0.100000" if name == "z_offset" else "0.200000",
        }
    return {
        "snapshot_version": "tw-parameter-constraints-v1",
        "product_model": "TW-AA-PROTOTYPE-V1",
        "rule_set_version": "tw-rules-v1",
        "constraints": constraints,
    }


def generate(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "direction-rules.json": {
            "direction_rule_version": "tw-direction-rules-v1",
            "rule_set_version": "tw-rules-v1",
            "minimum_spatial_support": "0.040000",
            "axis_rules": {
                "pitch": {
                    "root_cause": "PLANE_TILT",
                    "feature_name": "top_bottom_difference",
                    "sign_relation": "SAME_SIGN",
                    "rule_id": "PLANE_TILT_PITCH_SAME_SIGN",
                },
                "roll": {
                    "root_cause": "PLANE_TILT",
                    "feature_name": "left_right_difference",
                    "sign_relation": "OPPOSITE_SIGN",
                    "rule_id": "PLANE_TILT_ROLL_OPPOSITE_SIGN",
                },
                "x_offset": {
                    "root_cause": "XY_DECENTER",
                    "feature_name": "left_right_difference",
                    "sign_relation": "SAME_SIGN",
                    "rule_id": "XY_DECENTER_X_SAME_SIGN",
                },
                "y_offset": {
                    "root_cause": "XY_DECENTER",
                    "feature_name": "top_bottom_difference",
                    "sign_relation": "OPPOSITE_SIGN",
                    "rule_id": "XY_DECENTER_Y_OPPOSITE_SIGN",
                },
            },
            "z_rule": {
                "root_cause": "Z_DEFOCUS_CONDITIONAL",
                "rule_id": "Z_DEFOCUS_GATE_AND_GLOBAL_PATTERN",
                "supporting_features": ["mtf_center_mean", "corner_mtf_mean"],
            },
        },
        "safety-rules.json": {
            "safety_rule_version": "tw-parameter-safety-v1",
            "rule_set_version": "tw-rules-v1",
            "tick_size": "0.050000",
            "maximum_adjusted_parameter_count": 2,
            "parameter_families": {
                "XY_OFFSET": ["x_offset", "y_offset"],
                "PITCH_ROLL": ["pitch", "roll"],
                "Z_OFFSET": ["z_offset"],
            },
            "top1_allowed_families": {
                "PLANE_TILT": "PITCH_ROLL",
                "XY_DECENTER": "XY_OFFSET",
                "Z_DEFOCUS_CONDITIONAL": "Z_OFFSET",
            },
        },
        "planning-rules.json": {
            "planning_rule_version": "tw-parameter-planning-v1",
            "rule_set_version": "tw-rules-v1",
            "generation_ticks": {"CONSERVATIVE": 1, "STANDARD": 2},
            "maximum_candidate_count": 3,
            "sort_order": [
                "total_absolute_delta_ticks:ASC",
                "supporting_case_count:DESC",
                "candidate_id:ASC",
            ],
            "case_action_version": "tw-approved-case-action-v1",
        },
    }
    files = {}
    for name, payload in artifacts.items():
        content = canonical_bytes(payload)
        (output / name).write_bytes(content)
        files[name] = hashlib.sha256(content).hexdigest()
    manifest = {
        "manifest_version": "1",
        "asset_version": "tw-parameter-planning-assets-v1",
        "direction_rule_version": "tw-direction-rules-v1",
        "safety_rule_version": "tw-parameter-safety-v1",
        "planning_rule_version": "tw-parameter-planning-v1",
        "planning_result_version": "tw-parameter-planning-result-v1",
        "rule_set_version": "tw-rules-v1",
        "feature_definition_version": "tw-feature-definition-v1",
        "expected_parameter_constraint_snapshot_hash": _sha256(
            parameter_constraint_snapshot()
        ),
        "dependency_summary": {
            "implementation": "python-standard-library",
            "network": "none",
            "serialization": "canonical-json-v1",
        },
        "files": files,
    }
    (output / "manifest.json").write_bytes(canonical_bytes(manifest))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 TuneWise TW-06 参数规划规则资产。")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    manifest = generate(arguments.output)
    sys.stdout.write(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
