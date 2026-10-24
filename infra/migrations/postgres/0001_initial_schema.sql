-- Non-destructive bootstrap/adoption of the current pipeline schema.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
        id SERIAL PRIMARY KEY,
        title VARCHAR(500),
        content TEXT,
        source VARCHAR(500) UNIQUE NOT NULL,
        source_type VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
      );

CREATE TABLE IF NOT EXISTS chunks (
        id SERIAL PRIMARY KEY,
        document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
        chunk_index INTEGER,
        content TEXT,
        created_at TIMESTAMP DEFAULT NOW()
      );

CREATE TABLE IF NOT EXISTS embeddings (
        id SERIAL PRIMARY KEY,
        chunk_id INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
        content TEXT NOT NULL,
        embedding vector(1536),
        metadata JSONB DEFAULT '{}',
        model VARCHAR(100) DEFAULT 'text-embedding-3-small',
        created_at TIMESTAMPTZ DEFAULT NOW()
      );

CREATE TABLE IF NOT EXISTS rate_limit_log (
        id SERIAL PRIMARY KEY,
        agent_name VARCHAR(100) NOT NULL,
        model VARCHAR(100) NOT NULL,
        tokens_input INTEGER DEFAULT 0,
        tokens_output INTEGER DEFAULT 0,
        request_type VARCHAR(50) DEFAULT 'chat',
        session_id VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT NOW()
      );

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_attribute
        WHERE attrelid = 'embeddings'::regclass AND attname = 'embedding'
          AND format_type(atttypid, atttypmod) NOT LIKE '%vector(1536)'
    ) THEN
        RAISE EXCEPTION 'Existing embeddings schema requires a reviewed dimension migration';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS embeddings_hnsw_idx
                    ON embeddings USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64);


                CREATE TABLE IF NOT EXISTS pipeline_logs (
                    id          BIGSERIAL PRIMARY KEY,
                    run_id      TEXT        NOT NULL DEFAULT '',
                    event       TEXT        NOT NULL,
                    stage       TEXT,
                    ts          TIMESTAMPTZ NOT NULL,
                    data        JSONB       NOT NULL,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS pipeline_logs_run_id_idx
                    ON pipeline_logs (run_id);
                CREATE INDEX IF NOT EXISTS pipeline_logs_ts_idx
                    ON pipeline_logs (ts DESC);
