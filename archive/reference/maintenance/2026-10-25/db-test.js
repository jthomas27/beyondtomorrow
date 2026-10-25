const { Pool } = require('pg');

async function testDatabase() {
  const connectionString = process.env.DATABASE_URL_PRIVATE || process.env.DATABASE_URL;

  if (!connectionString) {
    console.error('✗ DATABASE_URL environment variable not set');
    process.exit(1);
  }

  const pool = new Pool({
    connectionString,
  });

  try {
    // Test connection
    const client = await pool.connect();
    console.log('✓ Database connection successful!');

    // Get PostgreSQL version
    const versionResult = await client.query('SELECT version()');
    const version = versionResult.rows[0].version.split(' ').slice(0, 2).join(' ');
    console.log(`✓ ${version}`);

    // Create pgvector extension
    await client.query('CREATE EXTENSION IF NOT EXISTS vector');
    console.log('✓ pgvector extension is installed');

    // Create tables
    await client.query(`
      CREATE TABLE IF NOT EXISTS documents (
        id SERIAL PRIMARY KEY,
        title VARCHAR(500),
        content TEXT,
        source VARCHAR(500) UNIQUE NOT NULL,
        source_type VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
      )
    `);
    console.log('✓ Created documents table');

    await client.query(`
      CREATE TABLE IF NOT EXISTS chunks (
        id SERIAL PRIMARY KEY,
        document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
        chunk_index INTEGER,
        content TEXT,
        created_at TIMESTAMP DEFAULT NOW()
      )
    `);
    console.log('✓ Created chunks table');

    await client.query(`
      CREATE TABLE IF NOT EXISTS embeddings (
        id SERIAL PRIMARY KEY,
        chunk_id INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
        content TEXT NOT NULL,
        embedding vector(384),
        metadata JSONB DEFAULT '{}',
        model VARCHAR(100) DEFAULT 'all-MiniLM-L6-v2',
        created_at TIMESTAMPTZ DEFAULT NOW()
      )
    `);
    console.log('\u2713 Created embeddings table (normalized: chunk_id FK, content denormalized for fast search)');

    await client.query(`
      CREATE TABLE IF NOT EXISTS blog_posts (
        id SERIAL PRIMARY KEY,
        title VARCHAR(500),
        slug VARCHAR(500) UNIQUE,
        content TEXT,
        summary TEXT,
        status VARCHAR(20) DEFAULT 'draft',
        published_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
      )
    `);
    console.log('✓ Created blog_posts table');

    await client.query(`
      CREATE TABLE IF NOT EXISTS knowledge_graph (
        id SERIAL PRIMARY KEY,
        source_chunk_id INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
        target_chunk_id INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
        relationship_type VARCHAR(100),
        confidence FLOAT,
        created_at TIMESTAMP DEFAULT NOW()
      )
    `);
    console.log('✓ Created knowledge_graph table');

    await client.query(`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        version VARCHAR(100) PRIMARY KEY,
        applied_at TIMESTAMPTZ DEFAULT NOW()
      )
    `);
    console.log('✓ Created schema_migrations table');

    await client.query(`
      CREATE TABLE IF NOT EXISTS rate_limit_log (
        id SERIAL PRIMARY KEY,
        agent_name VARCHAR(100) NOT NULL,
        model VARCHAR(100) NOT NULL,
        tokens_input INTEGER DEFAULT 0,
        tokens_output INTEGER DEFAULT 0,
        request_type VARCHAR(50) DEFAULT 'chat',
        session_id VARCHAR(100),
        created_at TIMESTAMPTZ DEFAULT NOW()
      )
    `);
    console.log('✓ Created rate_limit_log table');

    await client.query(`
      CREATE TABLE IF NOT EXISTS agent_sessions (
        id SERIAL PRIMARY KEY,
        session_id VARCHAR(100) UNIQUE NOT NULL,
        agent_name VARCHAR(100) NOT NULL,
        status VARCHAR(20) DEFAULT 'active',
        input TEXT,
        output TEXT,
        error TEXT,
        metadata JSONB DEFAULT '{}',
        started_at TIMESTAMPTZ DEFAULT NOW(),
        completed_at TIMESTAMPTZ
      )
    `);
    console.log('✓ Created agent_sessions table');

    // ---------------------------------------------------------------------------
    // Idempotent ALTER statements — bring existing databases up to the current
    // normalized schema without dropping any data.
    // Run BEFORE index creation so all columns exist when indexes are built.
    // ---------------------------------------------------------------------------

    // Add UNIQUE constraint on documents.source if missing
    await client.query(`
      DO $$
      BEGIN
        IF NOT EXISTS (
          SELECT 1 FROM pg_constraint
          WHERE conrelid = 'documents'::regclass AND conname = 'documents_source_key'
        ) THEN
          ALTER TABLE documents ADD CONSTRAINT documents_source_key UNIQUE (source);
        END IF;
      END$$
    `);

    // Add content column to embeddings if missing (denormalized for fast search reads)
    await client.query(`
      DO $$
      BEGIN
        IF NOT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'embeddings' AND column_name = 'content'
        ) THEN
          ALTER TABLE embeddings ADD COLUMN content TEXT;
        END IF;
      END$$
    `);

    // Add metadata JSONB column to embeddings if missing
    await client.query(`
      DO $$
      BEGIN
        IF NOT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'embeddings' AND column_name = 'metadata'
        ) THEN
          ALTER TABLE embeddings ADD COLUMN metadata JSONB DEFAULT '{}';
        END IF;
      END$$
    `);

    // Add chunk_id FK to embeddings if missing (nullable — existing flat rows stay valid)
    await client.query(`
      DO $$
      BEGIN
        IF NOT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'embeddings' AND column_name = 'chunk_id'
        ) THEN
          ALTER TABLE embeddings
            ADD COLUMN chunk_id INTEGER REFERENCES chunks(id) ON DELETE CASCADE;
        END IF;
      END$$
    `);

    console.log('✓ Schema alterations applied (idempotent)');

    // Create indexes
    await client.query('CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_embeddings_chunk_id ON embeddings(chunk_id)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_embeddings_metadata ON embeddings USING gin (metadata)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_blog_posts_slug ON blog_posts(slug)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_blog_posts_status ON blog_posts(status)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_rate_limit_log_created ON rate_limit_log(created_at)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_rate_limit_log_agent ON rate_limit_log(agent_name, model)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_agent_sessions_session ON agent_sessions(session_id)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status)');
    console.log('✓ All indexes created');

    try {
      await client.query(`
        CREATE INDEX IF NOT EXISTS idx_embeddings_vector
        ON embeddings USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 128)
      `);
      console.log('✓ Vector similarity index created (HNSW, ef_construction=128)');
    } catch (err) {
      console.log('⚠ Vector index will be rebuilt during dimension migration');
    }

    // Record this setup run so migrate-embeddings.py can check preconditions
    await client.query(`
      INSERT INTO schema_migrations (version) VALUES ('001_initial_setup')
      ON CONFLICT (version) DO NOTHING
    `);
    await client.query(`
      INSERT INTO schema_migrations (version) VALUES ('003_normalize_documents_chunks')
      ON CONFLICT (version) DO NOTHING
    `);
    console.log('✓ Recorded schema versions: 001_initial_setup, 003_normalize_documents_chunks');

    // Verify tables
    const tablesResult = await client.query(`
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = 'public'
      ORDER BY table_name
    `);
    const tables = tablesResult.rows.map(r => r.table_name);
    console.log(`\n✓ Database setup complete! Tables: ${tables.join(', ')}`);

    client.release();
  } catch (err) {
    console.error('✗ Database error:', err.message);
    process.exit(1);
  } finally {
    await pool.end();
  }
}

testDatabase();
