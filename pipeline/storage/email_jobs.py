"""Persist email requests before acknowledging IMAP; lease jobs across restarts."""
import hashlib
import json
from pipeline.db import get_pool


async def enqueue(raw: bytes) -> str:
    identifier = hashlib.sha256(raw).hexdigest()
    pool = await get_pool()
    await pool.execute(
        'INSERT INTO pipeline_email_jobs(id,raw_message) VALUES($1,$2) '
        'ON CONFLICT(id) DO NOTHING', identifier, raw,
    )
    return identifier


async def claim():
    pool = await get_pool()
    return await pool.fetchrow(
        "UPDATE pipeline_email_jobs SET status='running', attempts=attempts+1, "
        "lease_until=NOW()+INTERVAL '10 minutes', updated_at=NOW() WHERE id=("
        "SELECT id FROM pipeline_email_jobs WHERE status='queued' OR "
        "(status='running' AND lease_until<NOW()) ORDER BY created_at "
        "FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id,raw_message,attempts",
    )


async def heartbeat(identifier: str, attempt: int):
    pool = await get_pool()
    updated = await pool.execute("UPDATE pipeline_email_jobs SET lease_until=NOW()+INTERVAL '10 minutes' "
                       "WHERE id=$1 AND attempts=$2 AND status='running' AND lease_until>NOW()", identifier, attempt)
    if updated != 'UPDATE 1':
        raise RuntimeError('Email job lease expired or changed owner')


async def finish(identifier: str, status: str, result=None, *, attempt: int):
    if status not in {'complete', 'failed', 'partial'}:
        raise ValueError('Invalid terminal email job status')
    pool = await get_pool()
    await pool.execute(
        "UPDATE pipeline_email_jobs SET status=$2,result=$3::jsonb,"
        "raw_message=CASE WHEN $2='complete' THEN NULL ELSE raw_message END,"
        "lease_until=NULL,updated_at=NOW() WHERE id=$1 AND attempts=$4 AND status='running'", identifier, status,
        json.dumps(result or {}), attempt,
    )
