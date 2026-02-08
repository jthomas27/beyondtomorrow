# Database Connection Setup Guide

## Quick Start

You have a PostgreSQL connection test script ready. Here's how to set it up:

### Step 1: Add PostgreSQL to Railway (if not already done)

**Status**: PostgreSQL service not yet added to Railway project

1. Go to your [Railway Project Dashboard](https://railway.app/project/752fdaea-fd96-4521-bec6-b7d5ef451270)
2. Click **+ New** button (top right)
3. Select **Database** → **PostgreSQL**
4. Railway will provision the database automatically
5. Wait for it to show "Running" status (green indicator)

### Step 2: Get Connection Variables

Once PostgreSQL is running in Railway:

1. Click on the PostgreSQL service
2. Go to the **Variables** tab
3. You'll see: `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`
4. Copy the **DATABASE_URL** value

### Step 3: Set Environment Variable in Railway

1. Go to your **beyondtomorrow** service settings
2. Go to **Variables** tab
3. Add a new variable:
   - **Key**: `DATABASE_URL`
   - **Value**: Paste the PostgreSQL DATABASE_URL from step 2

### Step 4: Test the Connection

Run the connection test:

```bash
npm run db:test              # Local test (requires DATABASE_URL locally)
railway run npm run db:test  # Test via Railway environment
```

## What the Test Does

The `db-test.js` script:

✅ Tests PostgreSQL connectivity
✅ Creates **pgvector extension** (for vector embeddings)
✅ Initializes the following tables:

| Table | Purpose |
|-------|---------|
| `documents` | Source documents/content |
| `chunks` | Document chunks for embedding |
| `embeddings` | Vector embeddings (1536 dimensions) |
| `blog_posts` | Generated blog articles |
| `knowledge_graph` | Semantic relationships between chunks |

✅ Creates indexes for query performance
✅ Creates vector index for similarity search using pgvector

## BeyondTomorrow Database Schema

### documents
```sql
- id (SERIAL PRIMARY KEY)
- title (VARCHAR)
- content (TEXT)
- source (VARCHAR)
- source_type (VARCHAR)
- created_at, updated_at
```

### chunks
```sql
- id (SERIAL PRIMARY KEY)
- document_id (FOREIGN KEY → documents.id)
- chunk_index (INTEGER)
- content (TEXT)
- created_at
```

### embeddings ← Uses pgvector!
```sql
- id (SERIAL PRIMARY KEY)
- chunk_id (FOREIGN KEY → chunks.id)
- embedding (vector(1536)) ← OpenAI embedding size
- model (VARCHAR)
- created_at
```

### blog_posts
```sql
- id (SERIAL PRIMARY KEY)
- title, slug, content, summary
- status (draft, published)
- published_at, created_at, updated_at
```

### knowledge_graph
```sql
- id (SERIAL PRIMARY KEY)
- source_chunk_id, target_chunk_id
- relationship_type (VARCHAR)
- confidence (FLOAT)
- created_at
```

## Using in Your Application

Once set up, connect to the database:

```javascript
const { Pool } = require('pg');

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: { rejectUnauthorized: false } // Railway uses SSL
});

// Query example
const result = await pool.query(
  'SELECT * FROM embeddings WHERE id = $1',
  [1]
);
```

## Troubleshooting

### "DATABASE_URL environment variable not set"
- Ensure you added the variable to Railway service settings
- Restart the service after adding the variable
- Check: `railway variables`

### "pgvector extension not found"
- The script creates it automatically on first run
- If it fails, ensure PostgreSQL has the pgvector package installed (Railway includes this)

### "Connection refused"
- Verify PostgreSQL service is running (green status in Railway)
- Check DATABASE_URL format: `postgresql://user:password@host:port/database`

## Next Steps

1. ✅ Add PostgreSQL service to Railway
2. ✅ Set DATABASE_URL in service variables
3. ✅ Run `railway run npm run db:test` to initialize schema with pgvector
4. Create your RAG workflow to populate embeddings
5. Query vectors with: `SELECT * FROM embeddings WHERE embedding <-> query_vector < threshold`

## Vector Search Example

Once embeddings are in the database:

```sql
-- Find similar chunks
SELECT 
  chunks.id, 
  chunks.content,
  embeddings.embedding <-> query_embedding AS distance
FROM embeddings
JOIN chunks ON embeddings.chunk_id = chunks.id
ORDER BY embeddings.embedding <-> query_embedding
LIMIT 5;
```

The `<->` operator is the pgvector cosine distance operator.
