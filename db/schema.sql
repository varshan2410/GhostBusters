CREATE TABLE IF NOT EXISTS workflow_runs (
    id UUID PRIMARY KEY,
    goal TEXT NOT NULL,
    scenario_name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    version INTEGER NOT NULL,
    idempotency_key TEXT UNIQUE,
    error TEXT,
    payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS workflow_runs_status_idx ON workflow_runs(status);
CREATE INDEX IF NOT EXISTS workflow_runs_created_at_idx ON workflow_runs(created_at);

CREATE TABLE IF NOT EXISTS evidence_records (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    resource_id TEXT NOT NULL,
    source TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    claim TEXT NOT NULL,
    freshness_status TEXT NOT NULL,
    reliability DOUBLE PRECISION NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS evidence_records_run_idx ON evidence_records(run_id);
CREATE INDEX IF NOT EXISTS evidence_records_resource_idx ON evidence_records(resource_id);

CREATE TABLE IF NOT EXISTS approvals (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    reviewer TEXT NOT NULL,
    action TEXT NOT NULL,
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS approvals_run_idx ON approvals(run_id);

CREATE TABLE IF NOT EXISTS waivers (
    id BIGSERIAL PRIMARY KEY,
    resource_id TEXT NOT NULL,
    run_id UUID REFERENCES workflow_runs(id) ON DELETE SET NULL,
    reviewer TEXT NOT NULL,
    reason TEXT NOT NULL,
    expires_at TIMESTAMPTZ,
    milestone TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    CHECK (expires_at IS NOT NULL OR milestone IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS waivers_active_resource_idx
    ON waivers(resource_id) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    sequence_number INTEGER NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    summary TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (run_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS audit_log_run_idx ON audit_log(run_id, sequence_number);
