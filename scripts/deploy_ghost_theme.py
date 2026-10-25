"""Deploy generated Ghost theme injection or restore a private backup.

Default is a local build check. --apply writes Ghost settings and checks the
homepage once. --rollback PATH with --apply restores a previous backup.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import httpx
from dotenv import dotenv_values
from build_theme import ROOT, render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', type=Path)
    args = parser.parse_args()
    keys = {'header': 'codeinjection_head', 'footer': 'codeinjection_foot'}
    desired = {key: render(part) for part, key in keys.items()}
    if args.rollback:
        desired = json.loads(args.rollback.read_text())
        if set(desired) != set(keys.values()) or not all(isinstance(v, str) for v in desired.values()):
            raise ValueError('Invalid theme injection backup')
    else:
        for part, key in keys.items():
            if (ROOT / 'theme' / f'{part}.txt').read_text() != desired[key]:
                raise ValueError('Build the theme before deploying')
    if not args.apply:
        print('Theme is ready. --apply deploys; --rollback PATH --apply restores a backup.')
        return
    env = dotenv_values(ROOT / '.env')
    base = (os.environ.get('GHOST_URL') or env['GHOST_URL']).rstrip('/')
    with httpx.Client(base_url=base, headers={'Origin': base}, timeout=30) as client:
        response = client.post('/ghost/api/admin/session/', json={
            'username': os.environ.get('GHOST_ADMIN_EMAIL') or env['GHOST_ADMIN_EMAIL'],
            'password': os.environ.get('GHOST_ADMIN_PASSWORD') or env['GHOST_ADMIN_PASSWORD'],
        })
        if response.status_code != 201:
            raise RuntimeError(f'Ghost staff login failed (HTTP {response.status_code})')
        response = client.get('/ghost/api/admin/settings/')
        response.raise_for_status()
        current = {s['key']: s.get('value') or '' for s in response.json()['settings'] if s['key'] in desired}
        backup = ROOT / 'logs' / 'theme-backups' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        backup.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
            json.dump(current, output)
        response = client.put('/ghost/api/admin/settings/', json={
            'settings': [{'key': key, 'value': value} for key, value in desired.items()],
        })
        response.raise_for_status()
        homepage = client.get('/')
        present = homepage.status_code == 200 and all(value.strip() in homepage.text for value in desired.values())
        print('Theme deployed. Homepage:', 'updated injection present' if present else 'update not yet confirmed; may be cached')
        print('Private rollback copy:', backup.relative_to(ROOT))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Theme deployment stopped ({type(exc).__name__}); credential-bearing details withheld') from None
