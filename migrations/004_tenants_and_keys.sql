-- tenants
CREATE TABLE IF NOT EXISTS tenants (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ,
    config      JSONB NOT NULL DEFAULT '{}'
);

-- api keys (raw key is never stored; only the SHA-256 hash)
CREATE TABLE IF NOT EXISTS api_keys (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    TEXT NOT NULL REFERENCES tenants(id),
    key_hash     TEXT UNIQUE NOT NULL,
    label        TEXT NOT NULL DEFAULT '',
    scopes       TEXT[] NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    expires_at   TIMESTAMPTZ,
    revoked      BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash   ON api_keys (key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_tenant_id  ON api_keys (tenant_id);
