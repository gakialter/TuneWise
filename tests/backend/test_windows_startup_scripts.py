from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows cmd.exe contract")
ROOT = Path(__file__).resolve().parents[2]


def _wait_for_port(port: int, process: subprocess.Popen, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"process exited before port {port}: {process.returncode}")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.1)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise AssertionError(f"port {port} did not become ready")


def _port_is_closed(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.1)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def _stop_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.CTRL_BREAK_EVENT)
        process.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        process.wait(timeout=10)


def _start(script: str, database: Path | None = None) -> subprocess.Popen:
    environment = os.environ.copy()
    if database is not None:
        environment["TUNEWISE_DATABASE_PATH"] = str(database)
    return subprocess.Popen(
        ["cmd.exe", "/d", "/c", str(ROOT / script)],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )


@pytest.mark.parametrize(
    "script",
    ("start-tunewise-opcua-demo.cmd", "start-tunewise-opcua-sandbox.cmd"),
)
def test_opcua_cmd_requires_repository_venv_and_never_uses_path_python(
    tmp_path: Path, script: str
) -> None:
    isolated = tmp_path / "path with spaces"
    isolated.mkdir()
    shutil.copy2(ROOT / script, isolated / script)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    marker = tmp_path / "path-python-was-used"
    (fake_bin / "python.cmd").write_text(
        f"@echo off\r\necho used>\"{marker}\"\r\nexit /b 91\r\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin)

    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", str(isolated / script)],
        cwd=isolated,
        env=environment,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert completed.returncode == 2
    assert "Missing virtual environment Python" in completed.stderr
    assert "py -3.12 -m venv .venv" in completed.stderr
    assert not marker.exists()


def test_sandbox_cmd_starts_on_loopback_and_ctrl_break_stops_it(tmp_path: Path) -> None:
    process = _start("start-tunewise-opcua-sandbox.cmd")
    try:
        _wait_for_port(4841, process)
    finally:
        _stop_process_tree(process)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not _port_is_closed(4841):
        time.sleep(0.1)
    assert _port_is_closed(4841)


def test_demo_cmd_requires_sandbox_then_starts_web_and_cleans_both(tmp_path: Path) -> None:
    process = _start("start-tunewise-opcua-demo.cmd", tmp_path / "demo.db")
    try:
        _wait_for_port(4841, process)
        _wait_for_port(8000, process)
    finally:
        _stop_process_tree(process)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and (
        not _port_is_closed(4841) or not _port_is_closed(8000)
    ):
        time.sleep(0.1)
    assert _port_is_closed(4841)
    assert _port_is_closed(8000)


def test_demo_cmd_fails_cleanly_when_sandbox_port_is_occupied(tmp_path: Path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        blocker.bind(("127.0.0.1", 4841))
        blocker.listen(1)
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", str(ROOT / "start-tunewise-opcua-demo.cmd")],
            cwd=ROOT,
            env={**os.environ, "TUNEWISE_DATABASE_PATH": str(tmp_path / "blocked.db")},
            text=True,
            capture_output=True,
            timeout=10,
        )

    assert completed.returncode != 0
    assert "127.0.0.1:4841" in (completed.stdout + completed.stderr)
    assert _port_is_closed(8000)


def test_ordinary_start_cmd_behavior_still_starts_web(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["PATH"] = str(ROOT / ".venv" / "Scripts") + os.pathsep + environment["PATH"]
    environment["TUNEWISE_DATABASE_PATH"] = str(tmp_path / "ordinary.db")
    process = subprocess.Popen(
        ["cmd.exe", "/d", "/c", str(ROOT / "start-tunewise.cmd")],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        _wait_for_port(8000, process)
        assert _port_is_closed(4841)
    finally:
        _stop_process_tree(process)
    assert _port_is_closed(8000)
