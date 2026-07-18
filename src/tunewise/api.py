from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from .assets import AssetIntegrityError, PublicAssetLoader
from .detection import DetectionGuardError
from .service import TaskService
from .importing import ImportValidationError
from .store import TaskStore


class PresetImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset_asset_id: str


class AnomalyDetectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_data_version: str


def create_app(
    public_asset_root: Path,
    expected_manifest_hash: str,
    database_path: Path,
    static_root: Path | None = None,
    demo_asset_root: Path | None = None,
    expected_dataset_manifest_hash: str | None = None,
) -> FastAPI:
    service = TaskService(
        asset_loader=PublicAssetLoader(public_asset_root, expected_manifest_hash),
        store=TaskStore(database_path),
        demo_asset_root=demo_asset_root,
        expected_dataset_manifest_hash=expected_dataset_manifest_hash,
    )
    app = FastAPI(
        title="TuneWise MVP",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )
    app.state.boundary_counters = {
        "simulator_gateway_assemblies": 0,
        "simulator_gateway_calls": 0,
        "llm_calls": 0,
        "external_network_requests": 0,
    }

    @app.exception_handler(AssetIntegrityError)
    async def handle_asset_integrity_error(
        _request: Request,
        error: AssetIntegrityError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": error.code, "message": error.message}},
        )

    @app.exception_handler(ImportValidationError)
    async def handle_import_validation_error(
        _request: Request,
        error: ImportValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": error.code, "message": error.message}},
        )

    @app.exception_handler(DetectionGuardError)
    async def handle_detection_guard_error(
        _request: Request,
        error: DetectionGuardError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
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

    @app.post("/api/tasks/{task_id}/imports")
    def import_preset(task_id: str, request: PresetImportRequest) -> dict:
        return asdict(service.import_preset(task_id, request.preset_asset_id))

    @app.post("/api/tasks/{task_id}/detections")
    def detect_anomaly(task_id: str, request: AnomalyDetectionRequest) -> dict:
        task, detection = service.detect_anomaly(
            task_id,
            request.input_data_version,
        )
        return {"task": asdict(task), "detection": asdict(detection)}

    if static_root is not None:
        app.mount("/", StaticFiles(directory=static_root, html=True), name="frontend")

    return app
