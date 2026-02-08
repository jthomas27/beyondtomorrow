# Railway PostgreSQL + pgvector Setup Guide

Step-by-step instructions to create a PostgreSQL database in Railway with pgvector extension and link it to your project.

## Part 1: Create PostgreSQL Database in Railway

### Step 1: Log into Railway Dashboard
1. Navigate to [railway.app](https://railway.app)
2. Log in with your account credentials
3. Select your project or create a new one

### Step 2: Add PostgreSQL Service
1. Click the **+ New** button in your project
2. Select **Database** from the menu
3. Choose **PostgreSQL** from the available databases
4. Railway will automatically provision a PostgreSQL instance

### Step 3: Verify Database is Running
1. Click on the PostgreSQL service in your project canvas
2. Verify the status shows as **Running** (green indicator)
3. Note the default credentials that appear in the settings

## Part 2: Enable pgvector Extension

### Step 4: Access Database Shell
1. In the PostgreSQL service panel, click the **Connect** tab
2. Copy the connection string or use the **Query** tab to access the database

### Step 5: Create pgvector Extension
Run the following SQL command in the database query console:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Step 6: Verify Installation
Confirm pgvector is installed:

```sql
SELECT * FROM pg_extension WHERE extname = 'vector';
```

You should see a result showing the vector extension is installed.

## Part 3: Link Database to Your Project

### Step 7: Get Connection Credentials
1. In the PostgreSQL service panel, go to the **Variables** tab
2. Copy these essential variables:
   - `DATABASE_URL` - Full connection string (most important)
   - `PGHOST` - Hostname
   - `PGPORT` - Port (usually 5432)
   - `PGUSER` - Username
   - `PGPASSWORD` - Password
   - `PGDATABASE` - Database name

### Step 8: Add Environment Variables to Your Project
1. Open your project settings in Railway
2. Go to the **Variables** tab for your main service
3. Add or update the following variables:

```
DATABASE_URL=postgresql://[user]:[password]@[host]:[port]/[database]
```

Or add individual variables:

```
PGHOST=[hostname]
PGPORT=[port]
PGUSER=[username]
PGPASSWORD=[password]
PGDATABASE=[database_name]
```

### Step 9: Update Application Connection String
In your project's code, update your database connection to use the Railway environment variables.

#### For Node.js (with pg or sequelize):
```javascript
const { Pool } = require('pg');

const pool = new Pool({
  connectionString: process.env.DATABASE_URL
});
```

#### For Python (with psycopg2 or SQLAlchemy):
```python
import os
from sqlalchemy import create_engine

database_url = os.getenv('DATABASE_URL')
engine = create_engine(database_url)
```

#### For TypeScript (with drizzle, prisma, etc.):
```typescript
import { Pool } from 'pg';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL
});
```

### Step 10: Deploy Changes
1. Commit and push your changes to your repository
2. Railway will automatically redeploy your project
3. Verify in the deployment logs that the connection is successful

## Part 4: Test the Connection

### Step 11: Verify Database Connection
Once deployed, test the connection with a simple query:

```sql
SELECT 1;
SELECT * FROM pg_extension WHERE extname = 'vector';
```

### Step 12: Test pgvector Functionality (Optional)
If you'll be using pgvector for embeddings, test with a simple vector operation:

```sql
CREATE TABLE embeddings_test (
  id SERIAL PRIMARY KEY,
  embedding vector(1536)
);

INSERT INTO embeddings_test (embedding) VALUES ('[0.1, 0.2, 0.3]'::vector);

SELECT * FROM embeddings_test;

-- Test vector similarity
SELECT id, embedding <-> '[0.1, 0.2, 0.3]'::vector AS distance
FROM embeddings_test
ORDER BY embedding <-> '[0.1, 0.2, 0.3]'::vector
LIMIT 5;
```

## Troubleshooting

### Connection Refused
- Verify PostgreSQL service is running (green status in Railway)
- Check that credentials are correct
- Ensure your application's firewall/network allows the connection

### pgvector Extension Not Found
```
ERROR: extension "vector" does not exist
```
Run the creation command again:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Environment Variables Not Loaded
- Verify variables are set in Railway project settings
- Restart your service after adding variables
- Check that your code is reading `process.env.DATABASE_URL` (Node) or `os.getenv('DATABASE_URL')` (Python)

## Additional Resources

- [Railway PostgreSQL Docs](https://docs.railway.app/databases/postgresql)
- [pgvector Documentation](https://github.com/pgvector/pgvector)
- [Railway Environment Variables Guide](https://docs.railway.app/develop/variables)

## Next Steps

After successful setup:
1. Create database tables with vector columns for embeddings
2. Set up indexes on vector columns for better query performance: `CREATE INDEX ON table_name USING ivfflat (vector_column)`
3. Implement RAG workflows using pgvector for similarity search
