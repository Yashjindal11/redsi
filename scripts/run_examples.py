"""Run every example in a temporary directory and fail if any errors (used by CI)."""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
failed = []
for script in sorted((ROOT / "examples").glob("*/run.py")):
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(  # noqa: S603 - fixed, repository-local scripts
            [sys.executable, str(script)], cwd=tmp, capture_output=True, text=True, timeout=120
        )
    status = "ok" if proc.returncode == 0 else "FAIL"
    print(f"[{status}] {script.parent.name}")
    if proc.returncode != 0:
        failed.append(script.parent.name)
        print(proc.stdout[-2000:], proc.stderr[-4000:], sep="\n")
sys.exit(1 if failed else 0)
