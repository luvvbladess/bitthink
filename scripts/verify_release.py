"""Read-only smoke check after publishing a BitThink release."""
import argparse
import hashlib
import json
import re
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='https://bit-think.space')
    parser.add_argument('--index-sha256')
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    def get(path):
        for attempt in range(3):
            try:
                with urllib.request.urlopen(base + path, timeout=15) as response:
                    return response.read(), response.headers
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(.5 * (attempt + 1))
    index, headers = get('/')
    if args.index_sha256:
        assert hashlib.sha256(index).hexdigest() == args.index_sha256, 'Unexpected frontend version'
    assert 'no-cache' in headers.get('Cache-Control', ''), 'Entry document must refresh after deployment'
    for path in ['/chat', '/settings', '/billing', '/login']:
        document, _ = get(path)
        assert document == index, 'Route has an inconsistent entry document: ' + path
    for path in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', index.decode()):
        _, asset_headers = get(path)
        assert 'immutable' in asset_headers.get('Cache-Control', ''), 'Hashed asset cache policy changed'
    for path in ['/api/health', '/api/ready']:
        body, _ = get(path)
        assert json.loads(body)['status'] == 'ok', 'Service is not ready: ' + path
    print('PASS published routes, frontend version, assets, API and generation worker readiness')


if __name__ == '__main__':
    main()
