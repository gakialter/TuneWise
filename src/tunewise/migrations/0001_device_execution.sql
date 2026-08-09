CREATE TABLE IF NOT EXISTS device_execution_claims (
    device_execution_id TEXT PRIMARY KEY CHECK (length(device_execution_id) BETWEEN 1 AND 128),
    task_id TEXT NOT NULL CHECK (length(task_id) BETWEEN 1 AND 128)
        REFERENCES tasks(task_id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL UNIQUE CHECK (length(idempotency_key) = 64),
    owner_instance_id TEXT NOT NULL CHECK (length(owner_instance_id) BETWEEN 1 AND 128),
    status TEXT NOT NULL CHECK (status IN (
        'VALIDATING', 'WRITE_STARTED', 'UNKNOWN_OUTCOME',
        'RECONCILIATION_REQUIRED', 'FINALIZED'
    )),
    started_at TEXT NOT NULL CHECK (length(started_at) BETWEEN 1 AND 64),
    write_started_at TEXT,
    completed_at TEXT,
    receipt_hash TEXT CHECK (receipt_hash IS NULL OR length(receipt_hash) = 64),
    server_identity_hash TEXT NOT NULL CHECK (
        server_identity_hash = 'NOT_OBSERVED' OR length(server_identity_hash) = 64
    ),
    server_identity_json TEXT,
    node_mapping_version TEXT NOT NULL CHECK (length(node_mapping_version) BETWEEN 1 AND 128),
    expected_before_value TEXT CHECK (expected_before_value IS NULL OR length(expected_before_value) <= 64),
    requested_after_value TEXT CHECK (requested_after_value IS NULL OR length(requested_after_value) <= 64),
    confirmed_plan_hash TEXT CHECK (confirmed_plan_hash IS NULL OR length(confirmed_plan_hash) = 64),
    replay_result_hash TEXT CHECK (replay_result_hash IS NULL OR length(replay_result_hash) = 64),
    parameter_name TEXT CHECK (parameter_name IS NULL OR length(parameter_name) BETWEEN 1 AND 64),
    node_id TEXT CHECK (node_id IS NULL OR length(node_id) <= 512),
    recovery_payload_json TEXT CHECK (
        recovery_payload_json IS NULL OR length(recovery_payload_json) BETWEEN 2 AND 1048576
    ),
    attempt_count INTEGER NOT NULL DEFAULT 1 CHECK (attempt_count = 1),
    failure_code TEXT CHECK (failure_code IS NULL OR length(failure_code) <= 128)
);

CREATE INDEX IF NOT EXISTS device_execution_claims_task_idx
ON device_execution_claims(task_id);

CREATE INDEX IF NOT EXISTS device_execution_claims_reconciliation_idx
ON device_execution_claims(status, started_at);

CREATE TABLE IF NOT EXISTS device_execution_receipts (
    device_execution_id TEXT PRIMARY KEY CHECK (length(device_execution_id) BETWEEN 1 AND 128),
    task_id TEXT NOT NULL CHECK (length(task_id) BETWEEN 1 AND 128)
        REFERENCES tasks(task_id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL UNIQUE CHECK (length(idempotency_key) = 64),
    execution_status TEXT NOT NULL CHECK (
        execution_status IN (
            'REJECTED', 'FAILED_DEFINITE', 'UNKNOWN_OUTCOME',
            'RECONCILIATION_REQUIRED', 'SUCCEEDED'
        )
    ),
    receipt_hash TEXT NOT NULL UNIQUE CHECK (length(receipt_hash) = 64),
    completed_at TEXT NOT NULL CHECK (length(completed_at) BETWEEN 1 AND 64),
    payload_json TEXT NOT NULL CHECK (length(payload_json) BETWEEN 2 AND 1048576)
);

CREATE INDEX IF NOT EXISTS device_execution_receipts_task_idx
ON device_execution_receipts(task_id, completed_at);
