from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from tools.generate_demo_assets import generate
from tunewise.importing import ObservableCanonicalizer


def run_generator(output: Path) -> dict:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[2] / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.generate_demo_assets",
            "--output",
            str(output),
            "--seed",
            "20260718",
        ],
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads((output / "dataset-manifest.json").read_text(encoding="utf-8"))


def test_fixed_seed_generation_is_byte_and_canonical_hash_deterministic(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_manifest = run_generator(first)
    second_manifest = run_generator(second)

    assert (first / "aa-demo-batch.csv").read_bytes() == (
        second / "aa-demo-batch.csv"
    ).read_bytes()
    assert first_manifest == second_manifest
    assert first_manifest["random_seed"] == 20260718
    assert first_manifest["versions"] == {
        "canonicalizer_version": "tw-canonicalizer-v1",
        "dataset_version": "tw-dataset-v1",
        "evaluation_rule_version": "tw-evaluation-v1",
        "generator_version": "tw-generator-v1",
        "model_version": "tw-model-v1",
        "preprocessing_version": "tw-preprocessing-v1",
        "rule_set_version": "tw-rules-v1",
        "schema_version": "tw-schema-v1",
    }
    csv_bytes = (first / "aa-demo-batch.csv").read_bytes()
    assert first_manifest["raw_file_hash"] == hashlib.sha256(csv_bytes).hexdigest()
    assert first_manifest["canonical_observation_hash"]
    assert first_manifest["scenario_ref_hash"] == hashlib.sha256(
        first_manifest["scenario_ref"].encode("utf-8")
    ).hexdigest()
    rules_bytes = (first / "import-rules.json").read_bytes()
    assert first_manifest["rules_file"] == "import-rules.json"
    assert first_manifest["rules_file_hash"] == hashlib.sha256(rules_bytes).hexdigest()
    assert not {
        "FaultTruth",
        "fault_truth",
        "root_cause",
        "primary_fault_truth",
        "hidden_parameters",
        "simulator_coefficients",
    } & set(csv_bytes.decode("utf-8"))


def test_opaque_scenario_reference_is_not_derived_from_public_random_seed(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_manifest = run_generator(first)
    generate(second, 20260719)
    second_manifest = json.loads(
        (second / "dataset-manifest.json").read_text(encoding="utf-8")
    )

    assert first_manifest["raw_file_hash"] != second_manifest["raw_file_hash"]
    assert first_manifest["scenario_ref"] == second_manifest["scenario_ref"]
    assert first_manifest["scenario_ref"].startswith("scn_")


def test_canonical_observation_hash_ignores_line_endings_and_record_order(tmp_path):
    output = tmp_path / "asset"
    run_generator(output)
    original = (output / "aa-demo-batch.csv").read_bytes()
    lines = original.decode("utf-8").splitlines()
    reordered_lf = ("\n".join([lines[0], *reversed(lines[1:])]) + "\n").encode()
    reordered_crlf = reordered_lf.replace(b"\n", b"\r\n")

    canonicalizer = ObservableCanonicalizer()
    original_result = canonicalizer.canonicalize_csv(original)
    lf_result = canonicalizer.canonicalize_csv(reordered_lf)
    crlf_result = canonicalizer.canonicalize_csv(reordered_crlf)

    assert original_result.sha256 == lf_result.sha256 == crlf_result.sha256
    assert original_result.content == lf_result.content == crlf_result.content
    assert hashlib.sha256(reordered_lf).hexdigest() != hashlib.sha256(
        reordered_crlf
    ).hexdigest()
    assert hashlib.sha256(original).hexdigest() != hashlib.sha256(
        reordered_lf
    ).hexdigest()
