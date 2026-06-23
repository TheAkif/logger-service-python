-- Composite index on received_at for ingest-order time-range queries
CREATE INDEX IF NOT EXISTS idx_log_events_tenant_received
  ON log_events (tenant_id, received_at DESC);

-- GIN index for JSONB property queries
CREATE INDEX IF NOT EXISTS idx_log_events_properties_gin
  ON log_events USING GIN (properties);

-- Generated tsvector column for full-text search on message
ALTER TABLE log_events
  ADD COLUMN IF NOT EXISTS message_tsv TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', message)) STORED;

CREATE INDEX IF NOT EXISTS idx_log_events_message_tsv
  ON log_events USING GIN (message_tsv);
