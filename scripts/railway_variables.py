"""List Railway variable names and presence using the supported CLI; never values."""
import argparse
import json
import subprocess

SERVICES = {'ghost': '0daf496c-e14f-41d4-b89b-3624a778c99d',
            'email-worker': '15b13afb-8515-49e9-ab38-7e138069064f'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service', choices=SERVICES, default='email-worker', nargs='?')
    args = parser.parse_args()
    result = subprocess.run(['railway', 'variables', '--service', SERVICES[args.service], '--json'], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit('Railway variable inventory failed; CLI response withheld to protect credentials.')
    for key, value in sorted(json.loads(result.stdout).items()):
        print(f'{key}: {"set" if value else "empty"}')


if __name__ == '__main__':
    main()
