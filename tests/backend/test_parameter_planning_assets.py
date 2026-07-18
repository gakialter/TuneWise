from __future__ import annotations

import hashlib
import json

import pytest

from tools.generate_parameter_planning_assets import generate
from tunewise.parameter_planning import ParameterPlanningAssetError, ParameterPlanningAssetLoader


def test_planning_assets_are_deterministic_versioned_and_offline(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_manifest = generate(first)
    second_manifest = generate(second)

    assert first_manifest == second_manifest
    assert first_manifest["direction_rule_version"] == "tw-direction-rules-v1"
    assert first_manifest["safety_rule_version"] == "tw-parameter-safety-v1"
    assert first_manifest["planning_rule_version"] == "tw-parameter-planning-v1"
    assert first_manifest["dependency_summary"] == {
        "implementation": "python-standard-library",
        "network": "none",
        "serialization": "canonical-json-v1",
    }
    expected_hash = hashlib.sha256((first / "manifest.json").read_bytes()).hexdigest()
    loaded = ParameterPlanningAssetLoader(first, expected_hash).load()
    assert loaded.direction_rules.direction_rule_version == "tw-direction-rules-v1"
    assert loaded.safety_policy.maximum_adjusted_parameter_count == 2
    assert loaded.safety_policy.family_for_root_cause("PLANE_TILT") == "PITCH_ROLL"
    assert loaded.planning_policy.ticks_for("CONSERVATIVE") == 1
    assert loaded.planning_policy.ticks_for("STANDARD") == 2
    assert loaded.manifest_hash == expected_hash


def test_planning_asset_loader_rejects_rule_tampering(tmp_path) -> None:
    root = tmp_path / "planning"
    generate(root)
    expected_hash = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    path = root / "direction-rules.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["minimum_spatial_support"] = "0.000000"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ParameterPlanningAssetError) as captured:
        ParameterPlanningAssetLoader(root, expected_hash).load()

    assert captured.value.code == "PLANNING_ASSET_HASH_MISMATCH"
