"""Retain the local Compose overlay when the official quickstart updates itself."""

from pathlib import Path
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def ensure_management_hooks():
    script = ROOT / "quickstart.sh"
    source = script.read_text()
    original = '"$ENGINE" compose -f docker-compose.quickstart.yml "$@"'
    overlay = ('"$ENGINE" compose -f docker-compose.quickstart.yml '
               '-f docker-compose.ui-overrides.yml "$@"')
    if original in source:
        script.write_text(source.replace(original, overlay, 1))
    elif overlay not in source:
        raise RuntimeError("The official quickstart Compose helper changed; local overlay was not applied.")
    launcher = ROOT / "litellm-gateway"
    launcher.write_text(
        '#!/bin/sh\n'
        'export LITELLM_DIR=' + shlex.quote(str(ROOT)) + '\n'
        'exec python3 "$LITELLM_DIR/ui-overrides/manage_gateway.py" "$@"\n'
    )
    launcher.chmod(0o755)


if __name__ == "__main__":
    ensure_management_hooks()
    result = subprocess.run(["sh", str(ROOT / "quickstart.sh"), *sys.argv[1:]], cwd=ROOT)
    if (ROOT / ".env").exists() and (ROOT / "quickstart.sh").exists() and (ROOT / "ui-overrides").exists():
        ensure_management_hooks()
    raise SystemExit(result.returncode)
