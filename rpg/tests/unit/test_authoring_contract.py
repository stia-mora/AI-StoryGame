import copy
import hashlib
import io
import json
import zipfile

import pytest

from platform_app.authoring.contract import inspect_package
from platform_app.authoring.examples import example_files, package_bytes


@pytest.mark.parametrize("alternate", [False, True])
def test_original_samples_validate(alternate):
    report, *_ = inspect_package(package_bytes(example_files(alternate)))
    assert report["valid"], report
    assert report["checks"]["semantics"] == "not_verified"


@pytest.mark.parametrize("change,code", [
    (lambda f: f["authoring.json"].update(scope=["missing"]), "reference"),
    (lambda f: f["chapters.jsonl"][0].update(content="changed"), "fingerprint"),
    (lambda f: f["overrides.json"]["guide_world"]["facts"][0]["evidence"][0].update(locator="missing"), "reference"),
    (lambda f: f["overrides.json"].update(api_key="must-not-be-imported"), "platform_field"),
    (lambda f: f["authoring.json"]["play"]["identities"][0].update(opening="missing"), "reference"),
    (lambda f: f["authoring.json"]["completeness"].update(chapter_notes=[]), "coverage"),
    (lambda f: f["character_cards.jsonl"][0].update(metadata={}), "coverage"),
    (lambda f: f["character_cards.jsonl"].append({**f["character_cards.jsonl"][0], "name": "另一个人"}), "duplicate"),
])
def test_bad_packages_report_repairable_errors(change, code):
    files = copy.deepcopy(example_files())
    change(files)
    report, *_ = inspect_package(package_bytes(files))
    assert not report["valid"]
    assert any(e["code"] == code for e in report["errors"]), report


def test_zip_traversal_and_duplicate_rejected():
    for path in ("../secret", "C:/secret", "/absolute", "dir\\file"):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr(path, "bad")
        assert not inspect_package(data.getvalue())[0]["valid"]


def test_export_timestamp_does_not_change_content_fingerprint():
    files = example_files()
    original = inspect_package(package_bytes(files))[0]["fingerprint"]
    files["manifest.json"]["exported_at"] = "tomorrow"
    assert inspect_package(package_bytes(files))[0]["fingerprint"] == original


def test_future_canonical_name_cannot_bypass_identity_period():
    files = example_files()
    world = files["overrides.json"]["guide_world"]
    world["moments"].append(dict(key="later", order=1, label="稍后", chapter_min=1, chapter_max=1))
    world["facts"].append({**world["facts"][0], "id": "later-name", "field": "name", "value": "林舟", "starts_at": "later"})
    report, *_ = inspect_package(package_bytes(files))
    assert not report["valid"]
    assert any(e["code"] == "period" for e in report["errors"])


def test_streaming_fingerprint_preserves_existing_canonical_digest():
    files = example_files()
    files["unused.bin"] = b"original-test-data"
    raw = package_bytes(files)
    normalized = {k: v for k, v in files.items() if k not in ("manifest.json", "unused.bin")}
    normalized["manifest.json"] = {"format_version": 2}
    expected = hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                              + files["unused.bin"]).hexdigest()
    report, _, _, retained = inspect_package(raw)
    assert report["valid"] and report["fingerprint"] == expected
    assert "chapters.jsonl" not in retained


def test_jsonl_row_budget_is_global_and_expansion_is_configurable(monkeypatch):
    from platform_app.knowledge import script_pack
    monkeypatch.setattr(script_pack, "MAX_JSONL_ROWS", 2)
    assert not inspect_package(package_bytes())[0]["valid"]
    monkeypatch.setenv("RPG_AUTHORING_MAX_EXPANDED_BYTES", "16")
    report, *_ = inspect_package(package_bytes())
    assert not report["valid"] and "解压总量" in report["errors"][0]["message"]


@pytest.mark.parametrize("variable,limit,message", [
    ("RPG_AUTHORING_MAX_JSON_MEMBER_BYTES", "16", "JSON 成员"),
    ("RPG_AUTHORING_MAX_JSONL_LINE_BYTES", "16", "JSONL 单行"),
    ("RPG_AUTHORING_MAX_JSON_NODES", "20", "JSON 结构复杂度"),
])
def test_configured_json_structure_budgets_reject_oversized_content(monkeypatch, variable, limit, message):
    from platform_app.authoring.contract import get_contract

    monkeypatch.setenv(variable, limit)
    report, *_ = inspect_package(package_bytes())
    assert not report["valid"] and message in report["errors"][0]["message"]
    assert int(limit) in get_contract()["limits"].values()


def test_excessive_json_nesting_is_reported_as_invalid():
    files = example_files()
    nested = "leaf"
    for _ in range(65):
        nested = [nested]
    files["script.json"]["untrusted"] = nested
    report, *_ = inspect_package(package_bytes(files))
    assert not report["valid"] and "嵌套深度" in report["errors"][0]["message"]
