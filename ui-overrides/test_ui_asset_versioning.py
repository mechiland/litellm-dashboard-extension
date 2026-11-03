"""Ensure patched scripts use distinct URLs rather than stale vendor cache keys."""

import json
import os
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen


BASE = os.environ.get('LITELLM_TEST_BASE_URL', 'http://127.0.0.1:4000').rstrip('/')


class DashboardAssetVersionTests(unittest.TestCase):
    def test_model_page_references_the_versioned_refresh_button_bundle(self):
        try:
            with urlopen(BASE + '/ui/ui-extension-manifest.json', timeout=10) as response:
                manifest = json.load(response)
        except HTTPError as error:
            self.fail(f'Dashboard extension manifest is missing: HTTP {error.code}')
        assets = manifest['assets']
        matches = []
        for original, versioned in assets.items():
            with urlopen(BASE + '/litellm-asset-prefix/_next/static/chunks/' + versioned, timeout=10) as response:
                if b'refresh-provider-models' in response.read():
                    matches.append((original, versioned))
        self.assertEqual(len(matches), 1, 'Expected one refresh button bundle')
        original, versioned = matches[0]
        self.assertNotEqual(original, versioned)
        for path in ['/ui/models-and-endpoints/',
                     '/ui/models-and-endpoints/index.txt',
                     '/ui/models-and-endpoints/__next._full.txt']:
            with self.subTest(path=path):
                with urlopen(BASE + path, timeout=10) as response:
                    html = response.read().decode()
                self.assertTrue(versioned in html, f'{path} references a stale script')
        with urlopen(BASE + '/litellm-asset-prefix/_next/static/chunks/' + versioned,
                     timeout=10) as response:
            script = response.read().decode()
        self.assertTrue('refresh-provider-models' in script)


if __name__ == '__main__':
    unittest.main(verbosity=2)
