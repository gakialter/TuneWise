from __future__ import annotations

import os
import socket
import subprocess
import sys
import time


ENDPOINT = "opc.tcp://127.0.0.1:4841/tunewise/opcua-sandbox/"
HOST = "127.0.0.1"
PORT = 4841


def _port_is_open(port: int = PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        return probe.connect_ex((HOST, port)) == 0


def _wait_for_sandbox(process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"OPC-UA sandbox 启动失败，退出码 {process.returncode}。"
            )
        if _port_is_open():
            return
        time.sleep(0.1)
    raise RuntimeError("OPC-UA sandbox 未在 15 秒内监听本地端口。")


def main() -> None:
    if _port_is_open():
        raise SystemExit(
            "127.0.0.1:4841 已被占用；请关闭占用进程后再启动 TuneWise OPC-UA demo。"
        )
    if _port_is_open(8000):
        raise SystemExit(
            "127.0.0.1:8000 已被占用；TuneWise Web demo 未启动。"
        )
    os.environ["TUNEWISE_DEVICE_EXECUTION_ENABLED"] = "true"
    os.environ["TUNEWISE_OPCUA_MODE"] = "OPCUA_SANDBOX"
    os.environ["TUNEWISE_RUNTIME_PROFILE"] = "OPCUA_SANDBOX_DEMO"
    os.environ["TUNEWISE_OPCUA_SANDBOX_ENDPOINT"] = ENDPOINT
    sandbox = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tunewise.opcua_sandbox",
            "--endpoint",
            ENDPOINT,
            "--fault",
            "NORMAL",
        ]
    )
    try:
        _wait_for_sandbox(sandbox)
        import uvicorn

        uvicorn.run(
            "tunewise.main:app",
            host="127.0.0.1",
            port=8000,
            log_level="info",
        )
    finally:
        if sandbox.poll() is None:
            sandbox.terminate()
            try:
                sandbox.wait(timeout=5)
            except subprocess.TimeoutExpired:
                sandbox.kill()
                sandbox.wait(timeout=5)


if __name__ == "__main__":
    main()
