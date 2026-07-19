from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Any, Mapping

from .importing import OBSERVABLE_FIELDS


PRECISION = Decimal("0.000001")
PARAMETER_FIELDS = ("x_offset", "y_offset", "pitch", "roll", "z_offset")
PLATFORM_FIELDS = (
    "vibration_rms",
    "repeat_position_error",
    "calibration_residual_x",
    "calibration_residual_y",
)
QUALITY_FIELDS = ("mtf_center", "mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb")
CORNER_COORDINATES = {
    "mtf_lt": (Decimal("-1"), Decimal("1")),
    "mtf_rt": (Decimal("1"), Decimal("1")),
    "mtf_lb": (Decimal("-1"), Decimal("-1")),
    "mtf_rb": (Decimal("1"), Decimal("-1")),
}


class FrozenMeasurement(dict[str, str]):
    @staticmethod
    def _immutable(*_args: object, **_kwargs: object) -> None:
        raise TypeError("Simulator measurements are immutable.")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"Invalid simulator decimal: {field}") from error
    if not result.is_finite():
        raise ValueError(f"Invalid simulator decimal: {field}")
    return result


def _fixed(value: Decimal) -> str:
    return format(value.quantize(PRECISION, rounding=ROUND_HALF_EVEN), "f")


def _bounded(value: Decimal) -> Decimal:
    return min(Decimal("1"), max(Decimal("0"), value))


def _center_penalty(parameters: Mapping[str, Decimal], scenario: Mapping[str, Any]) -> Decimal:
    coefficients = scenario["causal_coefficients"]
    return (
        _decimal(coefficients["center_tilt_penalty"], "center_tilt_penalty")
        * (parameters["pitch"] ** 2 + parameters["roll"] ** 2)
        + _decimal(coefficients["center_decenter_penalty"], "center_decenter_penalty")
        * (parameters["x_offset"] ** 2 + parameters["y_offset"] ** 2)
        + _decimal(coefficients["center_z_penalty"], "center_z_penalty")
        * parameters["z_offset"] ** 2
    )


def _corner_penalty(
    field: str,
    parameters: Mapping[str, Decimal],
    scenario: Mapping[str, Any],
) -> Decimal:
    x_coordinate, y_coordinate = CORNER_COORDINATES[field]
    coefficients = scenario["causal_coefficients"]
    local_focus_error = (
        parameters["z_offset"]
        + parameters["pitch"] * y_coordinate
        + parameters["roll"] * x_coordinate
    )
    directional_decenter = (
        parameters["x_offset"] * x_coordinate
        + parameters["y_offset"] * y_coordinate
    )
    focus_penalties = coefficients["corner_focus_penalties"]
    return (
        _decimal(focus_penalties[field], f"corner_focus_penalties.{field}")
        * local_focus_error**2
        + _decimal(coefficients["corner_decenter_penalty"], "corner_decenter_penalty")
        * directional_decenter**2
    )


def simulate_observations(
    scenario: Mapping[str, Any],
    disturbance: Mapping[str, Any],
    parameters: Mapping[str, str],
    sample_count: int,
) -> tuple[FrozenMeasurement, ...]:
    if tuple(sorted(parameters)) != tuple(sorted(PARAMETER_FIELDS)):
        raise ValueError("Simulator parameters must match the frozen parameter fields.")
    numeric_parameters = {
        field: _decimal(parameters[field], field) for field in PARAMETER_FIELDS
    }
    for field, value in numeric_parameters.items():
        if value < -1 or value > 1 or value % Decimal("0.05") != 0:
            raise ValueError(f"Simulator parameter is outside the frozen grid: {field}")
    rows = disturbance.get("records")
    if not isinstance(rows, list) or sample_count <= 0 or sample_count > len(rows):
        raise ValueError("Simulator disturbance sequence does not cover sample_count.")
    baseline_parameters = {
        field: _decimal(scenario["baseline_parameters"][field], field)
        for field in PARAMETER_FIELDS
    }
    started_at = datetime.fromisoformat(
        str(scenario["start_timestamp"]).replace("Z", "+00:00")
    ).astimezone(UTC)
    center_delta = _center_penalty(baseline_parameters, scenario) - _center_penalty(
        numeric_parameters, scenario
    )
    corner_deltas = {
        field: _corner_penalty(field, baseline_parameters, scenario)
        - _corner_penalty(field, numeric_parameters, scenario)
        for field in CORNER_COORDINATES
    }
    result: list[FrozenMeasurement] = []
    for sample_index, disturbance_row in enumerate(rows[:sample_count]):
        if disturbance_row.get("sample_index") != sample_index:
            raise ValueError("Simulator disturbance sequence order is invalid.")
        noise = disturbance_row.get("noise")
        if not isinstance(noise, dict):
            raise ValueError("Simulator disturbance record is invalid.")
        row: dict[str, str] = {
            "sample_index": str(sample_index),
            "timestamp": (started_at + timedelta(seconds=sample_index))
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            **{field: _fixed(numeric_parameters[field]) for field in PARAMETER_FIELDS},
        }
        for field in PLATFORM_FIELDS:
            row[field] = _fixed(
                _decimal(scenario["observable_baselines"][field], field)
                + _decimal(scenario["noise_amplitudes"][field], field)
                * _decimal(noise[field], field)
            )
        for field in QUALITY_FIELDS:
            causal_delta = center_delta if field == "mtf_center" else corner_deltas[field]
            row[field] = _fixed(
                _bounded(
                    _decimal(scenario["observable_baselines"][field], field)
                    + causal_delta
                    + _decimal(scenario["noise_amplitudes"][field], field)
                    * _decimal(noise[field], field)
                )
            )
        result.append(FrozenMeasurement((field, row[field]) for field in OBSERVABLE_FIELDS))
    return tuple(result)
