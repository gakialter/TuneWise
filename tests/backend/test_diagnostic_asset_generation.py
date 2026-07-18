from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.generate_diagnostic_assets import generate


def file_hashes(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_fixed_training_inputs_and_seed_generate_identical_runtime_artifacts(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_manifest = generate(first, seed=20260718)
    second_manifest = generate(second, seed=20260718)

    assert first_manifest == second_manifest
    assert file_hashes(first) == file_hashes(second)
    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["class_order"] == [
        "PLANE_TILT",
        "XY_DECENTER",
        "PLATFORM_INSTABILITY",
        "REFERENCE_DRIFT",
        "Z_DEFOCUS_CONDITIONAL",
    ]
    assert manifest["random_seed"] == 20260718
    assert manifest["feature_definition_version"] == "tw-feature-definition-v1"
    assert manifest["model_fingerprint"] == first_manifest["model_fingerprint"]
    assert manifest["source_assets"] == {
        "training": {
            "partition": "diagnostic-dev-train-v1",
            "batch_count": 60,
            "random_seed": 20260819,
            "batch_id_manifest_hash": manifest["source_assets"]["training"]["batch_id_manifest_hash"],
            "observations_hash": manifest["source_assets"]["training"]["observations_hash"],
            "labels_hash": manifest["source_assets"]["training"]["labels_hash"],
            "partition_manifest_hash": manifest["source_assets"]["training"]["partition_manifest_hash"],
        },
        "validation": {
            "partition": "diagnostic-dev-validation-v1",
            "batch_count": 20,
            "random_seed": 20260920,
            "batch_id_manifest_hash": manifest["source_assets"]["validation"]["batch_id_manifest_hash"],
            "observations_hash": manifest["source_assets"]["validation"]["observations_hash"],
            "labels_hash": manifest["source_assets"]["validation"]["labels_hash"],
            "partition_manifest_hash": manifest["source_assets"]["validation"]["partition_manifest_hash"],
        },
    }
    assert (
        manifest["source_assets"]["training"]["random_seed"]
        != manifest["source_assets"]["validation"]["random_seed"]
    )
    assert all(
        len(source[key]) == 64
        for source in manifest["source_assets"].values()
        for key in (
            "batch_id_manifest_hash",
            "observations_hash",
            "labels_hash",
            "partition_manifest_hash",
        )
    )
    assert not any("label" in path.name.lower() for path in first.rglob("*"))
    assert set(manifest["files"]) == {
        "class-order.json",
        "evidence-rules.json",
        "feature-definition.json",
        "model.json",
        "preprocessing.json",
    }
    definition = json.loads(
        (first / "feature-definition.json").read_text(encoding="utf-8")
    )
    features = definition["features"]
    assert [item["feature_index"] for item in features] == list(range(50))
    assert {item["calculation_version"] for item in features} == {
        "tw-batch-feature-calculation-v1"
    }
    assert {item["missing_value_policy"] for item in features} == {"REJECT_BATCH"}
    by_name = {item["feature_name"]: item for item in features}
    assert by_name["corner_mtf_min"]["allowed_source_fields"] == [
        "mtf_lt",
        "mtf_rt",
        "mtf_lb",
        "mtf_rb",
    ]
    assert by_name["center_corner_gap"]["allowed_source_fields"] == [
        "mtf_center",
        "mtf_lt",
        "mtf_rt",
        "mtf_lb",
        "mtf_rb",
    ]


def test_checked_in_runtime_assets_match_the_generator_and_embedded_root_hash(tmp_path):
    generated = tmp_path / "generated"
    generate(generated, seed=20260718)
    repository_assets = (
        Path(__file__).parents[2]
        / "assets"
        / "diagnostic"
        / "tw-diagnostic-v1"
    )

    assert file_hashes(generated) == file_hashes(repository_assets)
