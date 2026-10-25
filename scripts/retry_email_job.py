"""List unfinished email jobs; --retry ID explicitly requeues a failed/partial job.

Known delivery receipts are preserved. Ambiguous provider outcomes still require
reconciliation; requeuing never clears a receipt or blindly resends a delivery.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.settings import load_environment
from pipeline.db import get_pool, close_pool


async def run(identifier):
    load_environment()
    pool = await get_pool()
    try:
        if identifier:
            row = await pool.fetchrow(
                "UPDATE pipeline_email_jobs SET status='queued',lease_until=NULL,updated_at=NOW() "
                "WHERE id=$1 AND status IN ('failed','partial') AND raw_message IS NOT NULL RETURNING id", identifier)
            print('Job requeued with existing delivery receipts.' if row else 'No retryable retained job matched.')
        else:
            for row in await pool.fetch("SELECT id,status,attempts FROM pipeline_email_jobs WHERE status<>'complete' ORDER BY created_at DESC LIMIT 30"):
                print(row['id'], row['status'], 'attempts=', row['attempts'])
    finally:
        await close_pool()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retry')
    try:
        asyncio.run(run(parser.parse_args().retry))
    except Exception as exc:
        raise SystemExit(f'Job operation failed ({type(exc).__name__}); details withheld') from None
