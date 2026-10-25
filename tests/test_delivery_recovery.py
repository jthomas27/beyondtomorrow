"""Offline regressions for destructive publishing, retries and durable email intake."""
from datetime import datetime, timezone
from email.message import EmailMessage
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from pipeline.integrations.ghost import create_post_safely
from pipeline.tools.newsletter import _eligible_member, _send_member


def response(status, body):
    return httpx.Response(status, json=body, request=httpx.Request('POST', 'https://example.com/'))


@pytest.fixture
def ghost_client():
    client = AsyncMock()
    client.get.return_value = response(200, {'posts': []})
    client.post.return_value = response(201, {'posts': [{
        'id': 'post-1', 'title': 'An existing article', 'url': 'https://example.com/article/', 'status': 'published',
    }]})
    return client


async def test_existing_slug_is_never_deleted(ghost_client, memory_deliveries):
    ghost_client.get.return_value = response(200, {'posts': [{'id': 'existing'}]})
    with pytest.raises(RuntimeError, match='already exists'):
        await create_post_safely(ghost_client, 'https://example.com', {'title': 'An existing article'}, {}, 'file:a')
    ghost_client.delete.assert_not_called()
    ghost_client.post.assert_not_called()


async def test_replayed_publication_returns_original_id(ghost_client, memory_deliveries):
    first = await create_post_safely(ghost_client, 'https://example.com', {'title': 'Article'}, {}, 'file:a')
    second = await create_post_safely(ghost_client, 'https://example.com', {'title': 'New title'}, {}, 'file:a')
    assert first == second
    assert second['id'] == 'post-1'
    ghost_client.post.assert_awaited_once()


async def test_uncertain_create_is_not_blindly_retried(ghost_client, memory_deliveries):
    ghost_client.post.side_effect = httpx.ReadTimeout('response lost')
    with pytest.raises(httpx.ReadTimeout):
        await create_post_safely(ghost_client, 'https://example.com', {'title': 'Article'}, {}, 'file:a')
    with pytest.raises(RuntimeError, match='uncertain'):
        await create_post_safely(ghost_client, 'https://example.com', {'title': 'Article'}, {}, 'file:a')
    ghost_client.post.assert_awaited_once()


def test_newsletter_requires_subscription_and_no_suppression():
    member = {'status': 'free', 'subscribed': True, 'newsletters': [{'id': 'chosen'}]}
    assert _eligible_member(member, 'chosen')
    assert not _eligible_member(member, 'other')
    assert not _eligible_member({**member, 'subscribed': False}, 'chosen')
    assert not _eligible_member({**member, 'newsletters': []}, 'chosen')
    assert not _eligible_member({**member, 'email_suppression': {'suppressed': True}}, 'chosen')


async def test_newsletter_retries_only_failed_recipients(memory_deliveries):
    client = AsyncMock()
    client.post.side_effect = [response(200, {'id': 'sent-a'}), response(400, {}), response(200, {'id': 'sent-b'})]
    assert await _send_member(client, {}, 'article', 'a@example.com', {'subject': 'same'}) == 'sent'
    with pytest.raises(RuntimeError):
        await _send_member(client, {}, 'article', 'b@example.com', {'subject': 'same'})
    assert await _send_member(client, {}, 'article', 'a@example.com', {'subject': 'changed'}) == 'already_sent'
    assert await _send_member(client, {}, 'article', 'b@example.com', {'subject': 'same'}) == 'sent'
    assert client.post.await_count == 3


async def test_uncertain_newsletter_reuses_idempotency_key_and_original_payload(memory_deliveries, monkeypatch):
    monkeypatch.setattr('pipeline.tools.newsletter.asyncio.sleep', AsyncMock())
    client = AsyncMock()
    client.post.side_effect = httpx.ReadTimeout('response lost')
    with pytest.raises(RuntimeError, match='uncertain'):
        await _send_member(client, {}, 'article', 'a@example.com', {'subject': 'original'})
    client.post.side_effect = None
    client.post.return_value = response(200, {'id': 'original-send'})
    await _send_member(client, {}, 'article', 'a@example.com', {'subject': 'changed'})
    calls = client.post.await_args_list
    assert len({c.kwargs['headers']['Idempotency-Key'] for c in calls}) == 1
    assert all(c.kwargs['json'] == {'subject': 'original'} for c in calls)


async def test_expired_uncertain_newsletter_is_held_for_reconciliation(memory_deliveries):
    client = AsyncMock()
    from pipeline.storage.deliveries import delivery_record
    async with delivery_record('newsletter', 'article', __import__('hashlib').sha256(b'a@example.com').hexdigest()) as record:
        await record.save('sending', data={'started_at': 0, 'payload': {}})
    with pytest.raises(RuntimeError, match='reconciliation'):
        await _send_member(client, {}, 'article', 'a@example.com', {})
    client.post.assert_not_called()


def test_email_sender_requires_receiver_dmarc_and_domain_alignment():
    from pipeline.email_listener import _authenticated_sender
    message = EmailMessage()
    assert not _authenticated_sender(message, 'allowed@example.com')
    message['Authentication-Results'] = 'fr-int-smtpin29.hostinger.io; dmarc=pass header.from=example.com; spf=pass'
    assert _authenticated_sender(message, 'Allowed <allowed@example.com>')
    assert not _authenticated_sender(message, 'allowed@other.com')
    del message['Authentication-Results']
    message['Authentication-Results'] = 'attacker.example; dmarc=pass header.from=example.com'
    assert not _authenticated_sender(message, 'allowed@example.com')

    del message['Authentication-Results']
    message['Authentication-Results'] = 'fr-int-smtpin29.hostinger.io; dmarc=fail header.from=example.com'
    message['Authentication-Results'] = 'fr-int-smtpin29.hostinger.io; dmarc=pass header.from=example.com'
    assert not _authenticated_sender(message, 'allowed@example.com')


def test_unsubscribe_uses_native_ghost_url_without_email_address():
    from pipeline.tools.newsletter import _unsubscribe_url
    result = _unsubscribe_url({'uuid': 'member-uuid', 'unsubscribe_url': 'https://example.com/unsubscribe/?uuid=member-uuid'},
                              {'uuid': 'newsletter-uuid'}, 'https://example.com')
    assert 'uuid=member-uuid' in result
    assert 'newsletter=newsletter-uuid' in result
    assert 'email=' not in result
    with pytest.raises(ValueError):
        _unsubscribe_url({'unsubscribe_url': 'https://attacker.example/unsubscribe'}, {'uuid': 'n'}, 'https://example.com')


async def test_unconfirmed_publisher_url_cannot_authorise_delivery(monkeypatch):
    from pipeline.workflows.publishing import confirmed_publication
    pool = AsyncMock()
    pool.fetchrow.return_value = None
    monkeypatch.setattr('pipeline.db.get_pool', AsyncMock(return_value=pool))
    with pytest.raises(RuntimeError, match='No confirmed'):
        await confirmed_publication('edited.md')
    pool.fetchrow.return_value = {'external_id': 'id', 'data': {
        'status': 'published', 'url': 'https://attacker.example/article/', 'id': 'id'}}
    monkeypatch.setenv('GHOST_URL', 'https://example.com')
    with pytest.raises(RuntimeError, match='configured site'):
        await confirmed_publication('edited.md')


async def test_expired_or_reassigned_job_lease_cannot_be_renewed(monkeypatch):
    from pipeline.storage.email_jobs import heartbeat
    pool = AsyncMock()
    pool.execute.return_value = 'UPDATE 0'
    monkeypatch.setattr('pipeline.storage.email_jobs.get_pool', AsyncMock(return_value=pool))
    with pytest.raises(RuntimeError, match='changed owner'):
        await heartbeat('job', 2)


async def test_ingestion_failure_does_not_mark_email_read(monkeypatch):
    from pipeline.email_listener import poll_once
    conn = MagicMock()
    conn.uid.side_effect = [('OK', [b'42']), ('OK', [(b'42', b'raw')])]
    monkeypatch.setattr('pipeline.email_listener.connect_imap', lambda: conn)
    monkeypatch.setattr('pipeline.storage.email_jobs.enqueue', AsyncMock(side_effect=RuntimeError('DB unavailable')))
    monkeypatch.setattr('pipeline.storage.email_jobs.claim', AsyncMock(return_value=None))
    await poll_once()
    assert not any(c.args[0] == 'store' for c in conn.uid.call_args_list)


async def test_persist_then_acknowledge_and_complete_job(monkeypatch):
    from pipeline.email_listener import poll_once
    from pipeline.storage.deliveries import job_key
    events = []
    conn = MagicMock()
    def uid(command, *args):
        events.append(command)
        if command == 'search': return 'OK', [b'42']
        if command == 'fetch': return 'OK', [(b'42', b'raw')]
        return 'OK', []
    conn.uid.side_effect = uid
    async def enqueue(raw): events.append('persist')
    async def process(raw):
        assert job_key.get() == 'email:job-1'
        return {'status': 'partial', 'published_url': 'https://example.com/article/'}
    monkeypatch.setattr('pipeline.email_listener.connect_imap', lambda: conn)
    monkeypatch.setattr('pipeline.storage.email_jobs.enqueue', enqueue)
    monkeypatch.setattr('pipeline.storage.email_jobs.claim', AsyncMock(side_effect=[{'id': 'job-1', 'raw_message': b'raw', 'attempts': 1}, None]))
    finish = AsyncMock()
    monkeypatch.setattr('pipeline.storage.email_jobs.finish', finish)
    monkeypatch.setattr('pipeline.email_listener._process_message', process)
    await poll_once()
    assert events.index('persist') < events.index('store')
    finish.assert_awaited_once_with('job-1', 'partial', {'published_url': 'https://example.com/article/'}, attempt=1)
    assert not job_key.get()


@pytest.mark.parametrize('status,expected', [('published', 0), ('failed', 1), ('partial', 2)])
def test_cli_propagates_workflow_exit_status(status, expected, monkeypatch):
    import pipeline.main as cli
    monkeypatch.setattr('sys.argv', ['pipeline', 'BLOG: test'])
    monkeypatch.setattr(cli, '_run_blog_pipeline', AsyncMock(return_value={'status': status}))
    if expected:
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == expected
    else:
        cli.main()
