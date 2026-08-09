from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

from tunewise.diagnostic_contract import (
    CLASS_ORDER,
    EVIDENCE_RULE_VERSION,
    FEATURE_DEFINITION_VERSION,
    FEATURE_NAMES,
    MODEL_VERSION,
    PREPROCESSING_VERSION,
    feature_definition,
)


TRAINING_SEED_OFFSET = 101
VALIDATION_SEED_OFFSET = 202


def canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def deterministic_noise(seed: int, partition: str, label: str, row: int, feature: str) -> float:
    digest = hashlib.sha256(
        f"{seed}:{partition}:{label}:{row}:{feature}".encode("ascii")
    ).digest()
    return (int.from_bytes(digest[:8], "big") / (2**64 - 1)) * 2.0 - 1.0


def _base_features(label: str) -> dict[str, float]:
    values = {name: 0.0 for name in FEATURE_NAMES}
    mtf = {
        "PLANE_TILT": (0.83, 0.72, 0.75, 0.63, 0.57),
        "XY_DECENTER": (0.82, 0.56, 0.73, 0.58, 0.75),
        "PLATFORM_INSTABILITY": (0.79, 0.66, 0.68, 0.65, 0.67),
        "REFERENCE_DRIFT": (0.80, 0.64, 0.67, 0.65, 0.68),
        "Z_DEFOCUS_CONDITIONAL": (0.69, 0.585, 0.595, 0.580, 0.590),
    }[label]
    for field, mean in zip(("mtf_center", "mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb"), mtf):
        values[f"{field}_mean"] = mean
        values[f"{field}_std"] = 0.006
        values[f"{field}_trend"] = 0.0
    corners = mtf[1:]
    corner_mean = sum(corners) / 4
    corner_std = math.sqrt(sum((value - corner_mean) ** 2 for value in corners) / 4)
    values.update(
        {
            "corner_mtf_mean": corner_mean,
            "corner_mtf_min": min(corners),
            "corner_mtf_range": max(corners) - min(corners),
            "corner_mtf_std": corner_std,
            "left_right_difference": ((corners[0] + corners[2]) - (corners[1] + corners[3])) / 2,
            "top_bottom_difference": ((corners[0] + corners[1]) - (corners[2] + corners[3])) / 2,
            "diagonal_difference": ((corners[0] + corners[3]) - (corners[1] + corners[2])) / 2,
            "center_corner_gap": mtf[0] - corner_mean,
        }
    )
    for field in ("x_offset", "y_offset", "pitch", "roll", "z_offset"):
        values[f"{field}_std"] = 0.001
    for field in ("vibration_rms", "repeat_position_error", "calibration_residual_x", "calibration_residual_y"):
        values[f"{field}_mean"] = 0.008
        values[f"{field}_std"] = 0.002
        values[f"{field}_trend"] = 0.0
    if label == "PLANE_TILT":
        values.update({"pitch_mean": 0.24, "roll_mean": -0.20})
    elif label == "XY_DECENTER":
        values.update({"x_offset_mean": 0.30, "y_offset_mean": -0.24})
    elif label == "PLATFORM_INSTABILITY":
        values.update(
            {
                "vibration_rms_mean": 0.085,
                "vibration_rms_std": 0.026,
                "vibration_rms_trend": 0.004,
                "repeat_position_error_mean": 0.068,
                "repeat_position_error_std": 0.021,
                "repeat_position_error_trend": 0.003,
            }
        )
        for field in ("mtf_center", "mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb"):
            values[f"{field}_std"] = 0.035
    elif label == "REFERENCE_DRIFT":
        values.update(
            {
                "calibration_residual_x_mean": 0.115,
                "calibration_residual_x_std": 0.009,
                "calibration_residual_x_trend": 0.007,
                "calibration_residual_y_mean": -0.095,
                "calibration_residual_y_std": 0.008,
                "calibration_residual_y_trend": -0.006,
            }
        )
    elif label == "Z_DEFOCUS_CONDITIONAL":
        values["z_offset_mean"] = 0.28
    return values


def build_partition(seed: int, partition: str, rows_per_class: int) -> tuple[list[list[float]], list[str]]:
    observations: list[list[float]] = []
    labels: list[str] = []
    amplitude = 0.012 if partition == "TRAIN" else 0.016
    for label in CLASS_ORDER:
        base = _base_features(label)
        for row in range(rows_per_class):
            observations.append(
                [
                    base[name]
                    + amplitude
                    * deterministic_noise(seed, partition, label, row, name)
                    for name in FEATURE_NAMES
                ]
            )
            labels.append(label)
    return observations, labels


def _fit_scaler(rows: list[list[float]]) -> tuple[list[float], list[float], list[list[float]]]:
    means = [sum(column) / len(rows) for column in zip(*rows)]
    scales = []
    for index, mean in enumerate(means):
        variance = sum((row[index] - mean) ** 2 for row in rows) / len(rows)
        scales.append(math.sqrt(variance) or 1.0)
    transformed = [
        [(value - means[index]) / scales[index] for index, value in enumerate(row)]
        for row in rows
    ]
    return means, scales, transformed


def _softmax(logits: list[float]) -> list[float]:
    maximum = max(logits)
    values = [math.exp(value - maximum) for value in logits]
    total = sum(values)
    return [value / total for value in values]


def _fit_model(rows: list[list[float]], labels: list[str]) -> tuple[list[list[float]], list[float]]:
    class_index = {label: index for index, label in enumerate(CLASS_ORDER)}
    weights = [[0.0 for _ in FEATURE_NAMES] for _ in CLASS_ORDER]
    intercept = [0.0 for _ in CLASS_ORDER]
    learning_rate = 0.045
    regularization = 0.001
    for _ in range(1400):
        weight_gradient = [[0.0 for _ in FEATURE_NAMES] for _ in CLASS_ORDER]
        intercept_gradient = [0.0 for _ in CLASS_ORDER]
        for row, label in zip(rows, labels):
            probabilities = _softmax(
                [
                    intercept[cls] + sum(weight * value for weight, value in zip(weights[cls], row))
                    for cls in range(len(CLASS_ORDER))
                ]
            )
            expected = class_index[label]
            for cls, probability in enumerate(probabilities):
                error = probability - (1.0 if cls == expected else 0.0)
                intercept_gradient[cls] += error
                for feature_index, value in enumerate(row):
                    weight_gradient[cls][feature_index] += error * value
        count = len(rows)
        for cls in range(len(CLASS_ORDER)):
            intercept[cls] -= learning_rate * intercept_gradient[cls] / count
            for feature_index in range(len(FEATURE_NAMES)):
                gradient = weight_gradient[cls][feature_index] / count
                gradient += regularization * weights[cls][feature_index]
                weights[cls][feature_index] -= learning_rate * gradient
    return weights, intercept


def _predict(row: list[float], weights: list[list[float]], intercept: list[float]) -> list[float]:
    return _softmax(
        [bias + sum(weight * value for weight, value in zip(class_weights, row)) for class_weights, bias in zip(weights, intercept)]
    )


def _rounded(values: list[float]) -> list[float]:
    return [float(f"{value:.12f}") for value in values]


def _source_partition_manifest(
    seed: int,
    partition: str,
    rows: list[list[float]],
    labels: list[str],
) -> dict[str, object]:
    batch_ids = [
        hashlib.sha256(f"{seed}:{partition}:batch:{index}".encode("ascii")).hexdigest()
        for index in range(len(rows))
    ]
    batch_id_manifest_hash = hashlib.sha256(
        canonical_bytes({"partition": partition, "batch_ids": batch_ids})
    ).hexdigest()
    observations_hash = hashlib.sha256(
        canonical_bytes(
            {
                "feature_names": FEATURE_NAMES,
                "rows": [[f"{value:.12f}" for value in row] for row in rows],
            }
        )
    ).hexdigest()
    labels_hash = hashlib.sha256(canonical_bytes(labels)).hexdigest()
    partition_manifest_hash = hashlib.sha256(
        canonical_bytes(
            {
                "partition": partition,
                "random_seed": seed,
                "batch_count": len(rows),
                "batch_id_manifest_hash": batch_id_manifest_hash,
                "observations_hash": observations_hash,
                "labels_hash": labels_hash,
            }
        )
    ).hexdigest()
    return {
        "partition": partition,
        "batch_count": len(rows),
        "random_seed": seed,
        "batch_id_manifest_hash": batch_id_manifest_hash,
        "observations_hash": observations_hash,
        "labels_hash": labels_hash,
        "partition_manifest_hash": partition_manifest_hash,
    }


def generate(output: Path, seed: int = 20260718) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    training_seed = seed + TRAINING_SEED_OFFSET
    validation_seed = seed + VALIDATION_SEED_OFFSET
    train_rows, train_labels = build_partition(training_seed, "TRAIN", 12)
    validation_rows, validation_labels = build_partition(
        validation_seed, "VALIDATION", 4
    )
    source_assets = {
        "training": _source_partition_manifest(
            training_seed, "diagnostic-dev-train-v1", train_rows, train_labels
        ),
        "validation": _source_partition_manifest(
            validation_seed,
            "diagnostic-dev-validation-v1",
            validation_rows,
            validation_labels,
        ),
    }
    means, scales, standardized_train = _fit_scaler(train_rows)
    weights, intercept = _fit_model(standardized_train, train_labels)
    standardized_validation = [
        [(value - means[index]) / scales[index] for index, value in enumerate(row)]
        for row in validation_rows
    ]
    validation_predictions = [
        _predict(row, weights, intercept) for row in standardized_validation
    ]
    correct_scores: list[float] = []
    correct_margins: list[float] = []
    for label, probabilities in zip(validation_labels, validation_predictions):
        ordered = sorted(probabilities, reverse=True)
        predicted = CLASS_ORDER[max(range(len(CLASS_ORDER)), key=probabilities.__getitem__)]
        if predicted == label:
            correct_scores.append(ordered[0])
            correct_margins.append(ordered[0] - ordered[1])
    top_score_min = min(0.80, max(0.45, min(correct_scores) * 0.80))
    top_margin_min = min(0.30, max(0.08, min(correct_margins) * 0.70))

    artifacts: dict[str, object] = {
        "feature-definition.json": {
            "feature_definition_version": FEATURE_DEFINITION_VERSION,
            "features": feature_definition(),
        },
        "preprocessing.json": {
            "artifact_type": "StandardScaler",
            "preprocessing_version": PREPROCESSING_VERSION,
            "feature_names": list(FEATURE_NAMES),
            "mean": _rounded(means),
            "scale": _rounded(scales),
        },
        "model.json": {
            "artifact_type": "multinomial_logistic_regression",
            "model_version": MODEL_VERSION,
            "feature_names": list(FEATURE_NAMES),
            "class_order": list(CLASS_ORDER),
            "coefficient": [_rounded(row) for row in weights],
            "intercept": _rounded(intercept),
            "solver": "deterministic_full_batch_gradient_descent",
            "random_seed": seed,
        },
        "class-order.json": {
            "model_version": MODEL_VERSION,
            "class_order": list(CLASS_ORDER),
        },
        "evidence-rules.json": {
            "evidence_rule_version": EVIDENCE_RULE_VERSION,
            "validation_partition": "diagnostic-dev-validation-v1",
            "top1_score_minimum": f"{top_score_min:.6f}",
            "top1_top2_margin_minimum": f"{top_margin_min:.6f}",
            "plane_tilt_spatial_support_minimum": "0.040000",
            "xy_parameter_support_minimum": "0.080000",
            "platform_vibration_mean_minimum": "0.040000",
            "platform_repeat_error_mean_minimum": "0.035000",
            "reference_residual_mean_minimum": "0.040000",
            "z_center_near_limit_margin": "0.030000",
            "z_corner_mean_margin": "0.020000",
            "z_asymmetry_maximum": "0.080000",
            "z_corner_std_maximum": "0.035000",
        },
    }
    files: dict[str, str] = {}
    for name, payload in artifacts.items():
        content = canonical_bytes(payload)
        (output / name).write_bytes(content)
        files[name] = hashlib.sha256(content).hexdigest()
    model_payload = artifacts["model.json"]
    model_fingerprint = hashlib.sha256(canonical_bytes(model_payload)).hexdigest()
    manifest = {
        "manifest_version": "1",
        "asset_version": "tw-diagnostic-assets-v1",
        "source_generator_version": "tw-diagnostic-synthetic-source-v1",
        "partition_seed_derivation": {
            "training_offset": TRAINING_SEED_OFFSET,
            "validation_offset": VALIDATION_SEED_OFFSET,
        },
        "feature_definition_version": FEATURE_DEFINITION_VERSION,
        "preprocessing_version": PREPROCESSING_VERSION,
        "model_version": MODEL_VERSION,
        "evidence_rule_version": EVIDENCE_RULE_VERSION,
        "class_order": list(CLASS_ORDER),
        "random_seed": seed,
        "training_partition": "diagnostic-dev-train-v1",
        "validation_partition": "diagnostic-dev-validation-v1",
        "training_batch_count": len(train_rows),
        "validation_batch_count": len(validation_rows),
        "excluded_partitions": ["demo", "test", "blind-test"],
        "source_assets": source_assets,
        "dependency_summary": {
            "implementation": "python-standard-library",
            # Frozen generation provenance is part of the immutable asset contract;
            # using the current runtime here makes byte-for-byte regeneration drift.
            "python": "3.11.9",
            "python_implementation": "CPython",
            "serialization": "canonical-json-v1",
        },
        "model_fingerprint": model_fingerprint,
        "files": files,
    }
    manifest_bytes = canonical_bytes(manifest)
    (output / "manifest.json").write_bytes(manifest_bytes)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 TuneWise 固定根因诊断资产。")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260718)
    arguments = parser.parse_args()
    manifest = generate(arguments.output, arguments.seed)
    sys.stdout.write(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
