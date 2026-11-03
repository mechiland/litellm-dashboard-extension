"""Give locally changed dashboard scripts URLs that reflect their contents."""

import hashlib
import importlib.util
import json
from pathlib import Path
import re


STAMP = re.compile(r"-litellm-ui-[0-9a-f]{12}(?=\.js)")


def write_changed(path, content):
    if path.exists() and path.read_text() == content:
        return
    temporary = path.with_suffix(path.suffix + ".ui-version.tmp")
    temporary.write_text(content)
    temporary.replace(path)


def version_dashboard_assets(package_root):
    root = package_root / "proxy/_experimental/out"
    chunks = root / "_next/static/chunks"
    originals = {
        path.name: path.read_text() for path in chunks.glob("*.js")
        if not STAMP.search(path.name)
    }
    changed = {
        name for name, source in originals.items()
        if "/* litellm-provider-sync:start */" in source
        or "refresh-provider-models" in source
    }
    if not changed:
        raise RuntimeError("No patched dashboard scripts were found to version.")

    # If a future export imports a patched script from another script, its URL
    # must also change. Current exports reference these chunks from HTML/RSC.
    while True:
        parents = {
            name for name, source in originals.items()
            if name not in changed and any(target in source for target in changed)
        }
        if not parents:
            break
        changed.update(parents)

    digest = hashlib.sha256()
    for name in sorted(changed):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(originals[name].encode())
    revision = digest.hexdigest()[:12]
    assets = {
        name: name[:-3] + "-litellm-ui-" + revision + ".js"
        for name in sorted(changed)
    }

    def rewrite(source):
        result = STAMP.sub("", source)
        for old, new in assets.items():
            result = result.replace(old, new)
        return result

    # Retain original and older URLs for tabs that were opened before this run.
    for old, new in assets.items():
        write_changed(chunks / new, rewrite(originals[old]))
    for path in root.rglob("*"):
        if (path.is_file() and path.suffix in {".html", ".txt", ".json"}
                and path.name != "ui-extension-manifest.json"):
            source = path.read_text()
            updated = rewrite(source)
            if source != updated:
                write_changed(path, updated)
    write_changed(
        root / "ui-extension-manifest.json",
        json.dumps({"revision": revision, "assets": assets}, indent=2) + "\n",
    )
    return len(assets), revision


if __name__ == "__main__":
    package_root = Path(importlib.util.find_spec("litellm").origin).parent
    count, revision = version_dashboard_assets(package_root)
    print(f"Dashboard assets: {count} versioned scripts, revision {revision}.")
