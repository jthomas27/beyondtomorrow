#!/usr/bin/env node

/**
 * PostgreSQL Database Connection Test & Setup
 * Tests connection to Railway PostgreSQL and initializes tables for BeyondTomorrow
 */

const { Pool } = require('pg');
const path = require('path');

// Color output helpers
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m'
};

function log(level, message) {
  const timestamp = new Date().toISOString();
  const prefix = {
    'INFO': `${colors.blue}ℹ${colors.reset}`,
    'SUCCESS': `${colors.green}✓${colors.reset}`,
    'ERROR': `${colors.red}✗${colors.reset}`,
    'WARN': `${colors.yellow}⚠${colors.reset}`
  }[level] || level;
  
  console.log(`[${timestamp}] ${prefix} ${message}`);
}

async function main() {
  log('INFO', 'BeyondTomorrow PostgreSQL Connection Test');
  log('INFO', '========================================');
  
  // Check for DATABASE_URL
  if (!process.env.DATABASE_URL) {
    log('WARN', 'DATABASE_URL environment variable not set');
    log('INFO', 'Please set DATABASE_URL=postgresql://user:password@host:port/database');
    process.exit(1);
  }
  
  log('INFO', `Connecting to: ${process.env.DATABASE_URL.replace(/:[^@]*@/, ':***@')}`);
  
  const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    ssl: { rejectUnauthorized: false } // Railway uses SSL
  });

  try {
    // Test basic connection
    log('INFO', 'Testing basic connection...');
    const result = await pool.query('SELECT 1 as test');
    log('SUCCESS', 'Database connection successful!');
    
    // Check PostgreSQL version
    const versionResult = await pool.query('SELECT version()');
    const version = versionResult.rows[0].version.split(' ')[1];
    log('INFO', `PostgreSQL Version: ${version}`);
    
    // Check pgvector extension
    log('INFO', 'Checking pgvector extension...');
    const extensionResult = await pool.query(
      "SELECT * FROM pg_extension WHERE extname = 'vector'"
    );
    
    if (extensionResult.rows.length > 0) {
      log('SUCCESS', 'pgvector extension is installed');
    } else {
      log('WARN', 'pgvector extension not found. Creating...');
      try {
        await pool.query('CREATE EXTENSION IF NOT EXISTS vector');
        log('SUCCESS', 'pgvector extension created');
      } catch (err) {
        log('ERROR', `Failed to create pgvector: ${err.message}`);
      }
    }
    
    // Create BeyondTomorrow tables
    log('INFO', 'Setting up BeyondTomorrow schema...');
    
    // 1. Documents table - stores source documents/content
    await pool.query(`
      CREATE TABLE IF NOT EXISTS documents (
        id SERIAL PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        content TEXT NOT NULL,
        source VARCHAR(255),
        source_type VARCHAR(50),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);
    log('SUCCESS', 'Created documents table');
    
    // 2. Chunks table - stores document chunks for embedding
    await pool.query(`
      CREATE TABLE IF NOT EXISTS chunks (
        id SERIAL PRIMARY KEY,
        document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
        chunk_index INTEGER,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);
    log('SUCCESS', 'Created chunks table');
    
    // 3. Embeddings table - stores vector embeddings with pgvector
    await pool.query(`
      CREATE TABLE IF NOT EXISTS embeddings (
        id SERIAL PRIMARY KEY,
        chunk_id INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
        embedding vector(1536),
        model VARCHAR(100) DEFAULT 'text-embedding-3-small',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);
    log('SUCCESS', 'Created embeddings table');
    
    // 4. Blog posts table - stores generated blog posts
    await pool.query(`
      CREATE TABLE IF NOT EXISTS blog_posts (
        id SERIAL PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        slug VARCHAR(255) UNIQUE NOT NULL,
        content TEXT NOT NULL,
        summary TEXT,
        status VARCHAR(50) DEFAULT 'draft',
        published_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);
    log('SUCCESS', 'Created blog_posts table');
    
    // 5. Knowledge graph table - semantic relationships
    await pool.query(`
      CREATE TABLE IF NOT EXISTS knowledge_graph (
        id SERIAL PRIMARY KEY,
        source_chunk_id INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
        target_chunk_id INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
        relationship_type VARCHAR(100),
        confidence FLOAT DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);
    log('SUCCESS', 'Created knowledge_graph table');
    
    // Create indexes for better query performance
    log('INFO', 'Creating indexes...');
    
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_embeddings_chunk_id 
      ON embeddings(chunk_id)
    `);
    
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_chunks_document_id 
      ON chunks(document_id)
    `);
    
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_blog_posts_status 
      ON blog_posts(status)
    `);
    
    await pool.query(`
      CREATE INDEX IF NOT EXISTS idx_blog_posts_published_at 
      ON blog_posts(published_at DESC)
    `);
    
    // Create vector index for similarity search (if pgvector exists)
    try {
      await pool.query(`
        CREATE INDEX IF NOT EXISTS idx_embeddings_vector 
        ON embeddings USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
      `);
      log('SUCCESS', 'Created vector index for similarity search');
    } catch (err) {
      log('WARN', `Vector index creation skipped: ${err.message}`);
    }
    
    log('SUCCESS', 'All indexes created');
    
    // Display connection info
    log('INFO', '========================================');
    log('SUCCESS', 'Database setup complete!');
    log('INFO', '\nDatabase Schema Summary:');
    log('INFO', '  • documents: Source documents/content');
    log('INFO', '  • chunks: Document chunks for embedding');
    log('INFO', '  • embeddings: Vector embeddings (pgvector)');
    log('INFO', '  • blog_posts: Generated blog posts');
    log('INFO', '  • knowledge_graph: Semantic relationships');
    
    log('INFO', '\nTo use in your application:');
    log('INFO', '  const { Pool } = require("pg");');
    log('INFO', '  const pool = new Pool({ connectionString: process.env.DATABASE_URL });');
    
    // Test with a sample query
    log('INFO', '\nTesting with sample query...');
    const tableResult = await pool.query(`
      SELECT table_name 
      FROM information_schema.tables 
      WHERE table_schema = 'public'
      ORDER BY table_name
    `);
    
    log('INFO', 'Created tables:');
    tableResult.rows.forEach(row => {
      log('INFO', `  • ${row.table_name}`);
    });
    
    process.exit(0);
    
  } catch (error) {
    log('ERROR', `Connection failed: ${error.message}`);
    if (error.code === 'ECONNREFUSED') {
      log('ERROR', 'Could not reach PostgreSQL server. Check:');
      log('ERROR', '  • PostgreSQL is running on Railway');
      log('ERROR', '  • DATABASE_URL is correct');
      log('ERROR', '  • Network connectivity to Railway');
    }
    process.exit(1);
  } finally {
    await pool.end();
  }
}

main().catch(err => {
  log('ERROR', `Unexpected error: ${err.message}`);
  process.exit(1);
});
