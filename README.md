# LiteLLM dashboard provider and model catalog extension

A community-maintained Docker Compose extension for LiteLLM Proxy. It fills gaps between the installed backend's provider registry and the dashboard, and adds a **Refresh Model List** button to **Models + Endpoints → Add Model**. It is independent of and not endorsed by LiteLLM.

## What it does

- Adds backend provider IDs missing from the Add Model selector, retaining existing options and credential fields. Both provider names and IDs are searchable.
- Combines LiteLLM's catalog with public model lists from OpenRouter, NanoGPT, Poe, and Synthetic. The last successful public snapshot survives container recreation.
- Fetches a selected provider's model list using the form's API base, API key, or saved credential. Results are held in the current browser's catalog. It does not deploy models or issue inference calls.
- Keeps supplemental names out of LiteLLM's billing/pricing metadata. Patched scripts get versioned URLs to avoid stale browser caches.

Model discovery requires proxy-admin access. The provider endpoint receives the supplied or stored API key. Custom API base URLs can direct requests to network locations reachable by the proxy; restrict admin access and use trusted endpoints. Account-specific results are not written to the shared public catalog. Cloud connectors that use deployments or resources rather than a generic model-list API retain their native workflow.

## Compatibility

Tested against the LiteLLM Docker image reporting **1.106.6**, image digest `sha256:37e2dafb088a7723beb998590682957386dfc83ffea1848486f8e0e5cfac0b06`, with the Docker Compose quickstart. Other versions may work but are not guaranteed: this extension patches compiled dashboard assets and internal Python endpoints at container startup. A LiteLLM upgrade may change those internals, make the button unavailable, or stop the service from starting. Pin and test upgrades before using them in production. This project does not modify LiteLLM upstream.

Requires Docker Compose with `post_start` support, an existing LiteLLM Compose installation, and outbound access to the public catalog endpoints if their extra model names are wanted. The overlay assumes the Compose service is named `litellm`, the image has `/app/docker/prod_entrypoint.sh`, and the dashboard is served under `/ui/`.

## Install on an existing quickstart

Run these commands on the Docker host. Replace the path in the first command with your existing gateway directory. Review the overlay first if you have customized the service: it replaces the image entrypoint and command with `--port 4000`; merge any custom command arguments or entrypoint behavior into the overlay before starting. Check that `ui-overrides` and `docker-compose.ui-overrides.yml` do not already contain files you need before copying.

```sh
cd /path/to/your/litellm-gateway
git clone https://github.com/mechiland/litellm-dashboard-extension.git /tmp/litellm-dashboard-extension
cp -R /tmp/litellm-dashboard-extension/ui-overrides ./ui-overrides
cp /tmp/litellm-dashboard-extension/docker-compose.ui-overrides.yml .
mkdir -p model-catalog
docker compose -f docker-compose.quickstart.yml -f docker-compose.ui-overrides.yml up -d
```

The Compose project directory (where your `.env` and base Compose file live) is the first file's directory. The overlay mounts the extension read-only and stores the public model catalog in `model-catalog/`; it does not need your `.env` copied into this repository. If your base Compose file has another name, substitute it in every Compose command.

Open your dashboard, sign in as a proxy admin, and select **Models + Endpoints → Add Model**. Select a provider, then use **Refresh Model List** below the model-name field. Supply the provider's credentials and API base when required. Some providers do not expose a compatible model-list API; their error message or existing deployment workflow applies. The public startup refresh runs in a Compose post-start hook, so extra public choices may take a short time to appear. Reload the dashboard after installing or upgrading.

## Restart, upgrade, and uninstall

Always include both Compose files so the overlay is applied:

```sh
docker compose -f docker-compose.quickstart.yml -f docker-compose.ui-overrides.yml restart litellm
# After reviewing and selecting a compatible image version:
docker compose -f docker-compose.quickstart.yml -f docker-compose.ui-overrides.yml pull litellm
docker compose -f docker-compose.quickstart.yml -f docker-compose.ui-overrides.yml up -d
```

Record the image digest and back up your configuration and database before upgrading. Afterward, verify the Add Model button and a model refresh. To remove the extension, recreate the service with your original Compose file alone (`docker compose -f docker-compose.quickstart.yml up -d --force-recreate litellm`). This removes the mounted extension from the running service; the copied files and public catalog remain on disk until you remove them.

`ui-overrides/manage_gateway.py` is an optional helper for the LiteLLM quickstart's `litellm-gateway` wrapper. It edits the quickstart's Compose helper and rewrites its launcher to include the overlay. Its matching depends on the quickstart script's exact contents. The direct Compose commands above do not require it.

## Verify

From the gateway directory, with the proxy running on `127.0.0.1:4000`:

```sh
python3 ui-overrides/test_provider_coverage.py
python3 ui-overrides/test_model_catalog.py
python3 ui-overrides/test_ui_asset_versioning.py
```

Set `LITELLM_TEST_BASE_URL` to test another base URL. Set `LITELLM_TEST_CONTAINER` to the actual LiteLLM container name to run the registry comparison. Two additional catalog checks run when `LITELLM_TEST_ADMIN_KEY` is set in the environment; use a proxy-admin key and avoid putting secrets in shell history. Public catalog checks depend on those external endpoints and a successfully populated snapshot. These checks do not send inference requests.

## Design and source notices

At startup, `prepare_gateway.py` patches the installed image's files inside its writable container layer. Compose recreation repeats that preparation. `model_catalog_data.py` caches only public provider model names; `model_catalog_routes.py` serves authenticated discovery. Provider metadata in `provider-fields.before-sync.json` and small references to compiled dashboard code derive from LiteLLM; its applicable MIT notice is in [LICENSE](LICENSE). LiteLLM and provider names are trademarks of their respective owners.
