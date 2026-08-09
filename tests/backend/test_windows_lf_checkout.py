from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows checkout contract")
ROOT = Path(__file__).resolve().parents[2]


def _run(*command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
    )


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_core_autocrlf_checkout_and_rebuild_preserve_hashed_assets() -> None:
    source_static = ROOT / "src" / "tunewise" / "static"
    source_public = ROOT / "assets" / "public"
    source_static_hashes = _hashes(source_static)
    source_public_hashes = _hashes(source_public)

    # Keeping this temporary hierarchy inside the ignored node_modules tree
    # both isolates it from parent-repository scanners and lets Node resolve
    # the already-installed dependencies without copying or linking them.
    with tempfile.TemporaryDirectory(
        prefix="lf-checkout-", dir=ROOT / "frontend" / "node_modules"
    ) as raw:
        temporary = Path(raw)
        seed = temporary / "seed"
        checkout = temporary / "checkout"
        (seed / "frontend").mkdir(parents=True)
        (seed / "src" / "tunewise").mkdir(parents=True)
        (seed / "assets").mkdir(parents=True)
        shutil.copy2(ROOT / ".gitattributes", seed / ".gitattributes")
        shutil.copy2(ROOT / ".gitignore", seed / ".gitignore")
        for name in (
            "package.json",
            "package-lock.json",
            "index.html",
            "vite.config.ts",
            "tsconfig.json",
            "tsconfig.app.json",
            "tsconfig.node.json",
        ):
            shutil.copy2(ROOT / "frontend" / name, seed / "frontend" / name)
        shutil.copytree(ROOT / "frontend" / "src", seed / "frontend" / "src")
        shutil.copytree(ROOT / "frontend" / "public", seed / "frontend" / "public")
        shutil.copytree(source_static, seed / "src" / "tunewise" / "static")
        shutil.copytree(source_public, seed / "assets" / "public")

        _run("git", "init", "-q", cwd=seed)
        _run("git", "config", "user.name", "TuneWise LF Test", cwd=seed)
        _run("git", "config", "user.email", "lf-test@invalid.local", cwd=seed)
        _run("git", "config", "core.autocrlf", "false", cwd=seed)
        _run("git", "config", "maintenance.auto", "false", cwd=seed)
        _run("git", "add", ".", cwd=seed)
        _run("git", "commit", "-q", "-m", "temporary LF checkout fixture", cwd=seed)
        _run(
            "git",
            "-c",
            "core.autocrlf=true",
            "clone",
            "-q",
            str(seed),
            str(checkout),
            cwd=temporary,
        )

        checked_static = checkout / "src" / "tunewise" / "static"
        checked_public = checkout / "assets" / "public"
        assert _hashes(checked_static) == source_static_hashes
        assert _hashes(checked_public) == source_public_hashes
        for path in checked_static.rglob("*"):
            if path.suffix in {".css", ".js", ".html", ".json", ".svg"}:
                assert b"\r\n" not in path.read_bytes(), path

        _run("npm.cmd", "run", "build", cwd=checkout / "frontend")
        assert _hashes(checked_static) == source_static_hashes
        assert _run("git", "status", "--porcelain", cwd=checkout).stdout == ""

        index = (checked_static / "index.html").read_text(encoding="utf-8")
        references = re.findall(r'(?:src|href)="/assets/([^"]+)"', index)
        assert references
        assert all((checked_static / "assets" / item).is_file() for item in references)
