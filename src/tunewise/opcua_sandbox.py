from __future__ import annotations

import argparse
import asyncio
import json
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from asyncua import ua
from asyncua import Server, uamethod

from .opcua_gateway import (
    NODE_MAPPINGS,
    OPCUA_NAMESPACE_URI,
    OPCUA_NODE_MAPPING_VERSION,
    OPCUA_PARAMETER_SAFETY_MAPPING_VERSION,
    OPCUA_ATOMIC_METHOD_VERSION,
    OPCUA_SANDBOX_APPLICATION_URI,
    OPCUA_SANDBOX_ENDPOINT,
    OPCUA_SANDBOX_MODE,
    OPCUA_SANDBOX_SECURITY_PROFILE,
    OPCUA_SANDBOX_SERVER_VERSION,
    normalize_device_value,
    validate_sandbox_endpoint,
)


SANDBOX_SERVER_VERSION = OPCUA_SANDBOX_SERVER_VERSION
FAULT_MODES = {
    "NORMAL",
    "SERVICE_UNAVAILABLE",
    "WRITE_REJECTED",
    "READBACK_MISMATCH",
    "EXTERNAL_CHANGE",
    "TIMEOUT",
    "COMMUNICATION_FAILURE",
    "APPLY_THEN_TIMEOUT",
    "ATOMIC_UNSUPPORTED",
    "WRONG_APPLICATION_URI",
    "WRONG_NAMESPACE_URI",
    "WRONG_MAPPING_VERSION",
    "WRONG_PITCH_UNIT",
    "WRONG_PITCH_DATATYPE",
    "MISSING_METADATA",
    "WRITABLE_PITCH",
}
INITIAL_VALUES = {
    "x_offset": 0.0,
    "y_offset": 0.0,
    "pitch": 0.25,
    "roll": 0.0,
    "z_offset": 0.0,
}


@dataclass(slots=True)
class SandboxRuntime:
    server: Server
    parameter_nodes: dict[str, object]
    fault_mode: str
    stop_event: asyncio.Event
    execution_records: dict[str, dict[str, object]]
    execution_lock: asyncio.Lock
    state_file: Path | None
    physical_write_count: int = 0
    compare_completed_event: asyncio.Event | None = None
    continue_after_compare_event: asyncio.Event | None = None

    async def run(self) -> None:
        if self.fault_mode == "SERVICE_UNAVAILABLE":
            await self.stop_event.wait()
            return
        await self.server.start()
        try:
            await self.stop_event.wait()
        finally:
            await self.server.stop()


async def create_sandbox(
    *,
    endpoint: str = OPCUA_SANDBOX_ENDPOINT,
    fault_mode: str = "NORMAL",
    state_file: Path | None = None,
) -> SandboxRuntime:
    normalized_fault = fault_mode.upper()
    if normalized_fault not in FAULT_MODES:
        raise ValueError(f"不支持的 sandbox fault mode: {fault_mode}")
    server = Server()
    await server.init()
    application_uri = (
        "urn:tunewise:opcua:wrong-server"
        if normalized_fault == "WRONG_APPLICATION_URI"
        else OPCUA_SANDBOX_APPLICATION_URI
    )
    await server.set_application_uri(application_uri)
    server.set_endpoint(endpoint)
    server.set_server_name("TuneWise Local OPC-UA Sandbox Device")
    namespace_uri = (
        "urn:tunewise:opcua:wrong-namespace"
        if normalized_fault == "WRONG_NAMESPACE_URI"
        else OPCUA_NAMESPACE_URI
    )
    namespace_index = await server.register_namespace(namespace_uri)
    device = await server.nodes.objects.add_object(
        ua.NodeId("TuneWiseSandbox.Device", namespace_index),
        "TuneWiseSandboxDevice",
    )
    parameters = await device.add_object(
        ua.NodeId("TuneWiseSandbox.Parameters", namespace_index),
        "Parameters",
    )
    if normalized_fault != "MISSING_METADATA":
        metadata = {
            "ApplicationURI": application_uri,
            "ServerVersion": SANDBOX_SERVER_VERSION,
            "NodeMappingVersion": (
                "wrong-mapping-version"
                if normalized_fault == "WRONG_MAPPING_VERSION"
                else OPCUA_NODE_MAPPING_VERSION
            ),
            "ParameterSafetyMappingVersion": OPCUA_PARAMETER_SAFETY_MAPPING_VERSION,
            "SandboxMode": OPCUA_SANDBOX_MODE,
            "SecurityProfile": OPCUA_SANDBOX_SECURITY_PROFILE,
            "AtomicMethodVersion": OPCUA_ATOMIC_METHOD_VERSION,
        }
        for name, value in metadata.items():
            await device.add_property(
                ua.NodeId(f"TuneWiseSandbox.Device.{name}", namespace_index),
                name,
                value,
                ua.VariantType.String,
            )
    await device.add_variable(
        ua.NodeId("TuneWiseSandbox.Device.Healthy", namespace_index),
        "Healthy",
        normalized_fault not in {"TIMEOUT", "COMMUNICATION_FAILURE"},
        ua.VariantType.Boolean,
    )
    await device.add_variable(
        ua.NodeId("TuneWiseSandbox.Device.Status", namespace_index),
        "Status",
        "SANDBOX_READY" if normalized_fault == "NORMAL" else f"FAULT_{normalized_fault}",
        ua.VariantType.String,
    )
    await device.add_variable(
        ua.NodeId("TuneWiseSandbox.Device.FaultMode", namespace_index),
        "FaultMode",
        normalized_fault,
        ua.VariantType.String,
    )
    values = dict(INITIAL_VALUES)
    if normalized_fault == "EXTERNAL_CHANGE":
        values["pitch"] = 0.30
    parameter_nodes: dict[str, object] = {}
    for name, mapping in NODE_MAPPINGS.items():
        data_type = (
            ua.VariantType.String
            if normalized_fault == "WRONG_PITCH_DATATYPE" and name == "pitch"
            else ua.VariantType.Double
        )
        initial_value = (
            str(values[name])
            if data_type is ua.VariantType.String
            else values[name]
        )
        node = await parameters.add_variable(
            ua.NodeId(mapping.identifier, namespace_index),
            name,
            initial_value,
            data_type,
        )
        if normalized_fault == "WRITABLE_PITCH" and name == "pitch":
            await node.set_writable()
        await node.add_property(
            ua.NodeId(f"{mapping.identifier}.Unit", namespace_index),
            "Unit",
            (
                "Wrong Unit"
                if normalized_fault == "WRONG_PITCH_UNIT" and name == "pitch"
                else mapping.unit
            ),
            ua.VariantType.String,
        )
        await node.add_property(
            ua.NodeId(f"{mapping.identifier}.DataTypeName", namespace_index),
            "DataTypeName",
            data_type.name,
            ua.VariantType.String,
        )
        parameter_nodes[name] = node
    records: dict[str, dict[str, object]] = {}
    if state_file is not None and state_file.exists():
        try:
            loaded = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                records = {
                    str(key): value
                    for key, value in loaded.items()
                    if isinstance(value, dict)
                }
        except (OSError, json.JSONDecodeError):
            records = {}
    for record in sorted(
        records.values(),
        key=lambda item: str(item.get("executed_at", "")),
    ):
        if record.get("result") == "APPLIED":
            parameter_name = str(record.get("parameter_name", ""))
            actual_after = record.get("actual_after")
            node = parameter_nodes.get(parameter_name)
            if node is not None and actual_after is not None:
                await node.write_value(
                    ua.Variant(float(str(actual_after)), ua.VariantType.Double)
                )
    runtime = SandboxRuntime(
        server=server,
        parameter_nodes=parameter_nodes,
        fault_mode=normalized_fault,
        stop_event=asyncio.Event(),
        execution_records=records,
        execution_lock=asyncio.Lock(),
        state_file=state_file,
    )

    def persist_records() -> None:
        if runtime.state_file is None:
            return
        runtime.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = runtime.state_file.with_suffix(runtime.state_file.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                runtime.execution_records,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(runtime.state_file)

    @uamethod
    async def apply_confirmed_parameter_change(
        _parent: object,
        request_json: str,
    ) -> str:
        try:
            request = json.loads(request_json)
        except (TypeError, json.JSONDecodeError):
            return json.dumps({"result": "INVALID_REQUEST"})
        required = {
            "method_version",
            "idempotency_key",
            "parameter_name",
            "expected_before",
            "requested_after",
            "node_mapping_version",
            "observed_identity_hash",
        }
        if not isinstance(request, dict) or set(request) != required:
            return json.dumps({"result": "INVALID_REQUEST"})
        key = str(request["idempotency_key"])
        async with runtime.execution_lock:
            existing = runtime.execution_records.get(key)
            if existing is not None:
                same_request = all(
                    existing.get(field) == request.get(field)
                    for field in (
                        "parameter_name",
                        "expected_before",
                        "requested_after",
                        "node_mapping_version",
                    )
                )
                if same_request:
                    return json.dumps(existing, ensure_ascii=False, sort_keys=True)
                conflict = dict(existing)
                conflict["result"] = "IDEMPOTENCY_CONFLICT"
                conflict["physical_write_count"] = 0
                return json.dumps(conflict, ensure_ascii=False, sort_keys=True)
            parameter_name = str(request["parameter_name"])
            mapping = NODE_MAPPINGS.get(parameter_name)
            if (
                request["method_version"] != OPCUA_ATOMIC_METHOD_VERSION
                or request["node_mapping_version"] != OPCUA_NODE_MAPPING_VERSION
                or mapping is None
            ):
                return json.dumps(
                    {
                        "idempotency_key": key,
                        "parameter_name": parameter_name,
                        "expected_before": str(request["expected_before"]),
                        "requested_after": str(request["requested_after"]),
                        "actual_before": None,
                        "actual_after": None,
                        "result": "PARAMETER_MAPPING_REJECTED",
                        "executed_at": datetime.now(timezone.utc).isoformat(),
                        "physical_write_count": 0,
                        "node_mapping_version": str(request["node_mapping_version"]),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            expected = normalize_device_value(request["expected_before"])
            requested = normalize_device_value(request["requested_after"])
            node = runtime.parameter_nodes[parameter_name]
            actual_before = normalize_device_value(await node.read_value())
            if (
                runtime.compare_completed_event is not None
                and runtime.continue_after_compare_event is not None
            ):
                runtime.compare_completed_event.set()
                await runtime.continue_after_compare_event.wait()
            record: dict[str, object] = {
                "idempotency_key": key,
                "parameter_name": parameter_name,
                "expected_before": expected,
                "requested_after": requested,
                "actual_before": actual_before,
                "actual_after": actual_before,
                "result": "EXPECTED_BEFORE_MISMATCH",
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "physical_write_count": 0,
                "node_mapping_version": OPCUA_NODE_MAPPING_VERSION,
            }
            if actual_before == expected:
                if normalized_fault == "WRITE_REJECTED":
                    record["result"] = "WRITE_REJECTED"
                else:
                    await node.write_value(
                        ua.Variant(float(requested), ua.VariantType.Double)
                    )
                    if normalized_fault == "READBACK_MISMATCH":
                        await node.write_value(
                            ua.Variant(float(requested) + 0.05, ua.VariantType.Double)
                        )
                    actual_after = normalize_device_value(await node.read_value())
                    runtime.physical_write_count += 1
                    record.update(
                        actual_after=actual_after,
                        result=(
                            "APPLIED"
                            if actual_after == requested
                            else "READBACK_MISMATCH"
                        ),
                        physical_write_count=1,
                    )
            runtime.execution_records[key] = record
            persist_records()
        if normalized_fault == "APPLY_THEN_TIMEOUT" and record["result"] == "APPLIED":
            await asyncio.sleep(5)
        return json.dumps(record, ensure_ascii=False, sort_keys=True)

    @uamethod
    async def query_execution_result(_parent: object, idempotency_key: str) -> str:
        async with runtime.execution_lock:
            record = runtime.execution_records.get(str(idempotency_key))
            return (
                "NOT_FOUND"
                if record is None
                else json.dumps(record, ensure_ascii=False, sort_keys=True)
            )

    if normalized_fault != "ATOMIC_UNSUPPORTED":
        await device.add_method(
            ua.NodeId(
                "TuneWiseSandbox.Device.ApplyConfirmedParameterChange",
                namespace_index,
            ),
            "ApplyConfirmedParameterChange",
            apply_confirmed_parameter_change,
            [ua.VariantType.String],
            [ua.VariantType.String],
        )
        await device.add_method(
            ua.NodeId("TuneWiseSandbox.Device.QueryExecutionResult", namespace_index),
            "QueryExecutionResult",
            query_execution_result,
            [ua.VariantType.String],
            [ua.VariantType.String],
        )
    return runtime


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description="TuneWise localhost-only OPC-UA sandbox device",
    )
    parser.add_argument("--endpoint", default=OPCUA_SANDBOX_ENDPOINT)
    parser.add_argument("--fault", choices=sorted(FAULT_MODES), default="NORMAL")
    parser.add_argument("--state-file", type=Path)
    args = parser.parse_args()
    endpoint = args.endpoint
    try:
        validate_sandbox_endpoint(endpoint)
    except ValueError as error:
        raise SystemExit("sandbox server 只允许监听 127.0.0.1 sandbox endpoint。") from error
    if endpoint != OPCUA_SANDBOX_ENDPOINT:
        raise SystemExit("sandbox server 的监听地址固定为 127.0.0.1。")
    runtime = await create_sandbox(
        endpoint=endpoint,
        fault_mode=args.fault,
        state_file=args.state_file,
    )
    loop = asyncio.get_running_loop()

    def stop(*_args: object) -> None:
        loop.call_soon_threadsafe(runtime.stop_event.set)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"TuneWise OPC-UA sandbox: {endpoint} fault={args.fault}", flush=True)
    await runtime.run()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
