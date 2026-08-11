from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .assets import AssetIntegrityError, PublicAssetLoader
from .case_retrieval import CaseRetrievalAssetError, CaseRetrievalGuardError
from .detection import DetectionGuardError
from .diagnosis import (
    DiagnosticAssetError,
    DiagnosticGuardError,
    FeatureEngineeringError,
)
from .parameter_planning import (
    ParameterPlanningAssetError,
    ParameterPlanningGuardError,
)
from .process_aware_demo import ProcessAwareDemoService
from .plan_confirmation import PlanConfirmationGuardError
from .replay import ReplayBoundaryAudit, ReplayGuardError
from .device_execution import (
    DeviceExecutionConflictError,
    DeviceExecutionService,
)
from .opcua_gateway import DeviceExecutionConfig, OpcUaGateway
from .service import PlanningBoundaryAudit, TaskService
from .importing import ImportValidationError
from .store import TaskStore


class PresetImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset_asset_id: str


class AnomalyDetectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_data_version: str


class RootCauseDiagnosisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detection_result_id: str


class ApprovedCaseRetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diagnostic_result_id: str
    top_k: Literal[3]


class ParameterPlanningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diagnostic_result_id: str
    case_retrieval_result_id: str | None = None


class PlanConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    candidate_hash: str


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    confirmed_plan_id: str
    confirmed_plan_hash: str
    request_idempotency_key: str


class DeviceExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed_plan_id: str = Field(min_length=1, max_length=128)
    confirmed_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_mode: Literal["OPCUA_SANDBOX"]
    sandbox_execution_acknowledged: StrictBool


def create_app(
    public_asset_root: Path,
    expected_manifest_hash: str,
    database_path: Path,
    static_root: Path | None = None,
    demo_asset_root: Path | None = None,
    expected_dataset_manifest_hash: str | None = None,
    diagnostic_asset_root: Path | None = None,
    expected_diagnostic_manifest_hash: str | None = None,
    case_asset_root: Path | None = None,
    expected_case_manifest_hash: str | None = None,
    planning_asset_root: Path | None = None,
    expected_planning_manifest_hash: str | None = None,
    replay_asset_root: Path | None = None,
    expected_replay_manifest_hash: str | None = None,
    device_execution_config: DeviceExecutionConfig | None = None,
    opcua_gateway: OpcUaGateway | None = None,
    process_aware_demo_asset_root: Path | None = None,
    expected_process_aware_demo_manifest_hash: str | None = None,
    process_aware_demo_static_root: Path | None = None,
) -> FastAPI:
    boundary_audit = PlanningBoundaryAudit()
    replay_boundary_audit = ReplayBoundaryAudit()
    store = TaskStore(database_path)
    public_asset_loader = PublicAssetLoader(public_asset_root, expected_manifest_hash)
    service = TaskService(
        asset_loader=public_asset_loader,
        store=store,
        demo_asset_root=demo_asset_root,
        expected_dataset_manifest_hash=expected_dataset_manifest_hash,
        diagnostic_asset_root=diagnostic_asset_root,
        expected_diagnostic_manifest_hash=expected_diagnostic_manifest_hash,
        case_asset_root=case_asset_root,
        expected_case_manifest_hash=expected_case_manifest_hash,
        planning_asset_root=planning_asset_root,
        expected_planning_manifest_hash=expected_planning_manifest_hash,
        planning_boundary_audit=boundary_audit,
        replay_asset_root=replay_asset_root,
        expected_replay_manifest_hash=expected_replay_manifest_hash,
        replay_boundary_audit=replay_boundary_audit,
    )
    process_aware_configuration = (
        process_aware_demo_asset_root,
        expected_process_aware_demo_manifest_hash,
    )
    if any(item is not None for item in process_aware_configuration) and not all(
        item is not None for item in process_aware_configuration
    ):
        raise ValueError(
            "Process-aware demo asset root and trusted manifest hash must be configured together."
        )
    process_aware_demo_service: ProcessAwareDemoService | None = None
    if all(item is not None for item in process_aware_configuration):
        required_source_configuration = (
            demo_asset_root,
            expected_dataset_manifest_hash,
            diagnostic_asset_root,
            expected_diagnostic_manifest_hash,
            case_asset_root,
            expected_case_manifest_hash,
            planning_asset_root,
            expected_planning_manifest_hash,
        )
        if any(item is None for item in required_source_configuration):
            raise ValueError(
                "Process-aware demo requires the frozen dataset, diagnostic, case, and planning assets."
            )
        process_aware_demo_service = ProcessAwareDemoService(
            public_asset_loader=public_asset_loader,
            fixture_root=process_aware_demo_asset_root,
            expected_fixture_manifest_hash=expected_process_aware_demo_manifest_hash,
            demo_asset_root=demo_asset_root,
            expected_dataset_manifest_hash=expected_dataset_manifest_hash,
            diagnostic_asset_root=diagnostic_asset_root,
            expected_diagnostic_manifest_hash=expected_diagnostic_manifest_hash,
            case_asset_root=case_asset_root,
            expected_case_manifest_hash=expected_case_manifest_hash,
            planning_asset_root=planning_asset_root,
            expected_planning_manifest_hash=expected_planning_manifest_hash,
        )
    execution_config = device_execution_config or DeviceExecutionConfig.from_env()
    device_execution_service = DeviceExecutionService(
        config=execution_config,
        repository=store,
        qualification_provider=service.qualify_device_execution,
        gateway=opcua_gateway,
    )
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if execution_config.enabled:
            outcomes = device_execution_service.reconcile_pending()
            application.state.device_execution_reconciliation_count = len(outcomes)
        yield

    app = FastAPI(
        title="TuneWise MVP",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.planning_boundary_audit = boundary_audit
    app.state.boundary_counters = boundary_audit.counters
    app.state.replay_boundary_audit = replay_boundary_audit
    app.state.replay_boundary_counters = replay_boundary_audit.counters
    app.state.device_execution_config = execution_config
    app.state.device_execution_service = device_execution_service
    app.state.device_execution_reconciliation_count = 0

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

    @app.exception_handler(DiagnosticGuardError)
    async def handle_diagnostic_guard_error(
        _request: Request,
        error: DiagnosticGuardError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": error.code, "message": error.message}},
        )

    @app.exception_handler(DiagnosticAssetError)
    async def handle_diagnostic_asset_error(
        _request: Request,
        error: DiagnosticAssetError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": error.code, "message": error.message}},
        )

    @app.exception_handler(FeatureEngineeringError)
    async def handle_feature_engineering_error(
        _request: Request,
        error: FeatureEngineeringError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": error.code, "message": error.message}},
        )

    @app.exception_handler(CaseRetrievalGuardError)
    async def handle_case_retrieval_guard_error(
        _request: Request,
        error: CaseRetrievalGuardError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": error.code, "message": error.message}},
        )

    @app.exception_handler(CaseRetrievalAssetError)
    async def handle_case_retrieval_asset_error(
        _request: Request,
        error: CaseRetrievalAssetError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": error.code, "message": error.message}},
        )

    @app.exception_handler(ParameterPlanningGuardError)
    async def handle_parameter_planning_guard_error(
        _request: Request,
        error: ParameterPlanningGuardError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "supporting_evidence": error.supporting_evidence,
                    "recommended_inspection_actions": error.recommended_inspection_actions,
                    "rule_set_version": error.rule_set_version,
                }
            },
        )

    @app.exception_handler(ParameterPlanningAssetError)
    async def handle_parameter_planning_asset_error(
        _request: Request,
        error: ParameterPlanningAssetError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "supporting_evidence": error.supporting_evidence,
                    "recommended_inspection_actions": error.recommended_inspection_actions,
                    "rule_set_version": error.rule_set_version,
                }
            },
        )

    @app.exception_handler(PlanConfirmationGuardError)
    async def handle_plan_confirmation_guard_error(
        _request: Request,
        error: PlanConfirmationGuardError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "expected_hash": error.expected_hash,
                    "actual_hash": error.actual_hash,
                    "expected_version": error.expected_version,
                    "actual_version": error.actual_version,
                }
            },
        )

    @app.exception_handler(ReplayGuardError)
    async def handle_replay_guard_error(
        _request: Request,
        error: ReplayGuardError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "expected_hash": error.expected_hash,
                    "actual_hash": error.actual_hash,
                    "failed_validation": error.failed_validation,
                }
            },
        )

    @app.exception_handler(DeviceExecutionConflictError)
    async def handle_device_execution_conflict(
        _request: Request,
        error: DeviceExecutionConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": error.code, "message": error.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        if request.url.path.endswith("/diagnoses") and any(
            item.get("type") == "extra_forbidden" for item in error.errors()
        ):
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "DIAGNOSTIC_REQUEST_FORBIDDEN_FIELDS",
                        "message": "诊断请求只能提交 task_id 路径参数与最新 detection_result_id。",
                    }
                },
            )
        if request.url.path.endswith("/case-retrievals"):
            if any(
                item.get("type") == "extra_forbidden" for item in error.errors()
            ):
                return JSONResponse(
                    status_code=422,
                    content={
                        "error": {
                            "code": "CASE_RETRIEVAL_REQUEST_FORBIDDEN_FIELDS",
                            "message": (
                                "案例检索请求只能提交最新 diagnostic_result_id "
                                "与固定 top_k=3。"
                            ),
                        }
                    },
                )
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "CASE_RETRIEVAL_REQUEST_INVALID",
                        "message": "案例检索请求必须引用最新诊断且 top_k 固定为 3。",
                    }
                },
            )
        if request.url.path.endswith("/parameter-plans"):
            if any(
                item.get("type") == "extra_forbidden" for item in error.errors()
            ):
                body = error.body if isinstance(error.body, dict) else {}
                forbidden_fields = tuple(
                    sorted(
                        str(item["loc"][-1])
                        for item in error.errors()
                        if item.get("type") == "extra_forbidden"
                    )
                )
                structured = service.record_parameter_planning_request_refusal(
                    request.path_params["task_id"],
                    str(body.get("diagnostic_result_id", "MISSING")),
                    body.get("case_retrieval_result_id"),
                    forbidden_fields,
                )
                return JSONResponse(
                    status_code=422,
                    content={
                        "error": {
                            "code": structured.code,
                            "message": structured.message,
                            "supporting_evidence": structured.supporting_evidence,
                            "recommended_inspection_actions": structured.recommended_inspection_actions,
                            "rule_set_version": structured.rule_set_version,
                        }
                    },
                )
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "PARAMETER_PLANNING_REQUEST_INVALID",
                        "message": "参数规划请求必须引用最新诊断与案例检索结果。",
                    }
                },
            )
        if request.url.path.endswith("/confirmed-plans"):
            body = error.body if isinstance(error.body, dict) else {}
            if any(
                item.get("type") == "extra_forbidden" for item in error.errors()
            ):
                forbidden_fields = tuple(
                    sorted(
                        str(item["loc"][-1])
                        for item in error.errors()
                        if item.get("type") == "extra_forbidden"
                    )
                )
                structured = service.record_confirmation_request_refusal(
                    request.path_params["task_id"],
                    body.get("candidate_id"),
                    body.get("candidate_hash"),
                    forbidden_fields,
                )
                return JSONResponse(
                    status_code=structured.status_code,
                    content={
                        "error": {
                            "code": structured.code,
                            "message": structured.message,
                            "expected_hash": None,
                            "actual_hash": None,
                            "expected_version": None,
                            "actual_version": ",".join(forbidden_fields),
                        }
                    },
                )
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "CONFIRMATION_REQUEST_INVALID",
                        "message": "确认请求必须提交 candidate_id 与 candidate_hash。",
                    }
                },
            )
        if request.url.path.endswith("/replays"):
            if any(item.get("type") == "extra_forbidden" for item in error.errors()):
                return JSONResponse(
                    status_code=422,
                    content={
                        "error": {
                            "code": "REPLAY_REQUEST_FORBIDDEN_FIELDS",
                            "message": (
                                "回放请求只能提交 task_id、confirmed_plan_id、"
                                "confirmed_plan_hash 与 request_idempotency_key。"
                            ),
                        }
                    },
                )
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "REPLAY_REQUEST_INVALID",
                        "message": "回放请求缺少合法的确认方案身份或幂等键。",
                    }
                },
            )
        if request.url.path.endswith("/device-executions"):
            task_id = request.path_params.get("task_id", "")
            if not task_id or not service.has_task(task_id):
                return JSONResponse(
                    status_code=404,
                    content={"detail": "调机任务不存在。"},
                )
            if any(item.get("type") == "extra_forbidden" for item in error.errors()):
                return JSONResponse(
                    status_code=422,
                    content={
                        "error": {
                            "code": "DEVICE_EXECUTION_REQUEST_FORBIDDEN_FIELDS",
                            "message": (
                                "设备执行请求只能提交 ConfirmedPlan 身份、"
                                "OPCUA_SANDBOX 模式与独立确认。"
                            ),
                        }
                    },
                )
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "DEVICE_EXECUTION_REQUEST_INVALID",
                        "message": "设备执行请求缺少合法的方案身份、模式或独立确认。",
                    }
                },
            )
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(error.errors())},
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

    @app.post("/api/tasks/{task_id}/diagnoses")
    def diagnose_root_cause(task_id: str, request: RootCauseDiagnosisRequest) -> dict:
        task, diagnostic = service.diagnose_root_cause(
            task_id,
            request.detection_result_id,
        )
        return {"task": asdict(task), "diagnostic": asdict(diagnostic)}

    @app.post("/api/tasks/{task_id}/case-retrievals")
    def retrieve_approved_cases(
        task_id: str,
        request: ApprovedCaseRetrievalRequest,
    ) -> dict:
        _task, retrieval = service.retrieve_approved_cases(
            task_id,
            request.diagnostic_result_id,
            request.top_k,
        )
        return {"retrieval": asdict(retrieval)}

    @app.post("/api/tasks/{task_id}/parameter-plans")
    def generate_parameter_plans(
        task_id: str,
        request: ParameterPlanningRequest,
    ) -> dict:
        boundary_audit.assert_pristine()
        try:
            task, planning = service.generate_parameter_plans(
                task_id,
                request.diagnostic_result_id,
                request.case_retrieval_result_id,
            )
        finally:
            boundary_audit.assert_pristine()
        return {"task": asdict(task), "planning": asdict(planning)}

    @app.post("/api/tasks/{task_id}/confirmed-plans")
    def confirm_parameter_plan(
        task_id: str,
        request: PlanConfirmationRequest,
    ) -> dict:
        boundary_audit.assert_pristine()
        try:
            task, plan = service.confirm_parameter_plan(
                task_id,
                request.candidate_id,
                request.candidate_hash,
            )
        finally:
            boundary_audit.assert_pristine()
        return {"task": asdict(task), "confirmed_plan": asdict(plan)}

    @app.post("/api/tasks/{task_id}/replays")
    def run_paired_replay(task_id: str, request: ReplayRequest) -> dict:
        if request.task_id != task_id:
            raise ReplayGuardError(
                "REPLAY_TASK_ID_MISMATCH",
                "请求 task_id 与路径任务不一致。",
                422,
            )
        task, result = service.run_replay(
            task_id,
            request.confirmed_plan_id,
            request.confirmed_plan_hash,
            request.request_idempotency_key,
        )
        return {"task": asdict(task), "replay_result": asdict(result)}

    @app.get("/api/tasks/{task_id}/audit-events")
    def get_audit_events(task_id: str) -> dict:
        if not service.has_task(task_id):
            raise HTTPException(status_code=404, detail="调机任务不存在。")
        return {"audit_events": [asdict(item) for item in service.get_audit_events(task_id)]}

    @app.get("/api/tasks/{task_id}/device-executions/eligibility")
    def get_device_execution_eligibility(
        task_id: str,
        confirmed_plan_id: str,
        confirmed_plan_hash: str,
    ) -> dict:
        if not service.has_task(task_id):
            raise HTTPException(status_code=404, detail="调机任务不存在。")
        return asdict(
            device_execution_service.eligibility(
                task_id,
                confirmed_plan_id,
                confirmed_plan_hash,
            )
        )

    @app.post("/api/tasks/{task_id}/device-executions")
    def create_device_execution(
        task_id: str,
        request: DeviceExecutionRequest,
    ) -> JSONResponse:
        if not service.has_task(task_id):
            raise HTTPException(status_code=404, detail="调机任务不存在。")
        outcome = device_execution_service.execute(
            task_id=task_id,
            confirmed_plan_id=request.confirmed_plan_id,
            confirmed_plan_hash=request.confirmed_plan_hash,
            execution_mode=request.execution_mode,
            sandbox_execution_acknowledged=request.sandbox_execution_acknowledged,
        )
        return JSONResponse(
            status_code=201 if outcome.created else 200,
            content=jsonable_encoder(
                {
                    "device_execution": asdict(outcome.receipt),
                    "idempotent_replay": outcome.idempotent_replay,
                }
            ),
        )

    @app.get(
        "/api/tasks/{task_id}/device-executions/{device_execution_id}"
    )
    def get_device_execution(
        task_id: str,
        device_execution_id: str,
    ) -> dict:
        if not service.has_task(task_id):
            raise HTTPException(status_code=404, detail="调机任务不存在。")
        receipt = device_execution_service.get_receipt(device_execution_id)
        if receipt is None or receipt.task_id != task_id:
            raise HTTPException(status_code=404, detail="设备执行记录不存在。")
        return {"device_execution": asdict(receipt)}

    @app.get(
        "/api/tasks/{task_id}/device-executions/{device_execution_id}/receipt"
    )
    def get_device_execution_receipt(
        task_id: str,
        device_execution_id: str,
    ) -> dict:
        if not service.has_task(task_id):
            raise HTTPException(status_code=404, detail="调机任务不存在。")
        receipt = device_execution_service.get_receipt(device_execution_id)
        if receipt is None or receipt.task_id != task_id:
            raise HTTPException(status_code=404, detail="设备执行凭证不存在。")
        return {"receipt": asdict(receipt)}

    if process_aware_demo_service is not None:
        @app.get("/api/demos/process-aware")
        def get_process_aware_demo() -> dict:
            boundary_audit.assert_pristine()
            replay_counters_before = dict(replay_boundary_audit.counters)
            try:
                return process_aware_demo_service.get_demo()
            finally:
                boundary_audit.assert_pristine()
                if replay_boundary_audit.counters != replay_counters_before:
                    raise RuntimeError(
                        "Process-aware demo crossed the replay isolation boundary."
                    )

    if process_aware_demo_static_root is not None:
        app.mount(
            "/process-aware-demo",
            StaticFiles(directory=process_aware_demo_static_root, html=True),
            name="process-aware-demo",
        )

    if static_root is not None:
        app.mount("/", StaticFiles(directory=static_root, html=True), name="frontend")

    return app
