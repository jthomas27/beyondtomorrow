"""Ghost authentication and durable, non-destructive publication."""
import time
import jwt



async def create_post_safely(client, base_url, payload, headers, source_key):
    """Return a durable publication receipt; never delete or blindly retry a post.

    A response lost after creation is ambiguous. Preserve the record for operator
    reconciliation rather than creating a second article.
    """
    from pipeline.storage.deliveries import delivery_record, job_key
    key = job_key.get() or source_key
    async with delivery_record('ghost', key) as receipt:
        if receipt.status == 'sent':
            return receipt.data
        if receipt.status == 'sending':
            raise RuntimeError('Previous Ghost creation outcome is uncertain; reconcile the saved delivery before retrying')
        # A title collision is not permission to replace a published article.
        import re
        slug = re.sub(r'[^\w\s-]', '', payload['title'].lower()).strip()
        slug = re.sub(r'[\s_]+', '-', slug)
        check = await client.get(base_url + '/ghost/api/admin/posts/',
                                 params={'filter': f'slug:{slug}', 'fields': 'id,slug', 'limit': 1}, headers=headers)
        check.raise_for_status()
        if check.json().get('posts'):
            raise RuntimeError('An article with this title already exists; use an explicit update by Ghost ID')
        await receipt.save('sending')
        response = await client.post(base_url + '/ghost/api/admin/posts/',
                                     json={'posts': [payload]}, headers=headers)
        if 400 <= response.status_code < 500 and response.status_code != 408:
            await receipt.save('failed')
        response.raise_for_status()
        post = response.json()['posts'][0]
        # Store only the public receipt, not the full authenticated API response.
        result = {k: post[k] for k in ('id', 'title', 'url', 'status')}
        result['feature_image'] = payload.get('feature_image', '')
        await receipt.save('sent', str(post['id']), result)
        return result

def create_admin_token(admin_key: str) -> str:
    key_id, secret = admin_key.split(":", 1)
    now = int(time.time())
    return jwt.encode({"iat": now, "exp": now + 300, "aud": "/admin/"},
                      bytes.fromhex(secret), algorithm="HS256",
                      headers={"alg": "HS256", "typ": "JWT", "kid": key_id})

