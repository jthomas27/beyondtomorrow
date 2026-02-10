# PostgreSQL + pgvector Setup Guide

A step-by-step guide to adding a PostgreSQL database with pgvector to your **caring-alignment** project on Railway.

> **Status:** ✅ Complete — pgvector service deployed, tables created, connection verified.

---

## What's Set Up

- A **PostgreSQL 18 database** with pgvector hosted on Railway (using the [pgvector template](https://railway.com/template/pgvector))
- The **pgvector extension** for storing and searching AI embeddings (1536-dimension vectors)
- Five tables: `documents`, `chunks`, `embeddings`, `blog_posts`, and `knowledge_graph`
- Vector similarity index (HNSW) for fast nearest-neighbor searches

---

## Prerequisites

- A Railway account ([railway.app](https://railway.app))
- Your project linked in Railway (Project ID: `752fdaea-fd96-4521-bec6-b7d5ef451270`)
- The Railway CLI installed locally (`npm i -g @railway/cli`)

---

## Step 1: Add pgvector to Your Railway Project

**Important:** Use the pgvector template, not the standard PostgreSQL database. The standard one does not include the pgvector extension.

Via CLI:
```bash
railway deploy --template 3jJFCA
```

Or via the dashboard:
1. Open the [pgvector template](https://railway.com/new/template/3jJFCA)
2. Deploy it into your existing **caring-alignment** project
3. Wait for the status indicator to turn **green** (Running)

---

## Step 2: Copy the Connection String

1. Click on the **pgvector** service in your project canvas
2. Go to the **Variables** tab
3. Find `DATABASE_URL_PRIVATE` (for service-to-service) or `DATABASE_URL` (for external access) and copy its value

Via CLI:
```bash
railway link --service pgvector
railway variables --kv | grep DATABASE_URL
```

> It looks like: `postgres://postgres:password@pgvector.railway.internal:5432/railway`

---

## Step 3: Add the Connection String to Your App Service

Via CLI:
```bash
railway link --service beyondtomorrow
railway variables --set "DATABASE_URL=<paste the DATABASE_URL_PRIVATE value from Step 2>"
```

Or via the dashboard:
1. In the same Railway project, click on your **beyondtomorrow** service
2. Go to the **Variables** tab
3. Click **+ New Variable**
4. Set the **Name** to `DATABASE_URL`
5. Paste the **private** connection string from Step 2
6. Click **Add**
7. **Restart** the beyondtomorrow service so it picks up the new variable

---

## Step 4: Test the Connection & Create Tables

From Railway's environment:
```bash
railway run npm run db:test
```

Or locally (use the **public** `DATABASE_URL`, not the private one):
```bash
DATABASE_URL='<paste public DATABASE_URL here>' npm run db:test
```

> **Note:** The private URL (`pgvector.railway.internal`) only works between Railway services. When running from your local machine, use the public URL (the one with `proxy.rlwy.net`).

This single command will:

- ✅ Connect to your new PostgreSQL database
- ✅ Enable the pgvector extension
- ✅ Create all five tables (see below)
- ✅ Create indexes for fast queries

### What Success Looks Like

```
✓ Database connection successful!
✓ PostgreSQL Version: 16.x
✓ pgvector extension is installed
✓ Created documents table
✓ Created chunks table
✓ Created embeddings table
✓ Created blog_posts table
✓ Created knowledge_graph table
✓ All indexes created
✓ Database setup complete!
```

---

## Database Tables Reference

| Table | Purpose |
|-------|---------|
| `documents` | Source documents and content |
| `chunks` | Smaller pieces of documents, ready for embedding |
| `embeddings` | Vector embeddings (1536 dimensions) for similarity search |
| `blog_posts` | Generated blog articles with status tracking |
| `knowledge_graph` | Semantic relationships between chunks |

---

## Connecting in Your Code

```javascript
const { Pool } = require('pg');

const pool = new Pool({
  connectionString: process.env.DATABASE_URL
});

const result = await pool.query('SELECT * FROM documents LIMIT 5');
```

---

## Searching with Vectors

Once you've stored embeddings, find similar content like this:

```sql
SELECT
  chunks.content,
  embeddings.embedding <-> query_embedding AS distance
FROM embeddings
JOIN chunks ON embeddings.chunk_id = chunks.id
ORDER BY embeddings.embedding <-> query_embedding
LIMIT 5;
```

The `<->` operator measures how similar two vectors are (lower = more similar).

---

## Viewing Tables with pgAdmin

Railway's dashboard doesn't show a database explorer, but you can use **pgAdmin** — a free, open-source PostgreSQL management tool with a web interface.

### Option 1: Online pgAdmin (No Installation)

1. Go to [pgadmin.io/deploy/pgadmin-online/](https://www.pgadmin.org/docs/pgadmin4/latest/deployment/pgadmin_online.html) or use [pgAdmin Cloud](https://www.pgadmin.org/pgadmin4/online/) if available
2. Create an account or log in
3. Click **Add New Server**
4. Fill in the connection details:
   - **Name**: `caring-alignment-pgvector`
   - **Host name/address**: `ballast.proxy.rlwy.net` (from `railway variables`)
   - **Port**: `32490` (from `railway variables`)
   - **Username**: `postgres` (from `railway variables`)
   - **Password**: Paste your `PGPASSWORD` (from `railway variables`)
   - **Database**: `railway`
5. Click **Save**
6. Expand the server in the left panel → **Databases** → **railway** → **Schemas** → **public** → **Tables**

### Option 2: Local pgAdmin Installation

1. **Install pgAdmin locally**:
   ```bash
   brew install pgadmin4    # macOS
   # or download from https://www.pgadmin.org/download/
   ```

2. **Launch pgAdmin** and access it at `http://localhost:5050`

3. **Add your Railway database**:
   - Create a new server with the same connection details as Option 1 above

### Option 3: Command-Line (psql)

If you have PostgreSQL installed:

```bash
# Get the password from Railway
PGPASSWORD='<paste password from railway variables>' psql \
  -h ballast.proxy.rlwy.net \
  -p 32490 \
  -U postgres \
  -d railway

# Then in psql prompt:
\dt                    -- List all tables
\d documents           -- Show table structure
SELECT * FROM documents LIMIT 5;  -- Query data
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `DATABASE_URL environment variable not set` | Make sure you added the variable to your **beyondtomorrow** service (not the PostgreSQL service) and restarted it. Run `railway variables` to double-check. |
| `Connection refused` | Check that the PostgreSQL service shows a green "Running" status. Wait 30 seconds and try again. |
| `pgvector extension not found` | The test script creates it automatically. Railway's PostgreSQL includes pgvector by default. |

---

## Next Steps

1. Populate the database by creating a RAG workflow to generate embeddings
2. Query vectors with similarity search to power your AI features
