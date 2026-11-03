"""Expose the installed LiteLLM backend provider registry in its dashboard.

Uses packaged metadata only. No credentials are read and no provider is called.
Run at container startup so a recreated container uses its own backend catalog.
"""

import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re


FIELD_KEYS = {
    "key", "label", "placeholder", "tooltip", "required", "field_type",
    "options", "default_value",
}
DISPLAY_NAMES = {
    "a2a_agent": "A2A Agent",
    "gdc": "Google Distributed Cloud (GDC)",
    "litellm_agent": "LiteLLM Agent",
    "mongodb": "MongoDB",
    "nano-gpt": "NanoGPT",
    "neosantara": "Neosantara",
    "sagemaker_nova": "AWS SageMaker Nova",
    "transcribe": "AWS Transcribe",
    "valkey": "Valkey",
}
NATIVE_URLS = {
    "amazon_nova": "https://api.nova.amazon.com/v1",
    "black_forest_labs": "https://api.bfl.ai",
    "inception": "https://api.inceptionlabs.ai/v1",
    "text-completion-inception": "https://api.inceptionlabs.ai/v1",
    "manus": "https://api.manus.im",
    "modelscope": "https://api-inference.modelscope.cn/v1",
    "stability": "https://api.stability.ai",
    "zai": "https://api.z.ai/api/paas/v4",
}
PATCH_START = "/* litellm-provider-sync:start */"
PATCH_END = "/* litellm-provider-sync:end */"


def field(key, label, *, required=False, secret=False, default=None,
          placeholder=None, tooltip=None, options=None):
    return {
        "key": key, "label": label, "required": required,
        "field_type": "select" if options else "password" if secret else "text",
        "placeholder": placeholder or default, "tooltip": tooltip,
        "options": options, "default_value": default,
    }


def backend_provider_slugs(root):
    tree = ast.parse((root / "types/utils.py").read_text())
    enum = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LlmProviders")
    slugs = {
        n.value.value for n in enum.body
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
        and isinstance(n.value.value, str)
    }
    if not slugs:
        raise RuntimeError("The installed backend provider registry could not be read.")
    return slugs


def credential_fields(slug, entries, registry, agents):
    if slug in {"aws_polly", "transcribe", "s3_vectors", "sagemaker_nova"}:
        return deepcopy([
            f for f in entries["bedrock"]["credential_fields"]
            if f["key"] not in {"api_key", "aws_bedrock_runtime_endpoint"}
        ])
    if slug in agents:
        return [
            {k: v for k, v in f.items() if k in FIELD_KEYS}
            for f in agents[slug]["credential_fields"]
            if f.get("include_in_litellm_params", True)
        ]
    if slug == "gdc":
        return [
            field("api_base", "GDC API Base", required=True),
            field("api_key", "Service Account JSON or Access Token", required=True, secret=True),
            field("vertex_project", "GDC Project", tooltip="Required unless included in the API Base URL."),
            field("vertex_location", "GDC Location", tooltip="Required unless included in the API Base URL."),
        ]
    if slug == "valkey":
        return [
            field("valkey_host", "Valkey Host", required=True),
            field("valkey_port", "Valkey Port", default="6379"),
            field("valkey_password", "Valkey Password", secret=True),
            field("valkey_ssl", "Use TLS", default="false", options=["true", "false"]),
            field("litellm_embedding_model", "Embedding Model", required=True,
                  placeholder="openai/text-embedding-3-small"),
        ]
    endpoint_required = slug in {"a2a", "a2a_agent", "ragflow", "mongodb"}
    key_required = slug in registry or slug in NATIVE_URLS or slug in {"mongodb", "reducto"}
    connection = registry.get(slug, {})
    default_url = connection.get("base_url") or NATIVE_URLS.get(slug)
    env_name = connection.get("api_key_env")
    return [
        field("api_key", "API Key", required=key_required, secret=True,
              tooltip=f"API key, or os.environ/{env_name}." if env_name else None),
        field("api_base", "API Base URL", required=endpoint_required, default=default_url),
    ]


def complete_metadata(root):
    path = root / "proxy/public_endpoints/provider_create_fields.json"
    providers = json.loads(path.read_text())
    slugs = backend_provider_slugs(root)
    # Retain pre-existing local option IDs, including the earlier MiMo fix,
    # when the upstream image has not registered those options yet.
    baseline = Path(__file__).with_name("provider-fields.before-sync.json")
    option_ids = {p["provider"] for p in providers}
    if baseline.exists():
        for local in json.loads(baseline.read_text()):
            if local["litellm_provider"] in slugs and local["provider"] not in option_ids:
                providers.append(deepcopy(local))
                option_ids.add(local["provider"])
    existing = {p["litellm_provider"]: p for p in providers}
    registry = json.loads((root / "llms/openai_like/providers.json").read_text())
    endpoints = json.loads((root / "provider_endpoints_support_backup.json").read_text())["providers"]
    agent_path = root / "proxy/public_endpoints/agent_create_fields.json"
    agents = {a["agent_type"]: a for a in json.loads(agent_path.read_text())} if agent_path.exists() else {}
    # A2A's agent registration has no connection fields; its model adapter needs api_base.
    agents.pop("a2a", None)
    catalog = json.loads((root / "model_prices_and_context_window_backup.json").read_text())
    models = {}
    for name, info in catalog.items():
        if isinstance(info, dict) and info.get("litellm_provider") in slugs:
            models.setdefault(info["litellm_provider"], []).append(name)

    missing = sorted(slugs - existing.keys())
    for slug in missing:
        display = endpoints.get(slug, {}).get("display_name", slug.replace("_", " ").title())
        display = re.sub(r"\s*\(`[^`]+`\)\s*$", "", display)
        display = DISPLAY_NAMES.get(slug, display)
        available = models.get(slug, [])
        placeholder = available[0] if available else agents.get(slug, {}).get("model_template")
        providers.append({
            "provider": slug,
            "provider_display_name": display,
            "litellm_provider": slug,
            "credential_fields": credential_fields(slug, existing, registry, agents),
            "default_model_placeholder": placeholder or f"{slug}/<model-name>",
        })
    return path, providers, missing


def dashboard_updates(root, providers):
    names = {p["provider"]: p["provider_display_name"] for p in providers}
    slugs = {p["provider"]: p["litellm_provider"] for p in providers}
    placeholders = {
        p["provider_display_name"]: p["default_model_placeholder"]
        for p in providers if p.get("default_model_placeholder")
    }
    export_pattern = re.compile(
        r'(?P<module>[A-Za-z_$][\w$]*)\.s\(\["g",\(\)=>(?P<names>[A-Za-z_$][\w$]*),'
        r'"J",0,e=>(?P<placeholders>[A-Za-z_$][\w$]*)\['
    )
    map_pattern = re.compile(r'"D",0,\(e,t\)=>\{let [A-Za-z_$][\w$]*=(?P<map>[A-Za-z_$][\w$]*)\[e\]')
    option_pattern = re.compile(
        r'label:([A-Za-z_$][\w$]*)\.provider_display_name,value:\1\.provider,icon:'
    )
    old_patch = re.compile(re.escape(PATCH_START) + ".*?" + re.escape(PATCH_END), re.S)
    updates = []
    found = 0
    refresh_anchor = (
        '(0,t.jsx)(aX,{selectedProvider:d,providerModels:m,getPlaceholder:h}),'
        '(0,t.jsx)(a5,'
    )
    refresh_button = r'''(0,t.jsx)("button",{id:"refresh-provider-models",type:"button",disabled:!ei||modelCatalogBusy,className:"mt-2 mb-3 inline-flex h-8 items-center rounded-md border px-3 text-sm disabled:opacity-50",onClick:async()=>{setModelCatalogBusy(!0);try{let values=e.getValues(),response=await fetch("/model/catalog/discover",{method:"POST",headers:{"Authorization":"Bearer "+T,"Content-Type":"application/json"},body:JSON.stringify({provider:ei,api_base:values.api_base,api_key:values.api_key,credential_name:values.litellm_credential_name})}),result=await response.json();if(!response.ok)throw Error(typeof result.detail==="string"?result.detail:"Failed to fetch model names");$.setQueriesData({queryKey:["modelCostMap"],predicate:q=>JSON.stringify(q.queryKey).includes("catalog_only")},old=>{let next={...old},known=new Map;for(let[name,info]of Object.entries(next))if(info&&info.litellm_provider===ei){known.set(name.startsWith(ei+"/")?name:ei+"/"+name,info);delete next[name]}for(let name of result.models)next[name]=known.get(name)||{litellm_provider:ei};return next});eW.f.success("Loaded "+result.models.length+" models")}catch(error){eW.f.error(error.message||"Failed to fetch model names")}finally{setModelCatalogBusy(!1)}},children:modelCatalogBusy?"Refreshing models…":"Refresh Model List"}),'''
    for path in (root / "proxy/_experimental/out/_next/static/chunks").glob("*.js"):
        if "-litellm-ui-" in path.name:
            continue
        original = path.read_text()
        source = old_patch.sub("", original)
        # The existing combobox searches labels and sublabels. Including the
        # native slug makes IDs such as xiaomi_mimo and nano-gpt searchable.
        source = option_pattern.sub(
            lambda m: (
                f'label:{m[1]}.provider_display_name,value:{m[1]}.provider,'
                f'sublabel:{m[1]}.litellm_provider,icon:'
            ), source,
        )
        if refresh_anchor in source and 'id:"refresh-provider-models"' not in source:
            state_anchor = 'decisionCatalog:g})=>{var j;let v,'
            if state_anchor not in source:
                raise RuntimeError("The model form changed; refresh button was not installed.")
            source = source.replace(
                state_anchor,
                'decisionCatalog:g})=>{let[modelCatalogBusy,setModelCatalogBusy]=(0,s.useState)(!1);var j;let v,',
                1,
            )
            source = source.replace(
                refresh_anchor,
                '(0,t.jsx)(aX,{selectedProvider:d,providerModels:m,getPlaceholder:h}),'
                + refresh_button + '(0,t.jsx)(a5,', 1,
            )
        export = export_pattern.search(source)
        mapping = map_pattern.search(source)
        if export and mapping:
            found += 1
            patch = PATCH_START + "".join(
                f"Object.assign({variable},{json.dumps(value, separators=(',', ':'))});"
                for variable, value in [
                    (export["names"], names), (mapping["map"], slugs),
                    (export["placeholders"], placeholders),
                ]
            ) + PATCH_END
            source = source[:export.start()] + patch + source[export.start():]
        if source != original:
            updates.append((path, source))
    if not found:
        raise RuntimeError("Dashboard provider definitions were not found; no files were changed.")
    return updates, found


def write_atomic(path, text):
    temporary = path.with_suffix(path.suffix + ".provider-sync.tmp")
    temporary.write_text(text)
    temporary.replace(path)


def main():
    root = Path(importlib.util.find_spec("litellm").origin).parent
    path, providers, missing = complete_metadata(root)
    bundles, found = dashboard_updates(root, providers)
    for bundle, source in bundles:
        write_atomic(bundle, source)
    if json.loads(path.read_text()) != providers:
        write_atomic(path, json.dumps(providers, indent=2) + "\n")
    covered = len({p["litellm_provider"] for p in providers})
    print(f"Dashboard: {covered} backend providers, {len(providers)} options, "
          f"{len(missing)} added; {found} provider bundles synchronized.")
    from version_dashboard_assets import version_dashboard_assets
    count, revision = version_dashboard_assets(root)
    print(f"Dashboard assets: {count} versioned scripts, revision {revision}.")


if __name__ == "__main__":
    main()
