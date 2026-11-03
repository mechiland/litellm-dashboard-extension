"""Authenticated model discovery with no credential or private-model persistence."""

import importlib.util
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
import httpx
from pydantic import BaseModel, SecretStr

from litellm.litellm_core_utils.credential_accessor import CredentialAccessor
from litellm.proxy._types import UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from model_catalog_data import PUBLIC_MODEL_URLS, fetch_model_names
from sync_providers import NATIVE_URLS, backend_provider_slugs


router = APIRouter()


class DiscoverModelsRequest(BaseModel):
    provider: str
    api_base: str | None = None
    api_key: SecretStr | None = None
    credential_name: str | None = None


@router.post("/model/catalog/discover", tags=["model management"])
async def discover_models(body: DiscoverModelsRequest,
                          user: UserAPIKeyAuth = Depends(user_api_key_auth)):
    if user.user_role != "proxy_admin":
        raise HTTPException(403, "Proxy admin access is required.")
    root = Path(importlib.util.find_spec("litellm").origin).parent
    provider = body.provider
    if provider not in backend_provider_slugs(root):
        raise HTTPException(400, "Unknown LiteLLM provider.")
    if provider in {
        "azure", "azure_ai", "azure_speech", "bedrock", "bedrock_mantle",
        "gdc", "vertex_ai", "vertex_ai_beta", "sagemaker", "sagemaker_chat",
        "sagemaker_nova", "aws_polly", "aws_textract", "transcribe", "s3_vectors",
        "valkey", "milvus", "pg_vector", "mongodb",
    }:
        raise HTTPException(400, "This connector uses cloud deployments or resources rather than an OpenAI-compatible model list. Its built-in catalog remains available.")
    credential = {}
    if body.credential_name:
        credential = CredentialAccessor.get_credential_values(body.credential_name)
    registry = json.loads((root / "llms/openai_like/providers.json").read_text())
    connection = registry.get(provider, {})
    key = body.api_key.get_secret_value() if body.api_key else credential.get("api_key")
    if not key and connection.get("api_key_env"):
        key = os.environ.get(connection["api_key_env"])
    if isinstance(key, str) and key.startswith("os.environ/"):
        key = os.environ.get(key.split("/", 1)[1])
    if key is not None and (not isinstance(key, str) or key.lstrip().startswith("{")):
        raise HTTPException(400, "Model discovery requires an API token, not a service-account JSON document.")
    defaults = {**NATIVE_URLS, "openai": "https://api.openai.com/v1",
                "anthropic": "https://api.anthropic.com/v1",
                "gemini": "https://generativelanguage.googleapis.com/v1beta",
                "deepseek": "https://api.deepseek.com/v1",
                "ollama": "http://host.docker.internal:11434",
                "ollama_chat": "http://host.docker.internal:11434"}
    base = body.api_base or credential.get("api_base") or connection.get("base_url") or defaults.get(provider)
    headers = {"Authorization": "Bearer " + key} if key else {}
    if provider in PUBLIC_MODEL_URLS and not body.api_base and not credential.get("api_base"):
        url = PUBLIC_MODEL_URLS[provider]
    else:
        if not base:
            raise HTTPException(400, "Enter this provider's API Base URL before refreshing models.")
        parsed = urlsplit(base)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query:
            raise HTTPException(400, "API Base must be an HTTP(S) base URL without credentials or query parameters.")
        base = base.rstrip("/")
        if provider in {"ollama", "ollama_chat"}:
            url = base.removesuffix("/v1") + "/api/tags"
        else:
            url = base if base.endswith("/models") else base + "/models"
        if provider == "gemini" and key:
            headers = {"x-goog-api-key": key}
        elif provider == "anthropic":
            headers = {"anthropic-version": "2023-06-01"}
            if key:
                headers["x-api-key"] = key
        elif provider in {"azure", "azure_ai"} and key:
            headers = {"api-key": key}
    try:
        models = await fetch_model_names(provider, url, headers)
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        message = ("Enter a valid provider API key, then refresh again." if status in {401, 403}
                   else "This API Base did not return a model list.")
        raise HTTPException(400, f"{message} Provider HTTP {status}.") from None
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "The provider model-list request failed. Check its API Base and credentials.") from None
    # Account-specific IDs stay in this admin's browser, outside the public cache.
    return {"provider": provider, "models": models, "count": len(models)}
