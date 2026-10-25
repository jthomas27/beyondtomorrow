-- Durable, additive recovery records. Existing articles and corpus are untouched.
CREATE TABLE IF NOT EXISTS pipeline_deliveries (
    channel TEXT NOT NULL,
    article_key TEXT NOT NULL,
    recipient_key TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sending', 'sent', 'failed')),
    external_id TEXT,
    data JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (channel, article_key, recipient_key)
);

CREATE TABLE IF NOT EXISTS pipeline_email_jobs (
    id TEXT PRIMARY KEY,
    raw_message BYTEA,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'complete', 'failed', 'partial')),
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_until TIMESTAMPTZ,
    result JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS pipeline_email_jobs_pending_idx
    ON pipeline_email_jobs (created_at) WHERE status IN ('queued', 'running');
