from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tunewise.importing import OBSERVABLE_FIELDS, ObservableCanonicalizer
from tunewise.simulator_gateway import LocalSimulatorGateway, SimulationRequest
from tools.generate_replay_assets import generate


SCENARIO_REF = "scn_c9b8a8d6bd33f72e893f33da85dfeb8e"
SCENARIO_REF_HASH = "5c210f78b07a053aebb4ddf1875f1d975d5725e9c9bf028aecedc6677796808a"


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _request(manifest: dict, *, pitch: str = "0.250000") -> SimulationRequest:
    return SimulationRequest(
        scenario_ref=SCENARIO_REF,
        scenario_ref_hash=SCENARIO_REF_HASH,
        simulator_version=manifest["simulator_version"],
        replay_scenario_schema_version=manifest["replay_scenario_schema_version"],
        scenario_mapping_version=manifest["scenario_mapping_version"],
        sample_count=24,
        seed=20260718,
        disturbance_sequence_hash=manifest["disturbance_sequence_hash"],
        parameters={
            "x_offset": "0.100000",
            "y_offset": "-0.050000",
            "pitch": pitch,
            "roll": "-0.200000",
            "z_offset": "0.000000",
        },
    )


def test_replay_asset_generation_is_byte_deterministic_and_matches_checked_in_assets(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_manifest = generate(first)
    second_manifest = generate(second)

    assert _file_bytes(first) == _file_bytes(second)
    assert _file_bytes(first) == _file_bytes(
        Path("assets/simulator-private/tw-replay-simulator-v1")
    )
    assert first_manifest == second_manifest
    assert first_manifest["simulator_version"] == "tw-simulator-v1"
    assert first_manifest["replay_scenario_schema_version"] == "tw-replay-scenario-v1"
    assert first_manifest["scenario_mapping_version"] == "tw-scenario-mapping-v1"
    assert first_manifest["fixed_seed"] == 20260718
    assert first_manifest["scenario_ref_hash"] == SCENARIO_REF_HASH
    assert len(first_manifest["hidden_scenario_content_hash"]) == 64
    assert len(first_manifest["disturbance_sequence_hash"]) == 64
    assert len(first_manifest["canonical_manifest_hash"]) == 64


def test_gateway_reproduces_imported_baseline_and_returns_only_frozen_observations(
    tmp_path: Path,
) -> None:
    root = tmp_path / "replay-assets"
    manifest = generate(root)
    gateway = LocalSimulatorGateway(root, manifest["canonical_manifest_hash"])

    run = gateway.run(_request(manifest))

    assert len(run.measurements) == 24
    assert all(tuple(row) == OBSERVABLE_FIELDS for row in run.measurements)
    serialized = json.dumps(run.measurements, ensure_ascii=False)
    for forbidden in (
        "FaultTruth",
        "primary_fault_truth",
        "coefficient",
        "local_focus_error",
        "nuisance",
        SCENARIO_REF,
    ):
        assert forbidden not in serialized

    csv_lines = [",".join(OBSERVABLE_FIELDS)]
    csv_lines.extend(",".join(row[field] for field in OBSERVABLE_FIELDS) for row in run.measurements)
    canonical = ObservableCanonicalizer().canonicalize_csv(
        ("\n".join(csv_lines) + "\n").encode("utf-8")
    )
    assert canonical.sha256 == "c74206387e06287d6c11ee8a4c6cc46cae867e6967f0c790f5dfe2f5ef940668"
    assert run.binding.scenario_ref_hash == SCENARIO_REF_HASH
    assert run.binding.disturbance_sequence_hash == manifest["disturbance_sequence_hash"]
    assert run.binding.sample_count == 24


def test_same_version_seed_and_parameters_produce_identical_measurements_ten_times(
    tmp_path: Path,
) -> None:
    root = tmp_path / "replay-assets"
    manifest = generate(root)
    gateway = LocalSimulatorGateway(root, manifest["canonical_manifest_hash"])

    runs = tuple(gateway.run(_request(manifest)) for _ in range(10))

    assert all(run == runs[0] for run in runs[1:])
    assert gateway.call_count == 10


def test_intervention_changes_only_authoritative_parameters_under_same_pairing_binding(
    tmp_path: Path,
) -> None:
    root = tmp_path / "replay-assets"
    manifest = generate(root)
    gateway = LocalSimulatorGateway(root, manifest["canonical_manifest_hash"])

    before = gateway.run(_request(manifest))
    after = gateway.run(_request(manifest, pitch="0.200000"))

    assert before.binding == after.binding
    assert before.measurements != after.measurements
    assert {row["pitch"] for row in before.measurements} == {"0.250000"}
    assert {row["pitch"] for row in after.measurements} == {"0.200000"}
    for before_row, after_row in zip(before.measurements, after.measurements, strict=True):
        assert before_row["sample_index"] == after_row["sample_index"]
        assert before_row["timestamp"] == after_row["timestamp"]
        for field in (
            "vibration_rms",
            "repeat_position_error",
            "calibration_residual_x",
            "calibration_residual_y",
        ):
            assert before_row[field] == after_row[field]


def test_scenario_reference_is_opaque_and_not_a_seed_or_filename_derivative(tmp_path: Path) -> None:
    manifest = generate(tmp_path / "replay-assets")

    assert hashlib.sha256(SCENARIO_REF.encode("utf-8")).hexdigest() == SCENARIO_REF_HASH
    assert str(manifest["fixed_seed"]) not in SCENARIO_REF
    assert manifest["scenario_asset_file"] not in SCENARIO_REF
