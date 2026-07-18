from __future__ import annotations

import hashlib
import json

import pytest

from tools.generate_diagnostic_assets import canonical_bytes, generate
from tunewise.diagnosis import DiagnosticAssetError, DiagnosticAssetLoader


def trust_mutated_asset(root, name, mutate):
    asset_path = root / name
    payload = json.loads(asset_path.read_text(encoding="utf-8"))
    mutate(payload)
    asset_path.write_bytes(canonical_bytes(payload))
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    asset_hash = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    manifest["files"][name] = asset_hash
    if name == "model.json":
        manifest["model_fingerprint"] = asset_hash
    manifest_path.write_bytes(canonical_bytes(manifest))
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def test_normalized_model_fingerprint_is_verified_independently_of_manifest_root(tmp_path):
    root = tmp_path / "diagnostic"
    generate(root, 20260718)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["model_fingerprint"] = "0" * 64
    manifest_path.write_bytes(canonical_bytes(manifest))
    trusted_manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    with pytest.raises(DiagnosticAssetError) as error:
        DiagnosticAssetLoader(root, trusted_manifest_hash).load()

    assert error.value.code == "DIAGNOSTIC_MODEL_FINGERPRINT_MISMATCH"


@pytest.mark.parametrize(
    ("asset_name", "mutate", "expected_code"),
    [
        (
            "preprocessing.json",
            lambda payload: payload["mean"].pop(),
            "DIAGNOSTIC_PREPROCESSING_INVALID",
        ),
        (
            "preprocessing.json",
            lambda payload: payload["scale"].__setitem__(0, 0.0),
            "DIAGNOSTIC_PREPROCESSING_INVALID",
        ),
        (
            "model.json",
            lambda payload: payload["coefficient"][0].__setitem__(0, float("nan")),
            "DIAGNOSTIC_MODEL_INVALID",
        ),
        (
            "evidence-rules.json",
            lambda payload: payload.__setitem__("top1_score_minimum", "NaN"),
            "DIAGNOSTIC_EVIDENCE_RULE_INVALID",
        ),
    ],
)
def test_trusted_but_malformed_numeric_assets_are_rejected_before_inference(
    tmp_path, asset_name, mutate, expected_code
):
    root = tmp_path / "diagnostic"
    generate(root, 20260718)
    trusted_manifest_hash = trust_mutated_asset(root, asset_name, mutate)

    with pytest.raises(DiagnosticAssetError) as error:
        DiagnosticAssetLoader(root, trusted_manifest_hash).load()

    assert error.value.code == expected_code
