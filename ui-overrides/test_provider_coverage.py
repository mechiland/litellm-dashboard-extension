"""Read-only integration checks for the running local LiteLLM dashboard."""

import json
import os
from pathlib import Path
import subprocess
import unittest
from urllib.request import urlopen


def get_json(path):
    with urlopen(os.environ.get("LITELLM_TEST_BASE_URL", "http://127.0.0.1:4000").rstrip("/") + path, timeout=10) as response:
        return json.load(response)


class ProviderCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = set(get_json("/public/providers"))
        cls.entries = get_json("/public/providers/fields")
        cls.by_slug = {p["litellm_provider"]: p for p in cls.entries}
        cls.baseline = json.loads(
            Path(__file__).with_name("provider-fields.before-sync.json").read_text()
        )

    def test_every_backend_provider_is_available_in_add_model(self):
        missing = sorted(self.backend - self.by_slug.keys())
        self.assertEqual(missing, [], f"Providers missing from Add Model: {missing}")

    def test_existing_credential_fields_and_aliases_are_preserved(self):
        by_id = {p["provider"]: p for p in self.entries}
        self.assertEqual(len(by_id), len(self.entries), "Duplicate provider option IDs")
        for old in self.baseline:
            with self.subTest(provider=old["provider"]):
                self.assertTrue(old["provider"] in by_id, f"Missing option: {old['provider']}")
                new = by_id[old["provider"]]
                self.assertEqual(new["litellm_provider"], old["litellm_provider"])
                self.assertEqual(new["credential_fields"], old["credential_fields"])

    def test_special_authentication_fields_are_available(self):
        expected = {
            "aws_polly": {"aws_access_key_id", "aws_secret_access_key", "aws_region_name"},
            "transcribe": {"aws_access_key_id", "aws_secret_access_key", "aws_region_name"},
            "s3_vectors": {"aws_access_key_id", "aws_secret_access_key", "aws_region_name"},
            "gdc": {"api_base", "api_key", "vertex_project", "vertex_location"},
            "valkey": {"valkey_host", "valkey_password", "litellm_embedding_model"},
            "langgraph": {"api_base", "api_key"},
        }
        for slug, keys in expected.items():
            with self.subTest(provider=slug):
                self.assertTrue(slug in self.by_slug, f"Missing provider: {slug}")
                actual = {f["key"] for f in self.by_slug[slug]["credential_fields"]}
                self.assertTrue(keys <= actual, f"Missing fields for {slug}: {keys - actual}")

    @unittest.skipUnless(os.environ.get("LITELLM_TEST_CONTAINER"), "Set LITELLM_TEST_CONTAINER to inspect registry")
    def test_new_openai_compatible_providers_have_their_native_default_urls(self):
        command = (
            "import importlib.util,json; from pathlib import Path; "
            "root=Path(importlib.util.find_spec('litellm').origin).parent; "
            "print((root/'llms/openai_like/providers.json').read_text())"
        )
        registry = json.loads(subprocess.check_output(
            ["docker", "exec", os.environ.get("LITELLM_TEST_CONTAINER", "litellm-gateway-litellm-1"), "python", "-c", command],
            text=True,
        ))
        baseline_slugs = {p["litellm_provider"] for p in self.baseline}
        for slug in sorted((self.backend & registry.keys()) - baseline_slugs):
            with self.subTest(provider=slug):
                self.assertTrue(slug in self.by_slug, f"Missing provider: {slug}")
                fields = {f["key"]: f for f in self.by_slug[slug]["credential_fields"]}
                self.assertEqual(fields["api_base"]["default_value"], registry[slug]["base_url"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
