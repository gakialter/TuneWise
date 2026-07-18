from __future__ import annotations


CLASS_ORDER = (
    "PLANE_TILT",
    "XY_DECENTER",
    "PLATFORM_INSTABILITY",
    "REFERENCE_DRIFT",
    "Z_DEFOCUS_CONDITIONAL",
)

FEATURE_DEFINITION_VERSION = "tw-feature-definition-v1"
MODEL_VERSION = "tw-model-v1"
PREPROCESSING_VERSION = "tw-preprocessing-v1"
EVIDENCE_RULE_VERSION = "tw-evidence-rules-v1"
DIAGNOSTIC_RESULT_VERSION = "tw-diagnostic-result-v1"
CALCULATION_VERSION = "tw-batch-feature-calculation-v1"

MTF_FIELDS = ("mtf_center", "mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb")
PARAMETER_FIELDS = ("x_offset", "y_offset", "pitch", "roll", "z_offset")
PLATFORM_FIELDS = (
    "vibration_rms",
    "repeat_position_error",
    "calibration_residual_x",
    "calibration_residual_y",
)


def feature_names() -> tuple[str, ...]:
    statistical = tuple(
        f"{field}_{statistic}"
        for field in (*MTF_FIELDS, *PARAMETER_FIELDS, *PLATFORM_FIELDS)
        for statistic in ("mean", "std", "trend")
    )
    spatial = (
        "corner_mtf_mean",
        "corner_mtf_min",
        "corner_mtf_range",
        "corner_mtf_std",
        "left_right_difference",
        "top_bottom_difference",
        "diagonal_difference",
        "center_corner_gap",
    )
    return statistical + spatial


FEATURE_NAMES = feature_names()


def feature_definition() -> list[dict[str, object]]:
    definitions: list[dict[str, object]] = []
    corner_fields = MTF_FIELDS[1:]
    for index, name in enumerate(FEATURE_NAMES):
        source = name.rsplit("_", 1)[0]
        if name.startswith("corner_mtf_") or name.endswith("_difference"):
            sources = list(corner_fields)
            unit = "Normalized MTF"
        elif name == "center_corner_gap":
            sources = list(MTF_FIELDS)
            unit = "Normalized MTF"
        else:
            sources = [source]
            unit = (
                "Normalized MTF"
                if source in MTF_FIELDS
                else "Normalized Angular Unit"
                if source in ("pitch", "roll")
                else "Normalized Offset Unit"
                if source in PARAMETER_FIELDS
                else "Normalized Prototype Unit"
            )
        definitions.append(
            {
                "feature_name": name,
                "feature_index": index,
                "calculation_version": CALCULATION_VERSION,
                "expected_unit": unit,
                "missing_value_policy": "REJECT_BATCH",
                "allowed_source_fields": sources,
            }
        )
    return definitions
