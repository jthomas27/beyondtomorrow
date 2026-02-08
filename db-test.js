const { Pool } = require('pg');

async function testDatabase() {
  const connectionString = process.env.DATABASE_URL;

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
        source VARCHAR(500),
        source_type VARCHAR(100),
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
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
        embedding vector(1536),
        model VARCHAR(100),
        created_at TIMESTAMP DEFAULT NOW()
      )
    `);
    console.log('✓ Created embeddings table');

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

    // Create indexes
    await client.query('CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_embeddings_chunk_id ON embeddings(chunk_id)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_blog_posts_slug ON blog_posts(slug)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_blog_posts_status ON blog_posts(status)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_knowledge_graph_source ON knowledge_graph(source_chunk_id)');
    await client.query('CREATE INDEX IF NOT EXISTS idx_knowledge_graph_target ON knowledge_graph(target_chunk_id)');
    console.log('✓ All indexes created');

    // Create vector similarity index (ivfflat) — only works if there's data, so we use a simple btree-compatible approach
    // The ivfflat index requires rows to exist; we'll create it with a HNSW index instead which works on empty tables
    try {
      await client.query('CREATE INDEX IF NOT EXISTS idx_embeddings_vector ON embeddings USING hnsw (embedding vector_cosine_ops)');
      console.log('✓ Vector similarity index created');
    } catch (err) {
      console.log('⚠ Vector index will be created when data is added');
    }

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
