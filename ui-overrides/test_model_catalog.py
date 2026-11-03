"""Verify model choices without running inference or exposing credentials."""

import json
import os
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(path, payload=None, admin=False):
    headers = {"Content-Type": "application/json"}
    if admin:
        headers['Authorization'] = 'Bearer ' + os.environ['LITELLM_TEST_ADMIN_KEY']
    req = Request(os.environ.get('LITELLM_TEST_BASE_URL', 'http://127.0.0.1:4000').rstrip('/') + path, headers=headers,
                  data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with urlopen(req, timeout=25) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


class ModelCatalogTests(unittest.TestCase):
    def test_public_supplier_models_are_available_in_model_picker(self):
        status, catalog = request('/public/litellm_model_cost_map?catalog_only=true')
        self.assertEqual(status, 200)
        for provider in ['openrouter', 'nano-gpt', 'poe', 'synthetic']:
            with self.subTest(provider=provider):
                count = sum(isinstance(v, dict) and v.get('litellm_provider') == provider
                            for v in catalog.values())
                self.assertGreater(count, 0, f'{provider} has no model choices')

    def test_ui_only_model_names_do_not_create_billing_prices(self):
        _, choices = request('/public/litellm_model_cost_map?catalog_only=true')
        _, billing = request('/public/litellm_model_cost_map')
        extras = {name: info for name, info in choices.items()
                  if isinstance(info, dict) and info.get('litellm_provider') in
                  {'openrouter', 'nano-gpt', 'poe', 'synthetic'}}
        self.assertTrue(extras, 'No supplemental model names were loaded')
        for name, info in extras.items():
            self.assertTrue(name not in billing, f'UI-only name changed billing: {name}')
            self.assertFalse(any('cost' in key for key in info), 'Invented pricing metadata')

    def test_model_discovery_requires_authentication(self):
        status, _ = request('/model/catalog/discover', {'provider': 'nano-gpt'})
        self.assertIn(status, [401, 403])

    @unittest.skipUnless(os.environ.get("LITELLM_TEST_ADMIN_KEY"), "Set LITELLM_TEST_ADMIN_KEY for authenticated checks")
    def test_admin_can_read_public_provider_model_names(self):
        status, data = request('/model/catalog/discover', {'provider': 'nano-gpt'}, admin=True)
        self.assertEqual(status, 200)
        self.assertGreater(len(data.get('models', [])), 0)
        self.assertTrue(all(name.startswith('nano-gpt/') for name in data['models']))

    @unittest.skipUnless(os.environ.get("LITELLM_TEST_ADMIN_KEY"), "Set LITELLM_TEST_ADMIN_KEY for authenticated checks")
    def test_unknown_providers_are_rejected(self):
        status, _ = request('/model/catalog/discover', {'provider': 'unknown-provider'}, admin=True)
        self.assertIn(status, [400, 422])


if __name__ == '__main__':
    unittest.main(verbosity=2)
