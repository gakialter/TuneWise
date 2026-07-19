from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tunewise.importing import OBSERVABLE_FIELDS
from tunewise.simulator_gateway import canonical_json_bytes, canonical_manifest_hash


SCENARIO_REF = "scn_c9b8a8d6bd33f72e893f33da85dfeb8e"
SIMULATOR_VERSION = "tw-simulator-v1"
SCENARIO_SCHEMA_VERSION = "tw-replay-scenario-v1"
SCENARIO_MAPPING_VERSION = "tw-scenario-mapping-v1"
FIXED_SEED = 20260718
NOISE_FIELDS = (
    "vibration_rms",
    "repeat_position_error",
    "calibration_residual_x",
    "calibration_residual_y",
    "mtf_center",
    "mtf_lt",
    "mtf_rt",
    "mtf_lb",
    "mtf_rb",
)


def _write(path: Path, payload: object) -> bytes:
    content = canonical_json_bytes(payload) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def _noise(sample_index: int, field: str) -> str:
    digest = hashlib.sha256(f"{FIXED_SEED}:{sample_index}:{field}".encode("ascii")).digest()
    integer = int.from_bytes(digest[:8], "big")
    from decimal import Decimal

    value = (Decimal(integer) / Decimal(2**64 - 1)) * 2 - 1
    return format(value, "f")


def generate(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    scenario_file = "scenarios/scn-c9b8a8d6bd33f72e893f33da85dfeb8e.json"
    disturbance_file = "disturbance-sequence.json"
    mapping_file = "scenario-mapping.json"
    policy_file = "simulator-policy.json"
    scenario = {
        "replay_scenario_schema_version": SCENARIO_SCHEMA_VERSION,
        "primary_fault_truth": "PLANE_TILT",
        "nuisance_disturbance": "FIXED_HASH_DERIVED_NOISE",
        "start_timestamp": "2026-07-18T00:00:00Z",
        "baseline_parameters": {
            "x_offset": "0.100000",
            "y_offset": "-0.050000",
            "pitch": "0.250000",
            "roll": "-0.200000",
            "z_offset": "0.000000",
        },
        "observable_baselines": {
            "vibration_rms": "0.018000",
            "repeat_position_error": "0.014000",
            "calibration_residual_x": "0.006000",
            "calibration_residual_y": "-0.004000",
            "mtf_center": "0.832000",
            "mtf_lt": "0.714000",
            "mtf_rt": "0.752000",
            "mtf_lb": "0.634000",
            "mtf_rb": "0.568000",
        },
        "noise_amplitudes": {
            "vibration_rms": "0.002000",
            "repeat_position_error": "0.001500",
            "calibration_residual_x": "0.001000",
            "calibration_residual_y": "0.001000",
            "mtf_center": "0.003000",
            "mtf_lt": "0.004000",
            "mtf_rt": "0.004000",
            "mtf_lb": "0.004000",
            "mtf_rb": "0.004000",
        },
        "causal_coefficients": {
            "center_tilt_penalty": "0.050000",
            "center_decenter_penalty": "0.020000",
            "center_z_penalty": "0.200000",
            "corner_focus_penalties": {
                "mtf_lt": "0.200000",
                "mtf_rt": "0.500000",
                "mtf_lb": "7.000000",
                "mtf_rb": "2.200000",
            },
            "corner_decenter_penalty": "0.100000",
        },
    }
    disturbance = {
        "disturbance_sequence_version": "tw-disturbance-sequence-v1",
        "fixed_seed": FIXED_SEED,
        "records": [
            {
                "sample_index": sample_index,
                "noise": {
                    field: _noise(sample_index, field) for field in NOISE_FIELDS
                },
            }
            for sample_index in range(24)
        ],
    }
    mapping = {
        "scenario_mapping_version": SCENARIO_MAPPING_VERSION,
        "mappings": [
            {
                "scenario_ref": SCENARIO_REF,
                "scenario_ref_hash": hashlib.sha256(SCENARIO_REF.encode("utf-8")).hexdigest(),
                "scenario_asset_file": scenario_file,
            }
        ],
    }
    policy = {
        "simulator_version": SIMULATOR_VERSION,
        "network": "none",
        "real_device_interface": "none",
        "observable_fields": list(OBSERVABLE_FIELDS),
        "parameter_fields": ["x_offset", "y_offset", "pitch", "roll", "z_offset"],
        "numeric_precision": "0.000001",
        "paired_input_invariant": "ONLY_CONFIRMED_PLAN_PARAMETERS_MAY_CHANGE",
    }
    payloads = {
        scenario_file: scenario,
        disturbance_file: disturbance,
        mapping_file: mapping,
        policy_file: policy,
    }
    files = {
        relative_path: hashlib.sha256(_write(output / relative_path, payload)).hexdigest()
        for relative_path, payload in payloads.items()
    }
    manifest = {
        "manifest_version": "1",
        "simulator_version": SIMULATOR_VERSION,
        "replay_scenario_schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_mapping_version": SCENARIO_MAPPING_VERSION,
        "fixed_seed": FIXED_SEED,
        "scenario_ref_hash": hashlib.sha256(SCENARIO_REF.encode("utf-8")).hexdigest(),
        "scenario_asset_file": scenario_file,
        "hidden_scenario_content_hash": files[scenario_file],
        "disturbance_sequence_file": disturbance_file,
        "disturbance_sequence_hash": files[disturbance_file],
        "scenario_mapping_file": mapping_file,
        "simulator_policy_file": policy_file,
        "simulator_policy_hash": files[policy_file],
        "files": dict(sorted(files.items())),
        "dependency_summary": {
            "implementation": "python-standard-library",
            "network": "none",
            "serialization": "canonical-json-v1",
        },
    }
    manifest["canonical_manifest_hash"] = canonical_manifest_hash(manifest)
    _write(output / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 TuneWise 确定性配对回放私有资产。")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    generate(arguments.output)


if __name__ == "__main__":
    main()
