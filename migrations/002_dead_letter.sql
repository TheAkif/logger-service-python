CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS failed_batches (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  payload    JSONB        NOT NULL,
  error      TEXT         NOT NULL,
  failed_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
