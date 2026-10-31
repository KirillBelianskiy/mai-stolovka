"""Export deterministic OpenAPI snapshots using each service's own environment."""

import json
import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
output = root / "packages/contracts/openapi"
output.mkdir(parents=True, exist_ok=True)
for name in ("user", "menu", "order"):
    service = root / "services" / f"{name}-service"
    binary = service / ".venv" / ("Scripts" if os.name == "nt" else "bin") / "python"
    code = (
        f"from {name}_service.main import create_app; "
        "import json; print(json.dumps(create_app().openapi()))"
    )
    result = subprocess.run(
        [str(binary), "-c", code],
        cwd=service,
        check=True,
        text=True,
        capture_output=True,
        timeout=30,
    )
    (output / f"{name}-service.v1.json").write_text(
        json.dumps(json.loads(result.stdout), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )
    print(f"Exported {name}-service OpenAPI contract")
