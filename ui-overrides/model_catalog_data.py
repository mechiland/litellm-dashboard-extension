"""Dashboard model names, kept separate from billing metadata and credentials."""

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import httpx


PUBLIC_MODEL_URLS = {
    "openrouter": "https://openrouter.ai/api/v1/models",
    "nano-gpt": "https://nano-gpt.com/api/v1/models",
    "poe": "https://api.poe.com/v1/models",
    "synthetic": "https://api.synthetic.new/openai/v1/models",
}


def catalog_path():
    return Path(os.environ.get("LITELLM_UI_MODEL_CATALOG_PATH",
                               "/opt/litellm-model-catalog/catalog.json"))


def read_catalog():
    path = catalog_path()
    return json.loads(path.read_text()) if path.exists() else {"providers": {}}


def prefixed_name(provider, name):
    name = name.strip()
    if not name or len(name) > 512 or any(c.isspace() for c in name):
        return None
    if provider == "gemini":
        name = name.removeprefix("models/")
    return name if name.startswith(provider + "/") else provider + "/" + name


def model_names(provider, response):
    rows = response.get("data", response.get("models", [])) if isinstance(response, dict) else response
    if not isinstance(rows, list):
        raise ValueError("The endpoint did not return a model list.")
    names = set()
    for row in rows:
        name = (row.get("id") or row.get("name") or row.get("model")) if isinstance(row, dict) else row
        if isinstance(name, str):
            normalized = prefixed_name(provider, name)
            if normalized:
                names.add(normalized)
    if not names:
        raise ValueError("The endpoint returned no model names.")
    return sorted(names)


async def fetch_model_names(provider, url, headers=None):
    names = set()
    params = {}
    async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
        for _ in range(20):
            response = await client.get(url, headers=headers or {}, params=params)
            response.raise_for_status()
            data = response.json()
            names.update(model_names(provider, data))
            if not isinstance(data, dict):
                break
            if data.get("nextPageToken"):
                params = {"pageToken": data["nextPageToken"]}
            elif data.get("has_more") and data.get("last_id"):
                params = {"after_id": data["last_id"], "limit": 1000}
            else:
                break
    return sorted(names)


async def refresh_public_catalog():
    snapshot = read_catalog()
    providers = snapshot.setdefault("providers", {})

    async def fetch(provider, url):
        try:
            names = await fetch_model_names(provider, url)
            providers[provider] = {"models": names, "source": url,
                                   "updated_at": datetime.now(timezone.utc).isoformat()}
            return provider, len(names), "updated"
        except (httpx.HTTPError, ValueError) as error:
            return provider, len(providers.get(provider, {}).get("models", [])), type(error).__name__

    results = await asyncio.gather(*(fetch(p, url) for p, url in PUBLIC_MODEL_URLS.items()))
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, indent=2) + "\n")
    temporary.replace(path)
    return results


def merge_ui_catalog(base):
    """Add public model names to Add Model without changing billing prices."""
    combined = dict(base)
    known = {
        prefixed_name(info["litellm_provider"], name)
        for name, info in base.items()
        if isinstance(info, dict) and isinstance(info.get("litellm_provider"), str)
    }
    for provider, entry in read_catalog().get("providers", {}).items():
        for name in entry.get("models", []):
            if name not in known:
                combined[name] = {"litellm_provider": provider,
                                  "model_catalog_source": entry.get("source", "provider")}
                known.add(name)
    return combined


if __name__ == "__main__":
    for provider, count, status in asyncio.run(refresh_public_catalog()):
        print(f"Model catalog: {provider}: {count} models ({status}).")
