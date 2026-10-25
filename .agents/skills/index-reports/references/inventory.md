# Read-only PDF inventory

Run from the repository root. Never print DATABASE_URL.

```bash
.venv/bin/python - <<'PYCODE'
from pathlib import Path
import os
import psycopg2
from dotenv import load_dotenv
load_dotenv(Path.cwd() / '.env')
with psycopg2.connect(os.environ['DATABASE_URL']) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT source FROM documents WHERE source_type='pdf'")
        indexed = {row[0] for row in cur.fetchall()}
files = sorted(Path('reports').glob('*.pdf'))
pending = [p for p in files if p.as_posix() not in indexed]
print(f'{len(files)} local PDFs | {len(pending)} pending')
for path in pending:
    print(path.as_posix())
PYCODE
```
