from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .assets import AssetIntegrityError, PublicAssetLoader
from .service import TaskService
from .store import TaskStore


def create_app(
    public_asset_root: Path,
    expected_manifest_hash: str,
    database_path: Path,
    static_root: Path | None = None,
) -> FastAPI:
    service = TaskService(
        asset_loader=PublicAssetLoader(public_asset_root, expected_manifest_hash),
        store=TaskStore(database_path),
    )
    app = FastAPI(
        title="TuneWise MVP",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )

    @app.exception_handler(AssetIntegrityError)
    async def handle_asset_integrity_error(
        _request: Request,
        error: AssetIntegrityError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": error.code, "message": error.message}},
        )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "offline"}

    @app.post("/api/tasks/initial", status_code=201)
    def create_initial_task() -> dict:
        return asdict(service.create_initial_task())

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict:
        task = service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="调机任务不存在。")
        return asdict(task)

    if static_root is not None:
        app.mount("/", StaticFiles(directory=static_root, html=True), name="frontend")

    return app
