CREATE TABLE IF NOT EXISTS spans (
    id              TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    parent_span_id  TEXT,
    span_type       TEXT NOT NULL DEFAULT '',
    agent_id        TEXT NOT NULL DEFAULT '',
    input           JSONB,
    output          JSONB,
    attributes      JSONB NOT NULL DEFAULT '{}',
    start_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    end_time        TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'ok',
    failure_mode    TEXT,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans (trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_agent_id ON spans (agent_id);
CREATE INDEX IF NOT EXISTS idx_spans_status   ON spans (status);
CREATE INDEX IF NOT EXISTS idx_spans_start    ON spans (start_time DESC);

CREATE TABLE IF NOT EXISTS failures (
    id              BIGSERIAL PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    span_id         TEXT NOT NULL,
    agent_id        TEXT NOT NULL DEFAULT '',
    failure_mode    TEXT NOT NULL,
    error_message   TEXT,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_failures_mode ON failures (failure_mode);
CREATE INDEX IF NOT EXISTS idx_failures_agent ON failures (agent_id);
CREATE INDEX IF NOT EXISTS idx_failures_ts   ON failures (timestamp DESC);

CREATE TABLE IF NOT EXISTS recovery_attempts (
    id              TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL DEFAULT '',
    span_id         TEXT NOT NULL DEFAULT '',
    failure_mode    TEXT,
    attempt_number  INT NOT NULL DEFAULT 1,
    strategy        TEXT NOT NULL DEFAULT '',
    success         BOOLEAN,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_recovery_trace ON recovery_attempts (trace_id);
CREATE INDEX IF NOT EXISTS idx_recovery_mode  ON recovery_attempts (failure_mode);
