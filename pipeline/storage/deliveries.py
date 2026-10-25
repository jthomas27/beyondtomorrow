"""Durable delivery receipts and a session lock around each external operation.

A crashed/ambiguous create remains 'sending': providers without idempotency must
be reconciled before retrying. A missing database never falls back to local state.
"""
from contextlib import asynccontextmanager
from contextvars import ContextVar
import hashlib
import json

from pipeline.db import get_pool

job_key: ContextVar[str] = ContextVar('pipeline_job_key', default='')


def private_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class DeliveryRecord:
    def __init__(self, connection, keys, row):
        self.connection, self.keys = connection, keys
        self.status = row['status']
        self.external_id = row['external_id']
        self.data = json.loads(row['data']) if isinstance(row['data'], str) else row['data']
        self.updated_at = row['updated_at']

    async def save(self, status, external_id=None, data=None):
        self.status = status
        if data is not None:
            self.data = data
        self.external_id = external_id
        await self.connection.execute(
            'UPDATE pipeline_deliveries SET status=$4, external_id=$5, data=$6::jsonb, '
            'updated_at=NOW() WHERE channel=$1 AND article_key=$2 AND recipient_key=$3',
            *self.keys, status, external_id, json.dumps(self.data),
        )


@asynccontextmanager
async def delivery_record(channel: str, article: str, recipient: str = ''):
    keys = (channel, article, recipient)
    lock = int.from_bytes(hashlib.sha256(json.dumps(keys).encode()).digest()[:8], 'big', signed=True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        locked = await conn.fetchval('SELECT pg_try_advisory_lock($1)', lock)
        if not locked:
            raise RuntimeError('Delivery is already being processed')
        try:
            await conn.execute(
                'INSERT INTO pipeline_deliveries(channel,article_key,recipient_key) '
                'VALUES($1,$2,$3) ON CONFLICT DO NOTHING', *keys,
            )
            row = await conn.fetchrow(
                'SELECT status, external_id, data, updated_at FROM pipeline_deliveries '
                'WHERE channel=$1 AND article_key=$2 AND recipient_key=$3', *keys,
            )
            yield DeliveryRecord(conn, keys, row)
        finally:
            await conn.execute('SELECT pg_advisory_unlock($1)', lock)
