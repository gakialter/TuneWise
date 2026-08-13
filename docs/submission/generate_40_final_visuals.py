"""Generate the eight fact-audited TuneWise 40-final SVG diagrams.

The script intentionally uses only the Python standard library. It reads the
repository's fixed evidence files before rendering and fails closed when the
facts needed by the diagrams cannot be found.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from html import escape
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "submission" / "assets" / "40-final"
RUNTIME_SCREENSHOTS = OUTPUT / "runtime-screenshots"
AILY_SCREENSHOT = OUTPUT / "aily-screenshots" / "03_hero_qa.png"
FONT = "Microsoft YaHei, Segoe UI, sans-serif"
MONO = "Cascadia Mono, Consolas, Microsoft YaHei, monospace"


COLORS = {
    "bg": "#F4F7FB",
    "paper": "#FFFFFF",
    "ink": "#10233F",
    "muted": "#5D6B82",
    "line": "#D7DEEA",
    "blue": "#355CFF",
    "blue_dark": "#223D9A",
    "blue_soft": "#EAF0FF",
    "purple": "#6F5CE7",
    "purple_soft": "#F0EDFF",
    "teal": "#0C9A9A",
    "teal_soft": "#E3F6F5",
    "green": "#16885B",
    "green_soft": "#E7F5EE",
    "orange": "#D97706",
    "orange_soft": "#FFF1DF",
    "red": "#C94242",
    "red_soft": "#FCEBEC",
    "slate": "#33445E",
    "slate_soft": "#EDF1F6",
}


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=None)
def png_asset(path_value: str) -> tuple[str, int, int]:
    path = Path(path_value)
    payload = path.read_bytes()
    if payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
        raise RuntimeError(f"Expected a valid PNG screenshot: {path}")
    width = int.from_bytes(payload[16:20], "big")
    height = int.from_bytes(payload[20:24], "big")
    data_uri = "data:image/png;base64," + base64.b64encode(payload).decode("ascii")
    return data_uri, width, height


def capture(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if not match:
        raise RuntimeError(f"Required repository fact missing: {label}")
    return match.group(1)


def require(text: str, *needles: str) -> None:
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise RuntimeError(f"Required repository facts missing: {missing}")


@dataclass(frozen=True)
class Facts:
    task_id: str
    asset_id: str
    batch_id: str
    sample_count: str
    anomaly: str
    top_root_cause: str
    score: str
    top_bottom: str
    left_right: str
    diagonal: str
    pitch_current: str
    pitch_target: str
    pitch_delta: str
    selected_ticks: int
    standard_ticks: int
    case_ticks: int
    standard_target: str
    case_target: str
    candidate_id: str
    candidate_hash: str
    confirmed_plan_id: str
    confirmed_plan_hash: str
    replay_result_id: str
    replay_hash: str
    replay_status: str
    baseline_status: str
    execution_surface: str
    execution_status: str
    actual_after: str
    receipt_hash: str
    historical_commit: str
    backend_tests: str
    frontend_tests: str
    process_a_case_id: str
    process_b_case_id: str
    process_a_ticks: int
    process_b_ticks: int


def load_facts() -> Facts:
    demo = read("docs/aily/knowledge/05_demo_evidence_snapshot.txt")
    aily = read("docs/validation/aily-v1-validation.md")
    engineering = read("docs/validation/engineering-validation.md")
    browser = json.loads(read("docs/validation/browser-qa-evidence.json"))
    process_demo = json.loads(
        read("assets/demo/tw-process-aware-demo-v1/process-aware-demo.json")
    )
    process_qa = read("frontend/e2e/process-aware-qa.mjs")
    approved_cases = json.loads(
        read("assets/cases/tw-approved-case-index-v1/approved-cases.json")
    )
    public_data_audit = read("docs/research/loros-public-optical-dataset.md")
    challenge = read("docs/competition/challenge-brief.md")
    diagnostic_manifest = json.loads(
        read("assets/diagnostic/tw-diagnostic-v1/manifest.json")
    )
    planning_rules = json.loads(
        read("assets/planning/tw-parameter-planning-v1/planning-rules.json")
    )

    require(
        challenge,
        "如果你是智造专家，你将如何借助 AI 设计并打造「智造调机助手」，提升现场良率？",
    )
    require(
        demo,
        "Score is not a calibrated fault probability.",
        "Replay result does not demonstrate production yield improvement.",
        "AA_PROCESS_ENGINEER",
        "LOCAL_ANONYMOUS_SANDBOX",
    )
    require(
        aily,
        "Live Knowledge Pack: 8/8",
        "Legacy Safety Hard Gates: PASS",
        "Process-aware QA: PASS",
        "Published Environment: PASS",
        "Manual UI / conversational acceptance validation",
        "不是实时 Runtime Evidence API",
    )
    require(
        engineering,
        "454 / 454 PASS",
        "46 / 46 PASS",
        "433 passed",
        "40 passed",
        "Production build",
        "本地模拟设备",
    )
    require(
        process_qa,
        "tw-aa-approved-011",
        "tw-aa-approved-003",
        "当前演示用于证明 TuneWise 能根据不同调机过程信息选择不同的历史参考案例。",
    )
    require(
        public_data_audit,
        "10.5281/zenodo.17493261",
        "10.1186/s40645-025-00783-7",
        "CC-BY-4.0",
        "没有 TuneWise 所需的装调参数",
        "不能据此计算 TuneWise classifier accuracy",
    )
    if diagnostic_manifest.get("model_version") != "tw-model-v1":
        raise RuntimeError("Diagnostic model version no longer matches audited facts")
    if planning_rules.get("planning_rule_version") != "tw-parameter-planning-v1":
        raise RuntimeError("Planning rule version no longer matches audited facts")

    current = capture(r"- Current value：\x60([^\x60]+)\x60", demo, "selected current")
    target = capture(r"- Target value：\x60([^\x60]+)\x60", demo, "selected target")
    selected_ticks = int(capture(r"即 \x60(-?\d+)\x60 tick", demo, "selected tick"))
    standard_ticks = int(
        capture(r"\x60STANDARD=(-?\d+) ticks\x60", demo, "standard ticks")
    )
    case_ticks = int(
        capture(r"\x60CASE_GUIDED=(-?\d+) ticks\x60", demo, "case-guided ticks")
    )
    step = Decimal("0.050000")
    standard_target = f"{Decimal(current) + step * standard_ticks:.6f}"
    case_target = f"{Decimal(current) + step * case_ticks:.6f}"

    if process_demo.get("synthetic") is not True:
        raise RuntimeError("Process-aware demo must remain explicitly synthetic")
    if process_demo.get("source_kind") != "SYNTHETIC_TEST_FIXTURE":
        raise RuntimeError("Process-aware demo source boundary changed")
    contexts = {item["scenario_id"]: item for item in process_demo["contexts"]}
    profiles = {
        item["compatible_process_stage"]: item
        for item in process_demo["case_process_profiles"]
    }
    if contexts["A"]["process_stage"] != "INITIAL_ASSESSMENT":
        raise RuntimeError("Process-aware scenario A stage changed")
    if contexts["B"]["process_stage"] != "POST_ADJUSTMENT_EVALUATION":
        raise RuntimeError("Process-aware scenario B stage changed")
    process_a_case_id = profiles["INITIAL_ASSESSMENT"]["case_id"]
    process_b_case_id = profiles["POST_ADJUSTMENT_EVALUATION"]["case_id"]
    if (process_a_case_id, process_b_case_id) != (
        "tw-aa-approved-011",
        "tw-aa-approved-003",
    ):
        raise RuntimeError("Process-aware A/B eligible case bindings changed")
    case_ticks_by_id = {
        item["case_id"]: int(item["historical_action"]["parameter_delta_ticks"]["pitch"])
        for item in approved_cases["cases"]
        if item["case_id"] in {process_a_case_id, process_b_case_id}
    }
    if case_ticks_by_id != {
        "tw-aa-approved-011": -3,
        "tw-aa-approved-003": -4,
    }:
        raise RuntimeError("Process-aware reference-case pitch evidence changed")

    return Facts(
        task_id=capture(r"- Task ID：\x60([^\x60]+)\x60", demo, "task id"),
        asset_id=capture(r"- Preset asset：\x60([^\x60]+)\x60", demo, "asset id"),
        batch_id=capture(r"- Batch ID：\x60([^\x60]+)\x60", demo, "batch id"),
        sample_count=capture(r"- Sample count：\x60([^\x60]+)\x60", demo, "sample count"),
        anomaly=capture(r"- Result：\x60([^\x60]+)\x60", demo, "anomaly"),
        top_root_cause=capture(
            r"1\. \x60([^\x60]+)\x60 — normalized score", demo, "top root cause"
        ),
        score=capture(
            r"1\. \x60PLANE_TILT\x60 — normalized score \x60([^\x60]+)\x60",
            demo,
            "top score",
        ),
        top_bottom=capture(
            r"top_bottom_difference=([+-]?[0-9.]+)", demo, "top-bottom feature"
        ),
        left_right=capture(
            r"left_right_difference=([+-]?[0-9.]+)", demo, "left-right feature"
        ),
        diagonal=capture(
            r"diagonal_difference=([+-]?[0-9.]+)", demo, "diagonal feature"
        ),
        pitch_current=current,
        pitch_target=target,
        pitch_delta=capture(r"- Delta：\x60([^\x60]+)\x60", demo, "selected delta"),
        selected_ticks=selected_ticks,
        standard_ticks=standard_ticks,
        case_ticks=case_ticks,
        standard_target=standard_target,
        case_target=case_target,
        candidate_id=capture(r"- Candidate ID：\x60([^\x60]+)\x60", demo, "candidate id"),
        candidate_hash=capture(r"- Candidate hash：\x60([^\x60]+)\x60", demo, "candidate hash"),
        confirmed_plan_id=capture(
            r"- ConfirmedPlan ID：\x60([^\x60]+)\x60", demo, "confirmed plan id"
        ),
        confirmed_plan_hash=capture(
            r"- ConfirmedPlan hash：\x60([^\x60]+)\x60", demo, "confirmed plan hash"
        ),
        replay_result_id=capture(
            r"- ReplayResult ID：\x60([^\x60]+)\x60", demo, "replay result id"
        ),
        replay_hash=capture(r"ReplayResult hash：\x60([^\x60]+)\x60", demo, "replay hash"),
        replay_status=capture(r"- Replay status：\x60([^\x60]+)\x60", demo, "replay status"),
        baseline_status=capture(
            r"- Baseline reproduction：\x60([^\x60]+)\x60", demo, "baseline status"
        ),
        execution_surface=str(browser["execution_surface"]),
        execution_status=str(browser["execution_status"]),
        actual_after=str(browser["actual_after_value"]),
        receipt_hash=str(browser["receipt_hash"]),
        historical_commit=capture(
            r"历史基线 \x60main\x60 / \x60([0-9a-f]{40})\x60",
            engineering,
            "validation commit",
        ),
        backend_tests=capture(
            r"\| 后端全量 \|.*?\*\*(\d+) / \d+ PASS\*\*",
            engineering,
            "current backend tests",
        ),
        frontend_tests=capture(
            r"\| 前端全量 \|.*?\*\*(\d+) / \d+ PASS\*\*",
            engineering,
            "current frontend tests",
        ),
        process_a_case_id=process_a_case_id,
        process_b_case_id=process_b_case_id,
        process_a_ticks=case_ticks_by_id[process_a_case_id],
        process_b_ticks=case_ticks_by_id[process_b_case_id],
    )


def validate_runtime_screenshot_evidence() -> None:
    evidence_path = RUNTIME_SCREENSHOTS / "runtime-screenshot-evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    fixed = evidence.get("fixed_demo", {})
    process = evidence.get("process_aware_demo", {})
    aily = evidence.get("aily_live_screenshot", {})
    expected_fixed = {
        "task_id": "tw-demo-task-001",
        "top_root_cause": "PLANE_TILT",
        "relative_ranking_score": "0.997781",
        "confirmed_plan_status": "VALID",
        "simulation_validation_status": "SUCCESS",
        "execution_surface": "LOCAL_OPCUA_SANDBOX",
        "execution_status": "SUCCEEDED",
        "actual_after_readback": "0.200000",
    }
    for key, expected in expected_fixed.items():
        if fixed.get(key) != expected:
            raise RuntimeError(f"Runtime screenshot evidence mismatch: fixed_demo.{key}")
    selected = fixed.get("selected_candidate", {})
    if selected != {
        "parameter_name": "pitch",
        "current_value": "0.250000",
        "target_value": "0.200000",
        "generation_type": "CONSERVATIVE",
        "delta_ticks": -1,
        "validation_status": "PASSED",
    }:
        raise RuntimeError("Runtime screenshot selected-candidate evidence changed")
    if process.get("source_kind") != "SYNTHETIC_TEST_FIXTURE":
        raise RuntimeError("Process-aware screenshot source must remain synthetic")
    if process.get("shared_evidence") != {
        "measurement_evidence": "SAME",
        "top_root_cause": "PLANE_TILT",
        "root_cause_evidence": "SAME",
    }:
        raise RuntimeError("Process-aware shared evidence changed")
    if process.get("scenario_a", {}).get("eligible_case") != "tw-aa-approved-011":
        raise RuntimeError("Process-aware screenshot scenario A case changed")
    if process.get("scenario_a", {}).get("case_guided_pitch_ticks") != -3:
        raise RuntimeError("Process-aware screenshot scenario A candidate changed")
    if process.get("scenario_b", {}).get("eligible_case") != "tw-aa-approved-003":
        raise RuntimeError("Process-aware screenshot scenario B case changed")
    if process.get("scenario_b", {}).get("case_guided_pitch_ticks") != -4:
        raise RuntimeError("Process-aware screenshot scenario B candidate changed")
    if process.get("unchanged_controls") != {
        "conservative_pitch_ticks": -1,
        "standard_pitch_ticks": -2,
        "parameter_safety_validator": "PASSED",
    }:
        raise RuntimeError("Process-aware screenshot invariant controls changed")
    if aily.get("process_aware_q5") is not False:
        raise RuntimeError("Existing Aily screenshot must not be presented as Process-aware Q5")
    if aily.get("device_control_evidence") is not False:
        raise RuntimeError("Aily screenshot must not be presented as device-control evidence")

    recorded = {item["file"]: item["sha256"] for item in evidence.get("screenshots", [])}
    used_runtime_files = [
        "fixed-01-root-cause-top1.png",
        "fixed-02-selected-conservative-candidate.png",
        "fixed-03-confirmed-plan.png",
        "fixed-04-replay-result.png",
        "fixed-05-device-receipt.png",
        "process-01-shared-evidence.png",
        "process-02-scenario-a-path.png",
        "process-03-scenario-a-candidate.png",
        "process-04-scenario-b-path.png",
        "process-05-scenario-b-candidate.png",
        "process-06-invariant-band.png",
    ]
    for name in used_runtime_files:
        path = RUNTIME_SCREENSHOTS / name
        relative = path.relative_to(ROOT).as_posix()
        if recorded.get(relative) != sha256_file(path):
            raise RuntimeError(f"Runtime screenshot hash mismatch: {relative}")
    if aily.get("sha256") != sha256_file(AILY_SCREENSHOT):
        raise RuntimeError("Existing Aily screenshot hash mismatch")


class Svg:
    def __init__(self) -> None:
        self.parts: list[str] = [
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            'width="1920" height="1080" '
            'viewBox="0 0 1920 1080" role="img">',
            "<defs>",
            '<linearGradient id="accent" x1="0" x2="1">',
            f'<stop offset="0" stop-color="{COLORS["blue"]}"/>',
            f'<stop offset=".52" stop-color="{COLORS["purple"]}"/>',
            f'<stop offset="1" stop-color="{COLORS["teal"]}"/>',
            "</linearGradient>",
            '<filter id="shadow" x="-20%" y="-20%" width="140%" height="160%">',
            '<feDropShadow dx="0" dy="8" stdDeviation="12" flood-color="#1C3355" flood-opacity=".09"/>',
            "</filter>",
        ]
        for name, color in (
            ("arrow", COLORS["slate"]),
            ("arrow-blue", COLORS["blue"]),
            ("arrow-green", COLORS["green"]),
            ("arrow-red", COLORS["red"]),
            ("arrow-orange", COLORS["orange"]),
        ):
            self.parts.extend(
                [
                    f'<marker id="{name}" viewBox="0 0 10 10" refX="8.5" refY="5" '
                    'markerWidth="8" markerHeight="8" orient="auto-start-reverse">',
                    f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/>',
                    "</marker>",
                ]
            )
        self.parts.append("</defs>")

    def raw(self, value: str) -> None:
        self.parts.append(value)

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: str = "none",
        stroke: str = "none",
        sw: float = 1,
        rx: float = 16,
        dash: str | None = None,
        shadow: bool = False,
        opacity: float = 1,
    ) -> None:
        attrs = [
            f'x="{x}"',
            f'y="{y}"',
            f'width="{w}"',
            f'height="{h}"',
            f'rx="{rx}"',
            f'fill="{fill}"',
            f'stroke="{stroke}"',
            f'stroke-width="{sw}"',
            f'opacity="{opacity}"',
        ]
        if dash:
            attrs.append(f'stroke-dasharray="{dash}"')
        if shadow:
            attrs.append('filter="url(#shadow)"')
        self.raw(f"<rect {' '.join(attrs)}/>")

    def image(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        path: Path,
        *,
        fit: str = "meet",
    ) -> None:
        data_uri, _, _ = png_asset(str(path))
        self.raw(
            f'<image x="{x}" y="{y}" width="{w}" height="{h}" '
            f'href="{data_uri}" xlink:href="{data_uri}" '
            f'preserveAspectRatio="xMidYMid {fit}"/>'
        )

    def image_crop(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        path: Path,
        crop: tuple[float, float, float, float],
    ) -> None:
        data_uri, source_width, source_height = png_asset(str(path))
        crop_x, crop_y, crop_w, crop_h = crop
        if (
            crop_x < 0
            or crop_y < 0
            or crop_w <= 0
            or crop_h <= 0
            or crop_x + crop_w > source_width
            or crop_y + crop_h > source_height
        ):
            raise RuntimeError(f"Invalid raster crop for {path.name}: {crop}")
        self.raw(
            f'<svg x="{x}" y="{y}" width="{w}" height="{h}" '
            f'viewBox="{crop_x} {crop_y} {crop_w} {crop_h}" '
            'preserveAspectRatio="xMidYMid meet" overflow="hidden">'
            f'<image x="0" y="0" width="{source_width}" height="{source_height}" '
            f'href="{data_uri}" xlink:href="{data_uri}"/>'
            "</svg>"
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        color: str = COLORS["line"],
        sw: float = 2,
        marker: str | None = None,
        dash: str | None = None,
        opacity: float = 1,
    ) -> None:
        attrs = [
            f'x1="{x1}"',
            f'y1="{y1}"',
            f'x2="{x2}"',
            f'y2="{y2}"',
            f'stroke="{color}"',
            f'stroke-width="{sw}"',
            'stroke-linecap="round"',
            f'opacity="{opacity}"',
        ]
        if marker:
            attrs.append(f'marker-end="url(#{marker})"')
        if dash:
            attrs.append(f'stroke-dasharray="{dash}"')
        self.raw(f"<line {' '.join(attrs)}/>")

    def path(
        self,
        d: str,
        *,
        color: str = COLORS["line"],
        sw: float = 2,
        fill: str = "none",
        marker: str | None = None,
        dash: str | None = None,
    ) -> None:
        attrs = [
            f'd="{d}"',
            f'stroke="{color}"',
            f'stroke-width="{sw}"',
            f'fill="{fill}"',
            'stroke-linecap="round"',
            'stroke-linejoin="round"',
        ]
        if marker:
            attrs.append(f'marker-end="url(#{marker})"')
        if dash:
            attrs.append(f'stroke-dasharray="{dash}"')
        self.raw(f"<path {' '.join(attrs)}/>")

    def circle(
        self,
        cx: float,
        cy: float,
        r: float,
        *,
        fill: str,
        stroke: str = "none",
        sw: float = 1,
    ) -> None:
        self.raw(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"/>'
        )

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        size: float = 22,
        color: str = COLORS["ink"],
        weight: int = 400,
        anchor: str = "start",
        family: str = FONT,
        opacity: float = 1,
        letter_spacing: float | None = None,
    ) -> None:
        extra = (
            f' letter-spacing="{letter_spacing}"' if letter_spacing is not None else ""
        )
        self.raw(
            f'<text x="{x}" y="{y}" fill="{color}" font-family="{family}" '
            f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
            f'dominant-baseline="middle" opacity="{opacity}"{extra}>'
            f"{escape(str(value))}</text>"
        )

    def multiline(
        self,
        x: float,
        y: float,
        lines: list[str] | tuple[str, ...],
        *,
        size: float = 22,
        line_height: float = 30,
        color: str = COLORS["ink"],
        weight: int = 400,
        anchor: str = "start",
        family: str = FONT,
    ) -> None:
        self.raw(
            f'<text x="{x}" y="{y}" fill="{color}" font-family="{family}" '
            f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">'
        )
        for index, line in enumerate(lines):
            dy = 0 if index == 0 else line_height
            self.raw(
                f'<tspan x="{x}" dy="{dy}" dominant-baseline="hanging">'
                f"{escape(str(line))}</tspan>"
            )
        self.raw("</text>")

    def finish(self) -> str:
        self.parts.append("</svg>")
        return "\n".join(self.parts) + "\n"


def base(s: Svg, title: str, subtitle: str, number: str) -> None:
    s.rect(0, 0, 1920, 1080, fill=COLORS["bg"], rx=0)
    s.rect(0, 0, 1920, 12, fill="url(#accent)", rx=0)
    s.text(72, 72, title, size=42, weight=700)
    s.text(74, 126, subtitle, size=21, color=COLORS["muted"])
    s.rect(1615, 48, 235, 56, fill=COLORS["ink"], rx=28)
    s.text(
        1732,
        76,
        f"TuneWise · 图 {number}",
        size=20,
        color="#FFFFFF",
        weight=700,
        anchor="middle",
    )
    s.line(72, 166, 1848, 166, color=COLORS["line"], sw=2)


def footer(s: Svg, text_value: str) -> None:
    s.text(74, 1040, text_value, size=17, color=COLORS["muted"])
    s.text(
        1848,
        1040,
        "40 强最终参赛方案 · 2026-08-11",
        size=17,
        color=COLORS["muted"],
        anchor="end",
    )


def pill(
    s: Svg,
    x: float,
    y: float,
    w: float,
    label: str,
    *,
    fill: str,
    color: str,
    stroke: str = "none",
    size: float = 18,
    weight: int = 700,
) -> None:
    s.rect(x, y, w, 38, fill=fill, stroke=stroke, sw=1.5, rx=19)
    s.text(
        x + w / 2,
        y + 19,
        label,
        size=size,
        color=color,
        weight=weight,
        anchor="middle",
    )


def card(
    s: Svg,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str = COLORS["paper"],
    stroke: str = COLORS["line"],
    sw: float = 1.5,
    rx: float = 18,
    shadow: bool = False,
    dash: str | None = None,
) -> None:
    s.rect(
        x,
        y,
        w,
        h,
        fill=fill,
        stroke=stroke,
        sw=sw,
        rx=rx,
        shadow=shadow,
        dash=dash,
    )


def screenshot_panel(
    s: Svg,
    x: float,
    y: float,
    w: float,
    h: float,
    number: str,
    title: str,
    source: Path,
    *,
    crop: tuple[float, float, float, float] | None = None,
    accent: str = COLORS["teal"],
) -> None:
    card(s, x, y, w, h, fill="#FFFFFF", stroke="#C7D2E2", rx=14, shadow=True)
    s.rect(x, y, w, 46, fill="#F7F9FC", stroke="none", rx=14)
    s.rect(x, y + 33, w, 13, fill="#F7F9FC", stroke="none", rx=0)
    s.circle(x + 27, y + 23, 15, fill=accent)
    s.text(
        x + 27,
        y + 23,
        number,
        size=15,
        color="#FFFFFF",
        weight=700,
        anchor="middle",
    )
    s.text(x + 52, y + 23, title, size=17, color=COLORS["ink"], weight=700)
    image_x, image_y = x + 10, y + 54
    image_w, image_h = w - 20, h - 64
    s.rect(image_x, image_y, image_w, image_h, fill="#F5F8FA", stroke="#D4DCE7", rx=5)
    if crop is None:
        s.image(image_x, image_y, image_w, image_h, source)
    else:
        s.image_crop(image_x, image_y, image_w, image_h, source, crop)


def center_node(
    s: Svg,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    *,
    subtitle: str | None = None,
    fill: str = COLORS["paper"],
    stroke: str = COLORS["line"],
    title_color: str = COLORS["ink"],
    title_size: float = 21,
    dash: str | None = None,
    shadow: bool = False,
) -> None:
    card(
        s,
        x,
        y,
        w,
        h,
        fill=fill,
        stroke=stroke,
        sw=1.7,
        rx=15,
        shadow=shadow,
        dash=dash,
    )
    title_y = y + h / 2 - (12 if subtitle else 0)
    s.text(
        x + w / 2,
        title_y,
        title,
        size=title_size,
        color=title_color,
        weight=700,
        anchor="middle",
    )
    if subtitle:
        s.text(
            x + w / 2,
            y + h / 2 + 22,
            subtitle,
            size=17,
            color=COLORS["muted"],
            anchor="middle",
        )


def numbered_step(
    s: Svg,
    x: float,
    y: float,
    w: float,
    h: float,
    index: int,
    label: str,
    *,
    color: str,
    fill: str,
    stroke: str,
    label_size: float = 19,
) -> None:
    card(s, x, y, w, h, fill=fill, stroke=stroke, sw=1.3, rx=14)
    s.circle(x + 30, y + h / 2, 17, fill=color)
    s.text(
        x + 30,
        y + h / 2,
        str(index),
        size=16,
        color="#FFFFFF",
        weight=700,
        anchor="middle",
    )
    s.text(x + 62, y + h / 2, label, size=label_size, weight=600)


def figure_01(_: Facts) -> str:
    s = Svg()
    base(
        s,
        "传统调机流程 vs TuneWise 决策支持流程",
        "从经验驱动的反复试错，转向证据驱动、安全门禁、工程师确认的可追溯决策",
        "01",
    )
    card(
        s,
        70,
        205,
        730,
        785,
        fill=COLORS["paper"],
        stroke="#F1C7C3",
        shadow=True,
    )
    card(
        s,
        835,
        205,
        1015,
        785,
        fill=COLORS["paper"],
        stroke="#BFCDFC",
        shadow=True,
    )
    s.rect(70, 205, 730, 96, fill=COLORS["red_soft"], stroke="none", rx=18)
    s.rect(835, 205, 1015, 96, fill=COLORS["blue_soft"], stroke="none", rx=18)
    s.text(
        105,
        242,
        "传统调机流程",
        size=28,
        weight=700,
        color=COLORS["red"],
    )
    s.text(
        105,
        278,
        "经验驱动 / 反复试错 / 证据分散",
        size=19,
        color=COLORS["muted"],
    )
    s.text(
        870,
        242,
        "TuneWise 决策支持流程",
        size=28,
        weight=700,
        color=COLORS["blue_dark"],
    )
    for x, w, label in (
        (870, 112, "证据驱动"),
        (994, 112, "安全门禁"),
        (1118, 112, "可追溯"),
        (1242, 112, "人在回路"),
    ):
        pill(
            s,
            x,
            263,
            w,
            label,
            fill="#FFFFFF",
            color=COLORS["blue_dark"],
            stroke="#C4D0FA",
            size=16,
        )

    before = [
        "异常出现",
        "人工检查多个指标",
        "依赖工程师经验猜测根因",
        "人工翻找历史记录与案例",
        "尝试调整参数",
        "重新测量",
        "继续试错迭代",
        "决策依据难追溯",
    ]
    after = [
        "异常出现",
        "SPC 异常检测",
        "AI 根因优先级",
        "当前证据 + 历史参考案例检索",
        "安全调参候选生成",
        "参数安全校验",
        "工程师确认",
        "执行前仿真验证",
        "本地模拟设备受控执行",
    ]
    by = 326
    for index, label in enumerate(before, start=1):
        y = by + (index - 1) * 78
        if index > 1:
            s.line(
                435,
                y - 14,
                435,
                y - 4,
                color=COLORS["red"],
                sw=2.2,
                marker="arrow-red",
            )
        numbered_step(
            s,
            105,
            y,
            660,
            60,
            index,
            label,
            color=COLORS["red"],
            fill="#FFF9F8",
            stroke="#F1D5D2",
            label_size=20,
        )
    ay = 322
    for index, label in enumerate(after, start=1):
        y = ay + (index - 1) * 64
        if index > 1:
            s.line(
                1343,
                y - 11,
                1343,
                y - 3,
                color=COLORS["blue"],
                sw=2.2,
                marker="arrow-blue",
            )
        fill = "#F9FBFF"
        stroke = "#D5DDF8"
        color = COLORS["blue"]
        if label in {"参数安全校验", "工程师确认"}:
            fill, stroke, color = (
                COLORS["green_soft"],
                "#A9D8C0",
                COLORS["green"],
            )
        if "模拟设备" in label:
            fill, stroke, color = (
                COLORS["orange_soft"],
                "#F0C792",
                COLORS["orange"],
            )
        numbered_step(
            s,
            870,
            y,
            945,
            49,
            index,
            label,
            color=color,
            fill=fill,
            stroke=stroke,
            label_size=18.5,
        )
    card(
        s,
        870,
        900,
        945,
        84,
        fill="#FBFAFF",
        stroke="#CFC6F3",
        rx=14,
        dash="6 5",
    )
    pill(
        s,
        885,
        923,
        155,
        "独立解释侧车",
        fill=COLORS["purple_soft"],
        color=COLORS["purple"],
        stroke="#CFC6F3",
        size=14.5,
    )
    sidecar_nodes = [
        (1060, 205, "Core 决策证据"),
        (1300, 242, "版本化知识 / 固定证据"),
        (1577, 215, "飞书 Aily · 检索 / 解释"),
    ]
    for index, (x, w, label) in enumerate(sidecar_nodes):
        if index:
            s.line(
                x - 30,
                942,
                x - 10,
                942,
                color=COLORS["purple"],
                sw=2,
                marker="arrow",
            )
        pill(
            s,
            x,
            923,
            w,
            label,
            fill="#FFFFFF",
            color=COLORS["purple"],
            stroke="#CFC6F3",
            size=13.5,
        )
    footer(s, "方法级工作流对比 · 不包含未经验证的效率、成本或真实良率 KPI")
    return s.finish()


def figure_02(_: Facts) -> str:
    s = Svg()
    base(
        s,
        "TuneWise 双层 AI 架构",
        "生成式 AI 负责检索与解释；确定性工业 AI 负责检测、诊断、荐参、安全校验与受控执行",
        "02",
    )
    card(
        s,
        70,
        205,
        1780,
        300,
        fill="#FBFAFF",
        stroke="#CCC3FA",
        shadow=True,
    )
    s.rect(70, 205, 1780, 76, fill=COLORS["purple_soft"], stroke="none", rx=18)
    s.text(
        105,
        241,
        "飞书 Aily · 生成式 AI 协作层",
        size=29,
        weight=700,
        color=COLORS["purple"],
    )
    pill(
        s,
        1475,
        224,
        330,
        "检索 · 解释 · 追溯 · 问答",
        fill="#FFFFFF",
        color=COLORS["purple"],
        stroke="#C8BDF6",
        size=17,
    )
    top_nodes = [
        ("知识空间", "8 文件知识包"),
        ("知识检索（RAG）", "Top K = 5"),
        ("大语言模型（LLM）", "发布配置记录"),
        ("工程解释", "基于检索证据"),
        ("评委 / 工程问答", "自然语言协作"),
    ]
    top_xs = [110, 460, 810, 1160, 1510]
    for index, ((title, subtitle), x) in enumerate(zip(top_nodes, top_xs)):
        if index:
            s.line(
                x - 50,
                360,
                x - 12,
                360,
                color=COLORS["purple"],
                sw=2.4,
                marker="arrow",
            )
        center_node(
            s,
            x,
            315,
            300,
            92,
            title,
            subtitle=subtitle,
            fill="#FFFFFF",
            stroke="#D5CEF8",
            title_color=COLORS["purple"],
            title_size=20,
        )
    s.rect(
        105,
        432,
        1710,
        48,
        fill=COLORS["red_soft"],
        stroke="#F1C6CA",
        sw=1,
        rx=14,
    )
    s.text(
        960,
        456,
        "Aily 只负责知识检索与解释 · 不生成新参数 / 不创建 ConfirmedPlan / 不触发仿真验证 / 无 OPC-UA 写权限",
        size=18.5,
        color=COLORS["red"],
        weight=700,
        anchor="middle",
    )

    card(
        s,
        310,
        525,
        1300,
        100,
        fill="#FFFFFF",
        stroke="#AFC0F6",
        sw=2,
        rx=20,
        shadow=True,
    )
    s.text(
        815,
        555,
        "双层之间仅共享可追溯证据",
        size=17,
        color=COLORS["muted"],
        anchor="middle",
    )
    s.text(
        815,
        586,
        "版本化项目知识 + 固定 Demo 证据 + Process-aware Demo 证据",
        size=22,
        color=COLORS["blue_dark"],
        weight=700,
        anchor="middle",
    )
    pill(
        s,
        1325,
        544,
        245,
        "非实时控制接口",
        fill=COLORS["orange_soft"],
        color=COLORS["orange"],
        stroke="#E9BC7F",
        size=17,
    )
    s.path(
        "M 710 650 L 710 625",
        color=COLORS["blue"],
        sw=3,
        marker="arrow-blue",
    )
    s.path(
        "M 1210 525 L 1210 505",
        color=COLORS["purple"],
        sw=3,
        marker="arrow",
    )
    s.text(
        665,
        638,
        "Core 产出证据",
        size=16,
        color=COLORS["blue_dark"],
        anchor="end",
    )
    s.text(1255, 516, "Aily 只读检索", size=16, color=COLORS["purple"])

    card(
        s,
        70,
        650,
        1780,
        330,
        fill="#F9FBFF",
        stroke="#B9C7F6",
        shadow=True,
    )
    s.rect(70, 650, 1780, 76, fill=COLORS["blue_soft"], stroke="none", rx=18)
    s.text(
        105,
        686,
        "TuneWise 确定性工业 AI 核心",
        size=29,
        weight=700,
        color=COLORS["blue_dark"],
    )
    pill(
        s,
        1395,
        669,
        410,
        "检测 · 诊断 · 推荐 · 校验 · 仿真验证 · 受控执行",
        fill="#FFFFFF",
        color=COLORS["blue_dark"],
        stroke="#BAC8F5",
        size=16,
    )
    core_nodes = [
        "SPC\n异常检测",
        "工程特征\n提取",
        "AI 根因\n优先级",
        "历史参考\n案例检索",
        "安全调参\n候选生成",
        "参数安全\n校验",
        "工程师\n确认",
        "执行前\n仿真验证",
        "本地模拟设备\n受控执行",
    ]
    start_x = 106
    width = 173
    gap = 20
    for index, label in enumerate(core_nodes):
        x = start_x + index * (width + gap)
        if index:
            s.line(
                x - gap + 2,
                826,
                x - 4,
                826,
                color=COLORS["blue"],
                sw=2.2,
                marker="arrow-blue",
            )
        fill = "#FFFFFF"
        stroke = "#C9D3F4"
        color = COLORS["blue_dark"]
        dash = None
        if "安全" in label or "工程师" in label:
            fill, stroke, color = (
                COLORS["green_soft"],
                "#ABD7C0",
                COLORS["green"],
            )
        if "模拟设备" in label:
            fill, stroke, color, dash = (
                COLORS["orange_soft"],
                "#E8BD82",
                COLORS["orange"],
                "7 5",
            )
        card(
            s,
            x,
            770,
            width,
            112,
            fill=fill,
            stroke=stroke,
            sw=1.6,
            rx=14,
            dash=dash,
        )
        lines = label.split("\n")
        s.multiline(
            x + width / 2,
            798 if len(lines) == 2 else 812,
            lines,
            size=17.5,
            line_height=27,
            color=color,
            weight=700,
            anchor="middle",
        )
    s.text(
        107,
        928,
        "安全关键数值与状态由版本固定的模型、规则、服务端契约和人工确认共同约束",
        size=20,
        color=COLORS["muted"],
    )
    pill(
        s,
        1510,
        910,
        294,
        "仅本地模拟环境",
        fill=COLORS["orange_soft"],
        color=COLORS["orange"],
        size=17,
    )
    footer(s, "职责隔离：Aily 解释 Core 证据，但不向 Core 或设备发送控制指令")
    return s.finish()


def figure_03(f: Facts) -> str:
    s = Svg()
    base(
        s,
        "TuneWise 核心决策链",
        "异常与根因证据结合调机过程信息，筛选当前适用案例，再形成可校验、可确认的调参候选",
        "03",
    )
    lanes = [
        (205, 195, "数据与检测", COLORS["teal"], COLORS["teal_soft"]),
        (420, 225, "模型、案例与过程", COLORS["purple"], COLORS["purple_soft"]),
        (655, 335, "决策、验证与演示", COLORS["blue"], COLORS["blue_soft"]),
    ]
    for y, h, label, color, fill in lanes:
        card(s, 70, y, 1780, h, fill="#FFFFFF", stroke=COLORS["line"], shadow=True)
        s.rect(70, y, 190, h, fill=fill, stroke="none", rx=18)
        s.text(
            165,
            y + 38,
            label,
            size=17,
            color=color,
            weight=700,
            anchor="middle",
        )
        s.text(165, y + 75, "CORE", size=14, color=COLORS["muted"], weight=700, anchor="middle")

    row1 = [
        ("版本化测量数据", "Manifest + SHA-256"),
        ("数据完整性校验", "schema / raw / canonical"),
        ("SPC 异常检测", "保护路由"),
        ("工程特征提取", "50 fixed features"),
    ]
    row1_x = [310, 690, 1070, 1450]
    for i, ((title, sub), x) in enumerate(zip(row1, row1_x)):
        if i:
            s.line(
                x - 64,
                305,
                x - 14,
                305,
                color=COLORS["teal"],
                sw=2.5,
                marker="arrow",
            )
        center_node(
            s,
            x,
            258,
            320,
            94,
            title,
            subtitle=sub,
            fill="#FBFEFE",
            stroke="#B8DEDB",
            title_color=COLORS["teal"],
            title_size=19,
        )
    s.path(
        "M 1770 305 L 1810 305 L 1810 510 L 1770 510",
        color=COLORS["purple"],
        sw=2.6,
        marker="arrow",
    )

    row2 = [
        ("StandardScaler", "tw-preprocessing-v1"),
        ("Logistic Regression", "固定可解释分类排序 · tw-model-v1"),
        ("AI 根因优先级", "稳定 Top-3 + logit 证据"),
        ("当前适用案例", "历史参考案例检索 · structured KNN"),
    ]
    row2_x = [1450, 1070, 690, 310]
    for i, ((title, sub), x) in enumerate(zip(row2, row2_x)):
        if i:
            s.line(
                x + 378,
                525,
                x + 334,
                525,
                color=COLORS["purple"],
                sw=2.5,
                marker="arrow",
            )
        center_node(
            s,
            x,
            473,
            320,
            104,
            title,
            subtitle=sub,
            fill="#FCFBFF",
            stroke="#D2CBF4",
            title_color=COLORS["purple"],
            title_size=18.5,
        )
    s.path(
        "M 310 577 L 285 577 L 285 730 L 310 730",
        color=COLORS["blue"],
        sw=2.6,
        marker="arrow-blue",
    )

    row3 = [
        ("安全调参\n候选生成", "规则 + 案例证据"),
        ("参数安全\n校验", "ParameterSafetyValidator"),
        ("工程师\n确认", "AA_PROCESS_ENGINEER"),
        ("不可变\nConfirmedPlan", "VALID / STALE"),
        ("执行前\n仿真验证", "Replay · 基线复现"),
        ("本地模拟设备\n受控执行", "OPC-UA Sandbox"),
    ]
    row3_x = [310, 565, 820, 1075, 1330, 1585]
    for i, ((title, sub), x) in enumerate(zip(row3, row3_x)):
        if i:
            s.line(
                x - 25,
                730,
                x - 6,
                730,
                color=COLORS["blue"],
                sw=2.4,
                marker="arrow-blue",
            )
        fill = "#FBFCFF"
        stroke = "#C6D1F5"
        color = COLORS["blue_dark"]
        dash = None
        if "安全" in title or "工程师" in title:
            fill, stroke, color = (
                COLORS["green_soft"],
                "#ADD7C1",
                COLORS["green"],
            )
        if "模拟设备" in title:
            fill, stroke, color, dash = (
                COLORS["orange_soft"],
                "#E8BC80",
                COLORS["orange"],
                "7 5",
            )
        card(
            s,
            x,
            675,
            230,
            110,
            fill=fill,
            stroke=stroke,
            sw=1.7,
            rx=15,
            dash=dash,
        )
        lines = title.split("\n")
        s.multiline(
            x + 115,
            693,
            lines,
            size=18,
            line_height=27,
            color=color,
            weight=700,
            anchor="middle",
        )
        s.text(
            x + 115,
            760,
            sub,
            size=15.5,
            color=COLORS["muted"],
            anchor="middle",
        )

    card(s, 310, 585, 570, 48, fill=COLORS["purple_soft"], stroke="#C9C0F3", rx=12)
    s.text(595, 609, "调机过程信息：当前阶段 · 上一步调整 · 上一步结果", size=18, color=COLORS["purple"], weight=700, anchor="middle")
    s.path("M 410 585 L 410 577", color=COLORS["purple"], sw=2.4, marker="arrow")
    card(s, 910, 585, 905, 48, fill=COLORS["red_soft"], stroke="#EFC5C8", rx=12)
    s.text(1362, 609, "不进入 classifier / StandardScaler / Root Cause Top-3 · 不直接计算参数值", size=17.5, color=COLORS["red"], weight=700, anchor="middle")

    pill(s, 300, 810, 430, "共同条件：测量相同 · 根因同为 PLANE_TILT", fill="#FFFFFF", color=COLORS["blue_dark"], stroke="#BCCAF3", size=16)
    pill(s, 750, 810, 520, "两边均有：保守 -1 tick · 标准 -2 ticks · 全部 PASSED", fill=COLORS["green_soft"], color=COLORS["green"], stroke="#A7D4BC", size=16)
    pill(s, 1290, 810, 500, "结合调机步骤的决策演示 · SYNTHETIC", fill=COLORS["purple_soft"], color=COLORS["purple"], stroke="#C8BFF3", size=16)

    card(s, 300, 858, 720, 110, fill="#FFFFFF", stroke="#B9C8F2", rx=14)
    pill(s, 320, 873, 170, "A｜初始评估", fill=COLORS["blue_soft"], color=COLORS["blue_dark"], size=16)
    s.text(515, 892, "上一步调整：无", size=17, color=COLORS["muted"], weight=600)
    s.text(325, 928, f"当前适用案例  {f.process_a_case_id}", size=18.5, color=COLORS["blue_dark"], weight=700, family=MONO)
    s.text(325, 954, f"案例参考方案  pitch {f.process_a_ticks} ticks", size=18, color=COLORS["purple"], weight=700, family=MONO)

    card(s, 1045, 858, 770, 110, fill="#FFFFFF", stroke="#B9C8F2", rx=14)
    pill(s, 1065, 873, 205, "B｜调整后评估", fill=COLORS["blue_soft"], color=COLORS["blue_dark"], size=16)
    s.text(1290, 892, "上一步：pitch 0.250000 → 0.200000 · 未观察到显著改善", size=16.5, color=COLORS["muted"], weight=600)
    s.text(1070, 928, f"当前适用案例  {f.process_b_case_id}", size=18.5, color=COLORS["blue_dark"], weight=700, family=MONO)
    s.text(1070, 954, f"案例参考方案  pitch {f.process_b_ticks} ticks", size=18, color=COLORS["purple"], weight=700, family=MONO)

    footer(s, "事实边界：A/B 为合成调机过程演示；不代表舜宇真实 SOP、真实生产数据或真实调参准确率")
    return s.finish()


def figure_04(f: Facts) -> str:
    s = Svg()
    base(
        s,
        "安全调参决策流程",
        "模型不直接输出参数：根因、空间特征、当前偏差、方向规则与案例幅值共同约束候选",
        "04",
    )
    evidence = [
        ("根因证据", f"{f.top_root_cause} · score {f.score}"),
        ("当前空间特征", f"top_bottom = {f.top_bottom}"),
        ("当前参数偏差", f"pitch {f.pitch_current} · nominal 0.000000"),
        ("方向规则", "PLANE_TILT_PITCH_SAME_SIGN"),
        ("已审核案例幅值", "median evidence · -3 ticks"),
    ]
    ex = [70, 425, 780, 1135, 1490]
    for (title, sub), x in zip(evidence, ex):
        card(s, x, 212, 305, 112, fill="#FFFFFF", stroke="#C9D4EF", shadow=True)
        s.text(
            x + 20,
            242,
            title,
            size=17,
            color=COLORS["blue_dark"],
            weight=700,
        )
        s.text(
            x + 20,
            281,
            sub,
            size=17,
            color=COLORS["muted"],
            family=MONO if any(c.isdigit() for c in sub) else FONT,
        )
        s.path(
            f"M {x + 152} 324 L 960 395",
            color="#9EADCA",
            sw=1.8,
            marker="arrow",
            dash="5 5",
        )

    center_node(
        s,
        680,
        392,
        560,
        82,
        "安全调参候选生成",
        subtitle="确定性方向规则 + 幅值规则",
        fill=COLORS["blue_soft"],
        stroke="#AFC0F4",
        title_color=COLORS["blue_dark"],
        shadow=True,
    )
    s.line(
        960,
        474,
        960,
        514,
        color=COLORS["green"],
        sw=3,
        marker="arrow-green",
    )
    center_node(
        s,
        680,
        520,
        560,
        88,
        "参数安全校验",
        subtitle="ParameterSafetyValidator · 范围 / 网格 / 方向 / 最大变化 / hash",
        fill=COLORS["green_soft"],
        stroke="#9FD0B7",
        title_color=COLORS["green"],
        shadow=True,
    )
    pill(
        s,
        1280,
        545,
        470,
        "roll：证据不足（INSUFFICIENT_SUPPORT）→ 不生成候选",
        fill=COLORS["orange_soft"],
        color=COLORS["orange"],
        stroke="#E8BC7C",
        size=17,
    )

    candidates = [
        (
            70,
            "保守调整方案 · 已选择",
            f"pitch {f.pitch_current} → {f.pitch_target}",
            f"{f.selected_ticks} tick · PASSED",
            "CONSERVATIVE · 固定规则幅值",
            COLORS["green_soft"],
            "#8CC9AA",
            COLORS["green"],
        ),
        (
            665,
            "标准调整方案",
            f"pitch {f.pitch_current} → {f.standard_target}",
            f"{f.standard_ticks} ticks · PASSED",
            "STANDARD · 固定规则幅值 · 未选择",
            "#FFFFFF",
            "#C8D2E6",
            COLORS["blue_dark"],
        ),
        (
            1260,
            "案例参考方案",
            f"pitch {f.pitch_current} → {f.case_target}",
            f"{f.case_ticks} ticks · PASSED",
            "CASE_GUIDED · approved-001 / 002 / 011",
            "#FFFFFF",
            "#C8D2E6",
            COLORS["purple"],
        ),
    ]
    for index, (x, title, flow, ticks, note, fill, stroke, color) in enumerate(
        candidates
    ):
        s.path(
            f"M 960 608 L 960 636 L {x + 260} 636 L {x + 260} 664",
            color=COLORS["green"],
            sw=2,
            marker="arrow-green",
        )
        card(
            s,
            x,
            670,
            520,
            154,
            fill=fill,
            stroke=stroke,
            sw=2 if index == 0 else 1.5,
            shadow=True,
        )
        s.text(x + 24, 699, title, size=20, color=color, weight=700)
        s.text(
            x + 24,
            741,
            flow,
            size=22,
            color=COLORS["ink"],
            weight=700,
            family=MONO,
        )
        s.text(
            x + 24,
            778,
            ticks,
            size=18,
            color=color,
            weight=700,
            family=MONO,
        )
        s.text(x + 24, 807, note, size=16, color=COLORS["muted"])

    s.path(
        "M 330 824 L 330 860 L 620 860",
        color=COLORS["green"],
        sw=3,
        marker="arrow-green",
    )
    center_node(
        s,
        620,
        836,
        400,
        92,
        "工程师确认",
        subtitle="AA_PROCESS_ENGINEER · Human-in-the-loop",
        fill=COLORS["green_soft"],
        stroke="#91CBAA",
        title_color=COLORS["green"],
    )
    s.line(
        1020,
        882,
        1080,
        882,
        color=COLORS["green"],
        sw=3,
        marker="arrow-green",
    )
    center_node(
        s,
        1080,
        836,
        540,
        92,
        "不可变 ConfirmedPlan",
        subtitle=f"{f.confirmed_plan_id} · VALID",
        fill=COLORS["blue_soft"],
        stroke="#AFC0F4",
        title_color=COLORS["blue_dark"],
    )

    s.rect(
        70,
        956,
        1780,
        54,
        fill=COLORS["slate_soft"],
        stroke="#D3DAE5",
        rx=14,
    )
    s.text(
        960,
        983,
        "结论：模型只排序根因；参数由确定性规则 / 案例证据生成，并经参数安全校验与工程师确认",
        size=21,
        color=COLORS["ink"],
        weight=700,
        anchor="middle",
    )
    footer(s, "固定 Demo：三个候选均存在且通过校验；仅保守调整方案（CONSERVATIVE）-1 tick 被工程师确认")
    return s.finish()


def diamond(
    s: Svg,
    cx: float,
    cy: float,
    w: float,
    h: float,
    *,
    fill: str,
    stroke: str,
) -> None:
    points = (
        f"{cx},{cy - h / 2} "
        f"{cx + w / 2},{cy} "
        f"{cx},{cy + h / 2} "
        f"{cx - w / 2},{cy}"
    )
    s.raw(
        f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" '
        'stroke-width="2" filter="url(#shadow)"/>'
    )


def figure_05(_: Facts) -> str:
    s = Svg()
    base(
        s,
        "执行前仿真验证与设备安全门禁",
        "仿真验证通过不是自动写入许可：设备执行仍需 fail-closed 资格检查、受控 Method 与结果核对",
        "05",
    )
    top = [
        (55, 250, "已确认调参方案", "ConfirmedPlan · VALID"),
        (330, 250, "状态检查", "freshness / hash"),
        (605, 250, "安全复核", "ParameterSafetyValidator"),
        (880, 250, "基线复现", "canonical hash match"),
        (1155, 250, "调参方案仿真", "Replay · paired simulation"),
    ]
    for index, (x, y, title, sub) in enumerate(top):
        if index:
            s.line(
                x - 50,
                y + 53,
                x - 10,
                y + 53,
                color=COLORS["blue"],
                sw=2.5,
                marker="arrow-blue",
            )
        fill = COLORS["green_soft"] if index in {0, 2} else "#FFFFFF"
        stroke = "#A7D4BC" if index in {0, 2} else "#C4D0EA"
        color = COLORS["green"] if index in {0, 2} else COLORS["blue_dark"]
        center_node(
            s,
            x,
            y,
            245,
            106,
            title,
            subtitle=sub,
            fill=fill,
            stroke=stroke,
            title_color=color,
            title_size=18.5,
            shadow=True,
        )
    s.line(
        1400,
        303,
        1460,
        303,
        color=COLORS["blue"],
        sw=2.6,
        marker="arrow-blue",
    )
    diamond(
        s,
        1570,
        303,
        190,
        126,
        fill=COLORS["blue_soft"],
        stroke="#9FB2F0",
    )
    s.multiline(
        1570,
        278,
        ["仿真验证结果", "SUCCESS?"],
        size=18,
        line_height=28,
        color=COLORS["blue_dark"],
        weight=700,
        anchor="middle",
    )
    s.path(
        "M 1665 303 L 1710 303",
        color=COLORS["red"],
        sw=2.5,
        marker="arrow-red",
    )
    pill(
        s,
        1687,
        226,
        70,
        "未通过",
        fill=COLORS["red_soft"],
        color=COLORS["red"],
        size=16,
    )
    center_node(
        s,
        1720,
        265,
        145,
        76,
        "阻断",
        fill=COLORS["red_soft"],
        stroke="#E9B3B8",
        title_color=COLORS["red"],
        title_size=20,
    )
    s.path(
        "M 1570 366 L 1570 398 L 210 398 L 210 445",
        color=COLORS["green"],
        sw=2.8,
        marker="arrow-green",
    )
    pill(
        s,
        1498,
        372,
        84,
        "通过",
        fill=COLORS["green_soft"],
        color=COLORS["green"],
        size=16,
    )

    center_node(
        s,
        80,
        450,
        270,
        112,
        "设备执行资格检查",
        subtitle="仅允许 1 个参数发生变化",
        fill=COLORS["green_soft"],
        stroke="#9ED0B5",
        title_color=COLORS["green"],
        shadow=True,
    )
    s.line(
        350,
        506,
        395,
        506,
        color=COLORS["green"],
        sw=2.6,
        marker="arrow-green",
    )
    center_node(
        s,
        400,
        450,
        280,
        112,
        "设备身份与映射检查",
        subtitle="mapping / type / unit / access",
        fill=COLORS["green_soft"],
        stroke="#9ED0B5",
        title_color=COLORS["green"],
        title_size=18,
        shadow=True,
    )
    s.line(
        680,
        506,
        720,
        506,
        color=COLORS["green"],
        sw=2.6,
        marker="arrow-green",
    )

    card(
        s,
        730,
        420,
        1135,
        330,
        fill="#FFFFFF",
        stroke="#AFC0E9",
        sw=2,
        shadow=True,
    )
    s.text(
        770,
        460,
        "本地模拟设备受控执行",
        size=27,
        color=COLORS["blue_dark"],
        weight=700,
    )
    pill(
        s,
        1540,
        441,
        280,
        "仅受控 Method 写入",
        fill=COLORS["blue_soft"],
        color=COLORS["blue_dark"],
        size=17,
    )
    method_steps = [
        ("执行锁", "single lock"),
        ("幂等键", "same key"),
        ("当前值核对", "before write"),
        ("单参数写入", "controlled"),
        ("写后回读", "= target"),
        ("执行凭证", "immutable"),
    ]
    mx = [770, 945, 1120, 1295, 1470, 1645]
    for index, ((title, sub), x) in enumerate(zip(method_steps, mx)):
        if index:
            s.line(
                x - 28,
                601,
                x - 6,
                601,
                color=COLORS["blue"],
                sw=2.1,
                marker="arrow-blue",
            )
        fill = (
            COLORS["green_soft"]
            if title in {"写后回读", "执行凭证"}
            else "#F8FAFE"
        )
        stroke = "#ABD6BF" if fill == COLORS["green_soft"] else "#CFD7E8"
        color = (
            COLORS["green"] if fill == COLORS["green_soft"] else COLORS["blue_dark"]
        )
        center_node(
            s,
            x,
            548,
            155,
            106,
            title,
            subtitle=sub,
            fill=fill,
            stroke=stroke,
            title_color=color,
            title_size=16.5,
        )
    s.rect(
        770,
        680,
        1050,
        42,
        fill=COLORS["slate_soft"],
        stroke="#D2DAE6",
        rx=12,
    )
    s.text(
        1295,
        701,
        "普通 OPC-UA Variable 对客户端保持只读；缺少受控 Method 时禁止回退写入",
        size=17.5,
        color=COLORS["slate"],
        weight=700,
        anchor="middle",
    )

    card(
        s,
        80,
        790,
        820,
        170,
        fill=COLORS["orange_soft"],
        stroke="#E7BC82",
        shadow=True,
    )
    s.text(
        115,
        825,
        "异常路径 · 通信超时",
        size=21,
        color=COLORS["orange"],
        weight=700,
    )
    exception_nodes = [
        (115, "客户端超时"),
        (370, "UNKNOWN_OUTCOME"),
        (650, "只读结果核对"),
    ]
    for index, (x, label) in enumerate(exception_nodes):
        if index:
            s.line(
                x - 55,
                886,
                x - 10,
                886,
                color=COLORS["orange"],
                sw=2.3,
                marker="arrow-orange",
            )
        center_node(
            s,
            x,
            852,
            205,
            68,
            label,
            fill="#FFFFFF",
            stroke="#E8C898",
            title_color=COLORS["orange"],
            title_size=17.5,
        )
    s.text(
        115,
        940,
        "UNKNOWN_OUTCOME ≠ FAILED ≠ 自动重试 · 只读查询同一 idempotency key",
        size=17,
        color=COLORS["red"],
        weight=700,
    )

    card(
        s,
        940,
        790,
        925,
        170,
        fill="#FFFFFF",
        stroke="#E4C18E",
        shadow=True,
    )
    pill(
        s,
        990,
        817,
        285,
        "设备执行环境",
        fill=COLORS["slate_soft"],
        color=COLORS["slate"],
        size=17,
    )
    s.text(
        990,
        882,
        "仅本地模拟环境",
        size=34,
        color=COLORS["orange"],
        weight=700,
    )
    s.text(
        1415,
        882,
        "非真实生产线",
        size=28,
        color=COLORS["red"],
        weight=700,
    )
    s.text(
        990,
        928,
        "loopback 127.0.0.1 · LOCAL_ANONYMOUS_SANDBOX",
        size=17,
        color=COLORS["muted"],
        family=MONO,
    )
    footer(s, "仿真验证通过只解锁下一轮设备执行资格检查；它本身不触发设备写入，也不证明真实设备有效")
    return s.finish()


def label_value(
    s: Svg,
    x: float,
    y: float,
    label: str,
    value: str,
    *,
    value_color: str = COLORS["ink"],
    value_size: float = 21,
    mono: bool = False,
) -> None:
    s.text(x, y, label, size=16.5, color=COLORS["muted"], weight=600)
    s.text(
        x,
        y + 31,
        value,
        size=value_size,
        color=value_color,
        weight=700,
        family=MONO if mono else FONT,
    )


def figure_06(f: Facts) -> str:
    s = Svg()
    base(
        s,
        "tw-demo-task-001 固定 Demo 证据卡",
        "独立复核固定 Demo 的异常、根因、调参候选、工程师确认、执行前仿真验证与本地模拟设备执行",
        "06",
    )
    card(
        s,
        70,
        205,
        1780,
        785,
        fill="#FFFFFF",
        stroke="#BCC8E2",
        shadow=True,
    )
    s.rect(70, 205, 1780, 105, fill=COLORS["ink"], stroke="none", rx=18)
    s.text(
        110,
        242,
        f"任务 · {f.task_id}",
        size=29,
        color="#FFFFFF",
        weight=700,
        family=MONO,
    )
    s.text(
        110,
        279,
        f"资产 {f.asset_id}  ·  批次 {f.batch_id}  ·  {f.sample_count} 条合成观测",
        size=18,
        color="#C8D5E8",
        family=MONO,
    )
    pill(
        s,
        1510,
        238,
        285,
        "固定 DEMO 证据",
        fill="#203A59",
        color="#8FE2D3",
        stroke="#3D5B79",
        size=17,
    )

    columns = [
        (105, 340, 520, 535, "01 · 异常与诊断", COLORS["purple"]),
        (700, 340, 520, 535, "02 · 调参候选与确认", COLORS["blue"]),
        (1295, 340, 520, 535, "03 · 仿真验证与执行", COLORS["teal"]),
    ]
    for x, y, w, h, title, color in columns:
        card(s, x, y, w, h, fill="#FAFBFD", stroke="#D5DDE9", rx=16)
        s.text(x + 24, y + 34, title, size=18, color=color, weight=700)
        s.line(x + 24, y + 65, x + w - 24, y + 65, color="#D7DEEA", sw=1.5)

    pill(
        s,
        130,
        430,
        240,
        f.anomaly,
        fill=COLORS["orange_soft"],
        color=COLORS["orange"],
        stroke="#E8BD80",
        size=18,
    )
    label_value(
        s,
        130,
        505,
        "AI 根因优先级 · Top-1",
        f.top_root_cause,
        value_color=COLORS["purple"],
        value_size=28,
        mono=True,
    )
    label_value(
        s,
        390,
        505,
        "相对排序分数",
        f.score,
        value_color=COLORS["purple"],
        value_size=28,
        mono=True,
    )
    s.rect(
        130,
        582,
        470,
        50,
        fill=COLORS["red_soft"],
        stroke="#EFC4C7",
        rx=12,
    )
    s.text(
        365,
        607,
        "相对排序分数 ≠ 校准后的故障概率",
        size=18,
        color=COLORS["red"],
        weight=700,
        anchor="middle",
    )
    s.text(
        130,
        670,
        "关键工程特征",
        size=17,
        color=COLORS["muted"],
        weight=700,
    )
    features = [
        f"top_bottom_difference   {f.top_bottom}",
        f"left_right_difference   {f.left_right}",
        f"diagonal_difference    {f.diagonal}",
        f"pitch_mean              {f.pitch_current}",
        "roll_mean              -0.200000",
    ]
    s.multiline(
        130,
        706,
        features,
        size=17,
        line_height=31,
        color=COLORS["ink"],
        family=MONO,
    )

    label_value(
        s,
        725,
        430,
        "已选调参候选",
        f.candidate_id,
        value_color=COLORS["blue_dark"],
        value_size=18,
        mono=True,
    )
    s.text(
        725,
        521,
        f"pitch  {f.pitch_current}  →  {f.pitch_target}",
        size=28,
        color=COLORS["ink"],
        weight=700,
        family=MONO,
    )
    pill(
        s,
        725,
        554,
        190,
        "保守调整方案",
        fill=COLORS["blue_soft"],
        color=COLORS["blue_dark"],
        size=17,
    )
    pill(
        s,
        930,
        554,
        125,
        "-1 tick",
        fill="#FFFFFF",
        color=COLORS["blue_dark"],
        stroke="#B7C5F2",
        size=17,
    )
    pill(
        s,
        1070,
        554,
        110,
        "PASSED",
        fill=COLORS["green_soft"],
        color=COLORS["green"],
        size=17,
    )
    label_value(
        s,
        725,
        635,
        "参数安全校验",
        "tw-parameter-safety-v1 · PASSED",
        value_color=COLORS["green"],
        value_size=19,
        mono=True,
    )
    label_value(
        s,
        725,
        724,
        "工程师确认",
        "AA_PROCESS_ENGINEER",
        value_color=COLORS["green"],
        value_size=21,
        mono=True,
    )
    s.text(
        725,
        811,
        f"ConfirmedPlan · {f.confirmed_plan_id}",
        size=17,
        color=COLORS["muted"],
        family=MONO,
    )
    s.text(
        725,
        842,
        f"Plan SHA-256 prefix · {f.confirmed_plan_hash[:12]}",
        size=17,
        color=COLORS["muted"],
        family=MONO,
    )

    label_value(
        s,
        1320,
        430,
        "基线复现",
        f.baseline_status,
        value_color=COLORS["green"],
        value_size=28,
        mono=True,
    )
    label_value(
        s,
        1570,
        430,
        "仿真验证结果",
        f.replay_status,
        value_color=COLORS["green"],
        value_size=28,
        mono=True,
    )
    s.rect(
        1320,
        530,
        470,
        56,
        fill=COLORS["orange_soft"],
        stroke="#E8BD80",
        rx=12,
    )
    s.text(
        1555,
        558,
        "仿真验证通过 ≠ 真实生产良率提升",
        size=17,
        color=COLORS["orange"],
        weight=700,
        anchor="middle",
    )
    label_value(
        s,
        1320,
        630,
        "设备执行环境",
        f.execution_surface,
        value_color=COLORS["orange"],
        value_size=20,
        mono=True,
    )
    label_value(
        s,
        1320,
        718,
        "本地执行状态",
        f"{f.execution_status} · readback {f.actual_after}",
        value_color=COLORS["green"],
        value_size=20,
        mono=True,
    )
    s.text(
        1320,
        811,
        f"Replay SHA-256 prefix · {f.replay_hash[:12]}",
        size=17,
        color=COLORS["muted"],
        family=MONO,
    )
    s.text(
        1320,
        842,
        f"Receipt SHA-256 prefix · {f.receipt_hash[:12]}",
        size=17,
        color=COLORS["muted"],
        family=MONO,
    )

    boundary = [
        (
            105,
            900,
            520,
            "合成固定 Demo · 非生产数据",
            COLORS["purple_soft"],
            COLORS["purple"],
        ),
        (
            700,
            900,
            520,
            "人在回路 · 不可变确认方案",
            COLORS["green_soft"],
            COLORS["green"],
        ),
        (
            1295,
            900,
            520,
            "本地 OPC-UA Sandbox · 非真实设备",
            COLORS["orange_soft"],
            COLORS["orange"],
        ),
    ]
    for x, y, w, text_value, fill, color in boundary:
        s.rect(x, y, w, 48, fill=fill, stroke="none", rx=12)
        s.text(
            x + w / 2,
            y + 24,
            text_value,
            size=17,
            color=color,
            weight=700,
            anchor="middle",
        )
    footer(
        s,
        "固定 Demo 与 Process-aware A/B 演示相互独立 · 版本：tw-model-v1 / tw-rules-v1 / tw-simulator-v1",
    )
    return s.finish()


def figure_07(_: Facts) -> str:
    s = Svg()
    base(
        s,
        "飞书 Aily 工程解释工作流",
        "基于 8 文件版本化知识包，通过知识检索（RAG）与大语言模型生成有证据边界的工程解释",
        "07",
    )
    card(
        s,
        70,
        205,
        1040,
        760,
        fill="#FBFAFF",
        stroke="#D0C8F5",
        shadow=True,
    )
    s.text(
        110,
        242,
        "有证据边界的工程解释工作流",
        size=27,
        color=COLORS["purple"],
        weight=700,
    )
    pill(
        s,
        775,
        222,
        290,
        "工作流逻辑示意",
        fill="#FFFFFF",
        color=COLORS["purple"],
        stroke="#CFC6F3",
        size=16,
    )
    workflow = [
        ("评委 / 工程师提问", "自然语言问题"),
        ("开始", "输入用户问题"),
        ("知识检索（RAG）", "Top K = 5 · threshold off"),
        ("TuneWise 工程知识", "版本化项目知识 + 固定演示证据"),
        ("大语言模型（LLM）", "基于检索结果组织回答"),
        ("工程解释", "检索 · 解释 · 追溯 · 问答"),
    ]
    wy = [288, 392, 496, 600, 704, 808]
    for index, ((title, sub), y) in enumerate(zip(workflow, wy)):
        if index:
            s.line(
                590,
                y - 26,
                590,
                y - 8,
                color=COLORS["purple"],
                sw=2.6,
                marker="arrow",
            )
        fill = COLORS["purple_soft"] if index in {2, 4} else "#FFFFFF"
        stroke = "#C7BDF1" if index in {2, 4} else "#D5DDE9"
        color = COLORS["purple"] if index in {2, 4} else COLORS["ink"]
        center_node(
            s,
            250,
            y,
            680,
            76,
            title,
            subtitle=sub,
            fill=fill,
            stroke=stroke,
            title_color=color,
            title_size=20,
        )

    card(
        s,
        1150,
        205,
        700,
        760,
        fill="#FFFFFF",
        stroke="#C4CFE6",
        shadow=True,
    )
    s.text(
        1190,
        242,
        "8 文件知识包",
        size=27,
        color=COLORS["blue_dark"],
        weight=700,
    )
    s.text(
        1190,
        280,
        "TuneWise Engineering Knowledge · 8 / 8 已启用",
        size=18,
        color=COLORS["muted"],
    )
    files = [
        "项目概览",
        "架构与双层 AI",
        "诊断与参数安全",
        "执行前仿真验证与 OPC-UA 安全",
        "固定 Demo 证据",
        "事实边界与 FAQ",
        "评委指南",
        "调机过程 Demo 证据",
    ]
    for index, name in enumerate(files, start=1):
        y = 306 + (index - 1) * 55
        card(s, 1190, y, 620, 44, fill="#F8FAFE", stroke="#D6DEEA", rx=11)
        s.circle(1221, y + 22, 15, fill=COLORS["blue"])
        s.text(
            1221,
            y + 22,
            f"{index:02d}",
            size=13,
            color="#FFFFFF",
            weight=700,
            anchor="middle",
        )
        s.text(1252, y + 22, name, size=17.5, color=COLORS["ink"], weight=600)

    statuses = [
        (1190, 760, 295, "知识包", "8 / 8"),
        (1505, 760, 305, "原有安全硬门禁", "PASS"),
        (1190, 838, 295, "调机过程问答（Process-aware QA）", "PASS"),
        (1505, 838, 305, "发布环境", "PASS"),
    ]
    for x, y, w, title, result in statuses:
        card(
            s,
            x,
            y,
            w,
            66,
            fill=COLORS["green_soft"],
            stroke="#A4D1B9",
            rx=14,
        )
        s.text(
            x + w / 2,
            y + 21,
            title,
            size=14.5,
            color=COLORS["green"],
            weight=700,
            anchor="middle",
        )
        s.text(
            x + w / 2,
            y + 46,
            result,
            size=17.5,
            color=COLORS["green"],
            weight=700,
            anchor="middle",
            family=MONO,
        )
    s.rect(
        1150,
        925,
        700,
        40,
        fill=COLORS["red_soft"],
        stroke="#EEC4C7",
        rx=12,
    )
    s.text(
        1500,
        945,
        "固定 / 版本化证据 RAG · 无实时控制权限",
        size=16.5,
        color=COLORS["red"],
        weight=700,
        anchor="middle",
    )
    footer(s, "人工 UI / 会话验收：8/8 · Legacy Safety PASS · Process-aware QA PASS · Published PASS")
    return s.finish()


def figure_05_runtime(_: Facts) -> str:
    s = Svg()
    base(
        s,
        "Fixed Demo 真实运行界面",
        "tw-demo-task-001 从异常诊断到本地模拟设备执行的真实浏览器运行画面",
        "05",
    )
    screenshot_panel(
        s,
        70,
        200,
        850,
        340,
        "①",
        "异常与根因判断 · PLANE_TILT Top-1 · 相对排序分数 0.997781",
        RUNTIME_SCREENSHOTS / "fixed-01-root-cause-top1.png",
        accent=COLORS["purple"],
    )
    screenshot_panel(
        s,
        950,
        200,
        900,
        340,
        "②",
        "保守调整方案 · pitch 0.250000 → 0.200000 · -1 tick · PASSED",
        RUNTIME_SCREENSHOTS / "fixed-02-selected-conservative-candidate.png",
        accent=COLORS["blue"],
    )
    screenshot_panel(
        s,
        70,
        565,
        850,
        170,
        "③",
        "工程师确认 · ConfirmedPlan · VALID",
        RUNTIME_SCREENSHOTS / "fixed-03-confirmed-plan.png",
        accent=COLORS["green"],
    )
    screenshot_panel(
        s,
        70,
        755,
        850,
        130,
        "④",
        "执行前仿真验证 · 基线复现与 SUCCESS",
        RUNTIME_SCREENSHOTS / "fixed-04-replay-result.png",
        accent=COLORS["teal"],
    )
    screenshot_panel(
        s,
        950,
        565,
        900,
        320,
        "⑤",
        "本地模拟设备执行 · SUCCEEDED / readback 0.200000",
        RUNTIME_SCREENSHOTS / "fixed-05-device-receipt.png",
        accent=COLORS["orange"],
    )

    s.rect(70, 905, 1780, 48, fill=COLORS["slate_soft"], stroke="#CDD6E3", rx=12)
    chain = ["工程师确认", "执行前仿真验证", "设备执行资格检查", "本地模拟设备执行"]
    centers = [330, 750, 1170, 1590]
    for index, (label, center) in enumerate(zip(chain, centers)):
        if index:
            s.line(centers[index - 1] + 120, 929, center - 120, 929, color=COLORS["slate"], sw=2.2, marker="arrow")
        s.text(center, 929, label, size=18, color=COLORS["slate"], weight=700, anchor="middle")

    s.rect(70, 970, 1780, 48, fill=COLORS["orange_soft"], stroke="#E9BD80", rx=12)
    s.text(
        960,
        994,
        "真实运行的软件界面 · 合成固定 Demo + 本地 OPC-UA 模拟环境 · 不代表真实生产设备或产线效果",
        size=18,
        color=COLORS["orange"],
        weight=700,
        anchor="middle",
    )
    footer(s, "真实页面像素来自 1440 × 1100 Playwright 复采；精确证据继续保留在正文表格")
    return s.finish()


def _process_scenario_panel(
    s: Svg,
    *,
    x: float,
    title: str,
    path_source: Path,
    candidate_source: Path,
    context_crop: tuple[float, float, float, float],
    eligible_crop: tuple[float, float, float, float],
    accent: str,
) -> None:
    card(s, x, 425, 850, 470, fill="#FFFFFF", stroke="#C6D6D5", rx=14, shadow=True)
    s.rect(x, 425, 850, 46, fill="#EEF7F6", stroke="none", rx=14)
    s.rect(x, 458, 850, 13, fill="#EEF7F6", stroke="none", rx=0)
    s.circle(x + 27, 448, 15, fill=accent)
    s.text(x + 27, 448, title[0], size=16, color="#FFFFFF", weight=700, anchor="middle")
    s.text(x + 52, 448, title, size=19, color=COLORS["ink"], weight=700)
    fragments = [
        (483, 110, path_source, context_crop),
        (605, 150, path_source, eligible_crop),
        (767, 112, candidate_source, None),
    ]
    for y, h, source, crop in fragments:
        s.rect(x + 14, y, 822, h, fill="#F7FAFA", stroke="#D4E0DF", rx=4)
        if crop is None:
            s.image(x + 14, y, 822, h, source)
        else:
            s.image_crop(x + 14, y, 822, h, source, crop)


def figure_06_process_runtime(_: Facts) -> str:
    s = Svg()
    base(
        s,
        "结合调机步骤的决策演示",
        "异常判断相同，调机过程不同，当前适用案例与案例参考方案也会不同",
        "06",
    )
    shared = RUNTIME_SCREENSHOTS / "process-01-shared-evidence.png"
    card(s, 70, 195, 1780, 210, fill="#FFFFFF", stroke="#C6D6D5", rx=14, shadow=True)
    s.circle(102, 219, 15, fill=COLORS["teal"])
    s.text(102, 219, "①", size=15, color="#FFFFFF", weight=700, anchor="middle")
    s.text(130, 219, "共同条件 · 测量数据相同 / PLANE_TILT Top-1 相同", size=19, color=COLORS["ink"], weight=700)
    s.image_crop(84, 244, 1752, 147, shared, (0, 0, 1338, 150))

    _process_scenario_panel(
        s,
        x=70,
        title="A｜初始评估",
        path_source=RUNTIME_SCREENSHOTS / "process-02-scenario-a-path.png",
        candidate_source=RUNTIME_SCREENSHOTS / "process-03-scenario-a-candidate.png",
        context_crop=(18, 172, 623, 118),
        eligible_crop=(18, 302, 623, 160),
        accent=COLORS["teal"],
    )
    _process_scenario_panel(
        s,
        x=1000,
        title="B｜调整后评估",
        path_source=RUNTIME_SCREENSHOTS / "process-04-scenario-b-path.png",
        candidate_source=RUNTIME_SCREENSHOTS / "process-05-scenario-b-candidate.png",
        context_crop=(18, 172, 623, 129),
        eligible_crop=(18, 313, 623, 160),
        accent=COLORS["blue_dark"],
    )

    s.rect(70, 913, 1780, 70, fill="#FFFFFF", stroke="#C6D6D5", rx=12)
    s.circle(102, 948, 15, fill=COLORS["green"])
    s.text(102, 948, "④", size=15, color="#FFFFFF", weight=700, anchor="middle")
    s.text(
        130,
        948,
        "保守 -1 tick｜标准 -2 ticks｜参数安全校验 PASSED",
        size=18,
        color=COLORS["green"],
        weight=700,
    )
    s.image_crop(
        970,
        920,
        858,
        56,
        RUNTIME_SCREENSHOTS / "process-06-invariant-band.png",
        (0, 0, 1338, 130),
    )
    s.rect(70, 995, 1780, 38, fill=COLORS["orange_soft"], stroke="#E9BD80", rx=10)
    s.text(
        960,
        1014,
        "真实运行的软件界面 · 合成调机过程数据（synthetic fixtures） · 不代表舜宇真实 SOP 或真实生产调参准确率",
        size=16.5,
        color=COLORS["orange"],
        weight=700,
        anchor="middle",
    )
    footer(s, "相同根因 + 不同调机过程 → 不同适用案例 → 不同案例参考方案")
    return s.finish()


def figure_07_aily_runtime(_: Facts) -> str:
    s = Svg()
    base(
        s,
        "飞书 Aily 工程解释｜Workflow + 真实问答",
        "使用已发布应用的真实界面像素；当前截图回答固定 Demo 的 PLANE_TILT 问题，不伪装为 Process-aware Q5",
        "07",
    )
    screenshot_panel(
        s,
        70,
        205,
        700,
        705,
        "①",
        "已发布工作流 · 真实截图",
        AILY_SCREENSHOT,
        crop=(150, 330, 600, 610),
        accent=COLORS["purple"],
    )
    screenshot_panel(
        s,
        790,
        205,
        720,
        705,
        "②",
        "固定 Demo 工程问答 · 真实截图",
        AILY_SCREENSHOT,
        crop=(880, 575, 550, 650),
        accent=COLORS["blue"],
    )
    card(s, 1530, 205, 320, 705, fill="#FFFFFF", stroke="#C4CFE6", rx=14, shadow=True)
    s.text(1560, 242, "人工验收状态", size=24, color=COLORS["purple"], weight=700)
    s.text(1560, 277, "Manual UI / conversational", size=14, color=COLORS["muted"], family=MONO)
    status_items = [
        ("Live Knowledge Pack", "8 / 8"),
        ("Legacy Safety Hard Gates", "PASS"),
        ("Process-aware QA", "PASS"),
        ("Published Environment", "PASS"),
    ]
    for index, (label, value) in enumerate(status_items):
        y = 315 + index * 105
        card(s, 1555, y, 270, 84, fill=COLORS["green_soft"], stroke="#A4D1B9", rx=12)
        s.text(1690, y + 25, label, size=14, color=COLORS["green"], weight=700, anchor="middle")
        s.text(1690, y + 57, value, size=20, color=COLORS["green"], weight=700, anchor="middle", family=MONO)
    s.rect(1555, 755, 270, 124, fill=COLORS["red_soft"], stroke="#EABFC3", rx=12)
    s.multiline(
        1690,
        776,
        ["非 Process-aware Q5", "非实时 Runtime API", "无 OPC-UA 写权限"],
        size=15,
        line_height=31,
        color=COLORS["red"],
        weight=700,
        anchor="middle",
    )
    s.rect(70, 932, 1780, 72, fill=COLORS["slate_soft"], stroke="#CDD6E3", rx=12)
    s.text(105, 958, "截图问题范围", size=16, color=COLORS["muted"], weight=700)
    s.text(105, 983, "tw-demo-task-001 为什么把 PLANE_TILT 排在第一？", size=20, color=COLORS["ink"], weight=700)
    pill(s, 1460, 949, 350, "固定 Demo 问答 · 非 Q5", fill=COLORS["red_soft"], color=COLORS["red"], stroke="#EABFC3", size=16)
    footer(s, "Aily 负责知识检索与工程解释；不生成新参数、不创建 ConfirmedPlan、不触发仿真验证或设备执行")
    return s.finish()


def status_row(
    s: Svg,
    x: float,
    y: float,
    label: str,
    value: str,
    *,
    value_color: str,
    value_fill: str,
    value_width: float = 230,
) -> None:
    s.text(x, y, label, size=19, color=COLORS["ink"], weight=600)
    pill(
        s,
        x + 535 - value_width,
        y - 19,
        value_width,
        value,
        fill=value_fill,
        color=value_color,
        size=16,
    )


def figure_08(f: Facts) -> str:
    s = Svg()
    base(
        s,
        "验证与证据总结",
        "工程自动化、浏览器演示、Aily 人工验收与当前验证边界分开呈现",
        "08",
    )
    cards = [
        (70, 210, "A · 工程自动化验证", "当前全量", COLORS["blue"]),
        (980, 210, "B · Demo 浏览器验证", "浏览器人工验收", COLORS["teal"]),
        (70, 595, "C · Aily 人工验收", "界面 / 对话验收", COLORS["purple"]),
        (980, 595, "D · 当前验证边界", "事实边界", COLORS["orange"]),
    ]
    for x, y, title, kind, color in cards:
        card(s, x, y, 870, 340, fill="#FFFFFF", stroke="#CCD5E5", shadow=True)
        s.text(x + 34, y + 43, title, size=28, color=color, weight=700)
        pill(
            s,
            x + 555,
            y + 24,
            275,
            kind,
            fill=COLORS["slate_soft"],
            color=COLORS["slate"],
            size=15,
        )
        s.line(
            x + 34,
            y + 82,
            x + 836,
            y + 82,
            color="#D9E0EB",
            sw=1.5,
        )

    s.text(
        105,
        327,
        "当前全量验证 · 2026-08-11",
        size=23,
        color=COLORS["blue_dark"],
        weight=700,
        family=MONO,
    )
    status_row(
        s,
        105,
        378,
        "Backend 全量",
        f"{f.backend_tests} / {f.backend_tests} PASS",
        value_color=COLORS["green"],
        value_fill=COLORS["green_soft"],
    )
    status_row(
        s,
        105,
        427,
        "Frontend 全量",
        f"{f.frontend_tests} / {f.frontend_tests} PASS",
        value_color=COLORS["green"],
        value_fill=COLORS["green_soft"],
    )
    status_row(
        s,
        105,
        476,
        "工程生成与事实硬门禁",
        "PASS",
        value_color=COLORS["green"],
        value_fill=COLORS["green_soft"],
    )
    s.text(
        105,
        522,
        "历史 433 / 40 已降级为旧 commit 证据，不作为本图主验证数字",
        size=17,
        color=COLORS["orange"],
        weight=700,
    )

    status_row(
        s,
        1015,
        332,
        "固定 Demo 浏览器 QA",
        "PASS",
        value_color=COLORS["green"],
        value_fill=COLORS["green_soft"],
    )
    status_row(
        s,
        1015,
        381,
        "调机过程 Demo 浏览器验收",
        "PASS",
        value_color=COLORS["green"],
        value_fill=COLORS["green_soft"],
    )
    status_row(
        s,
        1015,
        430,
        "桌面端 / 移动端",
        "PASS",
        value_color=COLORS["green"],
        value_fill=COLORS["green_soft"],
    )
    status_row(
        s,
        1015,
        479,
        "固定 Demo 本地执行回读",
        "0.200000",
        value_color=COLORS["green"],
        value_fill=COLORS["green_soft"],
    )
    s.text(
        1015,
        522,
        "Fixed Demo 与 Process-aware Demo 独立验收，不拼成生产案例",
        size=17,
        color=COLORS["orange"],
        weight=700,
    )

    status_row(
        s,
        105,
        717,
        "在线知识包（Live）",
        "8 / 8",
        value_color=COLORS["green"],
        value_fill=COLORS["green_soft"],
    )
    status_row(
        s,
        105,
        766,
        "原有安全硬门禁",
        "PASS",
        value_color=COLORS["green"],
        value_fill=COLORS["green_soft"],
    )
    status_row(
        s,
        105,
        815,
        "调机过程问答",
        "PASS",
        value_color=COLORS["green"],
        value_fill=COLORS["green_soft"],
    )
    status_row(
        s,
        105,
        864,
        "发布环境",
        "PASS",
        value_color=COLORS["green"],
        value_fill=COLORS["green_soft"],
    )
    s.text(
        105,
        907,
        "Manual UI / conversational acceptance validation · 非自动 benchmark",
        size=17,
        color=COLORS["purple"],
        weight=700,
    )

    status_row(
        s,
        1015,
        695,
        "固定 Demo",
        "SYNTHETIC",
        value_color=COLORS["orange"],
        value_fill=COLORS["orange_soft"],
        value_width=250,
    )
    status_row(
        s,
        1015,
        738,
        "Process-aware Demo",
        "SYNTHETIC",
        value_color=COLORS["orange"],
        value_fill=COLORS["orange_soft"],
        value_width=250,
    )
    status_row(
        s,
        1015,
        781,
        "设备执行",
        "LOCAL SANDBOX",
        value_color=COLORS["orange"],
        value_fill=COLORS["orange_soft"],
        value_width=250,
    )
    status_row(
        s,
        1015,
        824,
        "真实生产数据 / 业务效果",
        "NOT VALIDATED",
        value_color=COLORS["red"],
        value_fill=COLORS["red_soft"],
        value_width=250,
    )
    status_row(
        s,
        1015,
        867,
        "公开真实数据边界审查",
        "NO-GO",
        value_color=COLORS["red"],
        value_fill=COLORS["red_soft"],
        value_width=250,
    )
    s.text(1015, 914, "LOROS：真实 MTF / SFR / ROI 可追溯，但与 AA 调机语义不匹配", size=16.5, color=COLORS["red"], weight=700)

    s.rect(
        70,
        965,
        1780,
        50,
        fill=COLORS["slate_soft"],
        stroke="#D1D9E5",
        rx=14,
    )
    s.text(
        960,
        990,
        "证据类型必须随主张一起呈现：自动化验证 ≠ 人工验收 ≠ 合成演示 ≠ 真实生产验证",
        size=20,
        color=COLORS["slate"],
        weight=700,
        anchor="middle",
    )
    footer(
        s,
        "公开真实数据审查 NO-GO 表示语义不匹配；不等于真实 AA 验证 PASS",
    )
    return s.finish()


def main() -> None:
    facts = load_facts()
    validate_runtime_screenshot_evidence()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    figures = [
        ("01_before_after.svg", figure_01(facts)),
        ("02_dual_layer_ai_architecture.svg", figure_02(facts)),
        ("03_core_pipeline.svg", figure_03(facts)),
        ("04_safe_parameter_decision.svg", figure_04(facts)),
        ("05_replay_opcua_safety.svg", figure_05_runtime(facts)),
        ("06_demo_evidence_card.svg", figure_06_process_runtime(facts)),
        ("07_aily_rag_workflow.svg", figure_07_aily_runtime(facts)),
        ("08_validation_summary.svg", figure_08(facts)),
    ]
    for name, content in figures:
        (OUTPUT / name).write_text(content, encoding="utf-8", newline="\n")
        print(f"generated {name}")


if __name__ == "__main__":
    main()
