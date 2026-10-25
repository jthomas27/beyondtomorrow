"""Build Ghost injection files from maintained HTML, CSS and JavaScript sources."""
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'theme' / 'src'


def render(part):
    def include(match):
        kind, filename = match.groups()
        content = (SOURCE / filename).read_text()
        tag = 'script' if kind == 'script' else 'style'
        if f'</{tag}' in content.lower():
            raise ValueError('An included asset contains an unexpected closing tag')
        return f'<{tag}>{content}</{tag}>'
    return re.sub(r'<!-- include:(script|style) ([a-z0-9-]+\.(?:js|css)) -->', include,
                  (SOURCE / f'{part}.html').read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for part in ('header', 'footer'):
        path = ROOT / 'theme' / f'{part}.txt'
        content = render(part)
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit(f'Rebuild theme/{part}.txt with scripts/build_theme.py')
        else:
            path.write_text(content)
    print('Theme output matches sources.' if args.check else 'Built Ghost injection files.')


if __name__ == '__main__':
    main()
