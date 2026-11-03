"""Prepare dashboard extensions before the gateway imports its routes."""

import ast
import importlib.util
from pathlib import Path

from sync_providers import main as sync_providers, write_atomic


sync_providers()
root = Path(importlib.util.find_spec("litellm").origin).parent
path = root / "proxy/public_endpoints/public_endpoints.py"
source = path.read_text()
if "# local-model-catalog-extension" not in source:
    tree = ast.parse(source)
    node = next(n for n in tree.body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_litellm_model_cost_map")
    original = ast.get_source_segment(source, node)
    replacement = original.replace(
        "return _model_cost_map",
        "return _ui_merge_model_catalog(_model_cost_map) if catalog_only else _model_cost_map",
    )
    if original == replacement:
        raise RuntimeError("The model catalog endpoint shape changed; no backend files were changed.")
    source = source.replace(original, replacement, 1)
    source += (
        "\n# local-model-catalog-extension\n"
        "from model_catalog_data import merge_ui_catalog as _ui_merge_model_catalog\n"
        "from model_catalog_routes import router as _ui_model_catalog_router\n"
        "router.include_router(_ui_model_catalog_router)\n"
    )
    ast.parse(source)
    write_atomic(path, source)
print("Prepared dashboard model catalog and authenticated discovery.")
