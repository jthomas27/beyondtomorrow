"""Temporary script to check email-worker deployment status."""
import os, json, httpx
from pathlib import Path

for line in Path(__file__).parent.parent.joinpath('.env').read_text().splitlines():
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, _, v = line.partition('=')
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

token = os.environ['RAILWAY_TOKEN']
service_id = '15b13afb-8515-49e9-ab38-7e138069064f'
env_id = 'c9dfebe4-097a-4151-be37-2b1fcd414e74'

q = """
query Deps($s: String!, $e: String!) {
  deployments(input: { serviceId: $s, environmentId: $e }, last: 5) {
    edges { node { id status createdAt } }
  }
}
"""
r = httpx.post('https://backboard.railway.app/graphql/v2',
    json={'query': q, 'variables': {'s': service_id, 'e': env_id}},
    headers={'Authorization': f'Bearer {token}'}, timeout=15)
data = r.json()
if 'errors' in data:
    print('GraphQL errors:', json.dumps(data['errors'], indent=2))
else:
    print("email-worker deployments (newest last):")
    for edge in data['data']['deployments']['edges']:
        n = edge['node']
        print(f"  {n['createdAt'][:19]}  {n['status']:<20} {n['id'][:16]}")
