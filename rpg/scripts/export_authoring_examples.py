"""Regenerate the public original packages and their executable model schemas."""
import json
from pathlib import Path

from platform_app.authoring.contract import get_contract, inspect_package
from platform_app.authoring.examples import example_files, package_bytes


def main():
    target = Path(__file__).resolve().parents[2] / "docs/examples/creator-mcp"
    target.mkdir(parents=True, exist_ok=True)
    for name, alternate in (("ferry-lamp", False), ("unnumbered-station", True)):
        files = example_files(alternate)
        raw = package_bytes(files)
        assert inspect_package(raw)[0]["valid"]
        (target / (name+".pack.zip")).write_bytes(raw)
        (target / (name+".json")).write_text(json.dumps(files, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (target / "schemas.json").write_text(json.dumps(get_contract("schemas"), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
