CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS log_events (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  occurred_at   TIMESTAMPTZ NOT NULL,
  received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

  tenant_id     TEXT NOT NULL,
  source        TEXT NOT NULL,
  environment   TEXT NOT NULL,

  level         TEXT NOT NULL,
  type          TEXT NOT NULL,
  message       TEXT NOT NULL,

  trace_id       TEXT NULL,
  span_id        TEXT NULL,
  correlation_id TEXT NULL,
  request_id     TEXT NULL,

  user_id       TEXT NULL,

  path          TEXT NULL,
  method        TEXT NULL,
  status_code   INT NULL,
  duration_ms   INT NULL,

  exception     JSONB NULL,
  properties    JSONB NULL
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_log_events_tenant_time
  ON log_events (tenant_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_log_events_source_time
  ON log_events (source, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_log_events_level_time
  ON log_events (level, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_log_events_trace_id
  ON log_events (trace_id);
