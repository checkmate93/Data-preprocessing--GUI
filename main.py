"""Command-line demo of the flows, without the web server.

    python main.py                      # uses sample_data/pelates_demo.csv
    python main.py path/to/file.xlsx
"""

import logging
import shutil
import sys
import tempfile
from pathlib import Path

from flow import create_operation_flow, create_script_flow, create_shared, create_upload_flow


def run(shared, op, params=None):
    shared["request"] = {"op": op, "params": params or {}, "preview": False}
    shared["result"] = None
    create_operation_flow().run(shared)
    result = shared["result"]
    print(f"  {op:<24} {result['status']:<5} {result.get('message', '')}")
    for warning in result.get("warnings", []):
        print(f"  {'':<24} ! {warning}")
    return result


def main():
    logging.basicConfig(level=logging.WARNING)
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_data/pelates_demo.csv")
    workdir = Path(tempfile.mkdtemp(prefix="dataprep_cli_"))
    copy = workdir / f"source{source.suffix}"
    shutil.copy(source, copy)

    shared = create_shared("cli", str(workdir), str(copy), source.name, source.stat().st_size)
    create_upload_flow().run(shared)
    if shared["result"] and shared["result"]["status"] == "error":
        sys.exit(shared["result"]["message"])

    src, profile = shared["source"], shared["profile"]
    print(f"{source.name}: {src['format']} encoding={src.get('encoding')} delimiter={src.get('delimiter')!r}")
    print(f"shape={profile['shape']} missing={profile['total_missing']} quality={profile['quality']['total']}/100")
    print("Suggestions:", ", ".join(s["op"] for s in shared["suggestions"]) or "-")

    print("Applying suggestions:")
    applied = set()
    while True:
        # Suggestions are rebuilt after every step (column names change after snake_case).
        pending = [s for s in shared["suggestions"] if s["op"] not in applied]
        if not pending:
            break
        applied.add(pending[0]["op"])
        run(shared, pending[0]["op"], pending[0]["params"])

    profile = shared["profile"]
    print(f"After: shape={profile['shape']} missing={profile['total_missing']} quality={profile['quality']['total']}/100")
    create_script_flow().run(shared)
    script_path = workdir / "pipeline.py"
    script_path.write_text(shared["result"]["payload"]["script"], encoding="utf-8")
    print("pipeline.py:", script_path)


if __name__ == "__main__":
    main()
