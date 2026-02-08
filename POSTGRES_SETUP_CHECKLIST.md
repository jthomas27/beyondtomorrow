# PostgreSQL Setup for BeyondTomorrow - Quick Checklist

## ✅ What's Already Done

- [x] Created `db-test.js` - Full database setup & test script
- [x] Added `pg` dependency to package.json
- [x] Added npm scripts: `npm run db:test` and `npm run db:connect`
- [x] Database schema includes pgvector support (1536-dim embeddings)

## 🚀 What You Need to Do

### 1. Add PostgreSQL Service to Railway
Go to: https://railway.app/project/752fdaea-fd96-4521-bec6-b7d5ef451270

- Click **+ New** button (top right)
- Select **Database** 
- Choose **PostgreSQL**
- Wait for status to turn green

### 2. Get Connection String
Click on the PostgreSQL service → **Variables** tab

You'll see these variables:
- `DATABASE_URL` ← Copy this one!
- `PGHOST`
- `PGPORT`
- `PGUSER`
- `PGPASSWORD`
- `PGDATABASE`

### 3. Add DATABASE_URL to BeyondTomorrow Service

Go to: https://railway.app/project/752fdaea-fd96-4521-bec6-b7d5ef451270

- Click on **beyondtomorrow** service
- Go to **Variables** tab
- Click **+ New Variable**
- Name: `DATABASE_URL`
- Value: Paste the PostgreSQL DATABASE_URL from step 2
- Click **Add**

### 4. Restart Service
- Click on beyondtomorrow service
- Click **Restart** button (or redeploy)

### 5. Test Connection
```bash
railway run npm run db:test
```

This will:
✅ Connect to PostgreSQL
✅ Create pgvector extension
✅ Create all 5 tables (documents, chunks, embeddings, blog_posts, knowledge_graph)
✅ Create indexes for performance
✅ Show success message with table list

## 📊 Tables That Will Be Created

| Table | Type | Purpose |
|-------|------|---------|
| `documents` | Text | Source documents/content |
| `chunks` | Text + FK | Document chunks for embedding |
| `embeddings` | Vector(1536) | Vector embeddings using pgvector |
| `blog_posts` | Text + Metadata | Generated blog articles |
| `knowledge_graph` | Relationships | Semantic relationships |

## 🔍 Vector Search Ready

Once set up, you can query embeddings:

```javascript
// Find similar content
const query = await pool.query(`
  SELECT chunks.id, chunks.content, 
         embeddings.embedding <-> $1::vector as distance
  FROM embeddings
  JOIN chunks ON embeddings.chunk_id = chunks.id
  ORDER BY embeddings.embedding <-> $1::vector
  LIMIT 5
`, [queryVector]);
```

## ⚠️ If Something Goes Wrong

**Error: "DATABASE_URL environment variable not set"**
- Check that you added DATABASE_URL to beyondtomorrow service variables
- Make sure you restarted/redeployed the service
- Run `railway variables` to verify it's there

**Error: "Connection refused"**
- Verify PostgreSQL service status is green (Running)
- Check DATABASE_URL is correct format
- Wait 30 seconds for Railway to fully provision

**Error: "pgvector extension not found"**
- The script creates it automatically on first run
- Railway PostgreSQL includes pgvector by default
- If it still fails, pgvector may need to be enabled in your PostgreSQL plan

## 🎯 Success Indicators

When you run `railway run npm run db:test`, you should see:

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

**Project ID**: 752fdaea-fd96-4521-bec6-b7d5ef451270
**Service**: beyondtomorrow
**Environment**: production
**DB Type**: PostgreSQL + pgvector
