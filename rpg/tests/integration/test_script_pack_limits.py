# ruff: noqa: F811 -- imported pytest fixtures are injected by name.
import io
import json
import uuid
import zipfile

import pytest

from platform_app import account_io, federation, save_bundle
from platform_app.authoring import preview, service
from platform_app.authoring.budget import PackageBusy, acquire, package_budget
from platform_app.authoring.examples import example_files, package_bytes
from platform_app.db import connect
from platform_app.knowledge import script_pack
from tests.integration.test_authoring import creator, isolated_database, upload  # noqa: F401


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_and_current_jsonl_are_streamed(creator, monkeypatch, version):
    files = example_files()
    files["manifest.json"]["format_version"] = version
    original = script_pack._safe_member_read

    def bounded_json_only(archive, name, *args, **kwargs):
        assert not name.endswith(".jsonl"), "JSONL must not be read into a whole-member buffer"
        return original(archive, name, *args, **kwargs)

    monkeypatch.setattr(script_pack, "_safe_member_read", bounded_json_only)
    result = script_pack.import_script_pack(package_bytes(files), creator["uid"])
    assert result["ok"]
    with connect() as db:
        assert db.execute("select count(*) as n from script_chapters where script_id=%s",
                          (result["script_id"],)).fetchone()["n"] == 1
    assert any("v1 pack" in warning for warning in result["warnings"]) == (version == 1)


def test_global_row_limit_and_configured_expansion_limit(creator, monkeypatch):
    files = example_files()
    raw = package_bytes(files)
    with connect() as db:
        before = db.execute("select count(*) as n from scripts where owner_id=%s", (creator["uid"],)).fetchone()["n"]
    monkeypatch.setattr(script_pack, "MAX_PACK_JSONL_ROWS", 1)
    with pytest.raises(script_pack.PackLimitError, match="pack JSONL"):
        script_pack.import_script_pack(raw, creator["uid"])
    monkeypatch.setenv("RPG_SCRIPT_PACK_MAX_EXPANDED_BYTES", "16")
    with pytest.raises(ValueError, match="expands too large"):
        script_pack.import_script_pack(raw, creator["uid"])
    with connect() as db:
        assert db.execute("select count(*) as n from scripts where owner_id=%s", (creator["uid"],)).fetchone()["n"] == before


def test_optional_chunks_cannot_hide_resource_limit(creator, monkeypatch):
    files = example_files()
    files["manifest.json"].update(chunks_included=True, chunks_version=1)
    files["chunks.jsonl"] = [{"content": "a"}, {"content": "b"}]
    other_rows = sum(len(value) for name, value in files.items()
                     if name.endswith(".jsonl") and name != "chunks.jsonl")
    monkeypatch.setattr(script_pack, "MAX_PACK_JSONL_ROWS", other_rows + 1)
    with pytest.raises(script_pack.PackLimitError, match="pack JSONL"):
        script_pack.import_script_pack(package_bytes(files), creator["uid"])


def test_shared_budget_rejects_other_entrypoints_and_same_transaction_is_reentrant(creator):
    project, upload_id = upload(creator)
    raw = package_bytes()
    with package_budget():
        with pytest.raises(PackageBusy):
            service.validate_package(creator["uid"], upload_id)
        with pytest.raises(PackageBusy):
            script_pack.import_script_pack(raw, creator["uid"])
        with pytest.raises(PackageBusy):
            federation.ext_publish_pack(creator["uid"], raw)
    with connect() as db:
        acquire(db)
        result = script_pack.import_script_pack(raw, creator["uid"], db=db)
        assert result["ok"]
    assert service.validate_package(creator["uid"], upload_id)["valid"]


def test_account_budget_is_acquired_before_any_script_is_imported(creator):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        scripts = [dict(origin_script_id=i, member=f"scripts/{i}.zip") for i in (1, 2)]
        archive.writestr("account-manifest.json", json.dumps(dict(account_export_version=1, scripts=scripts)))
        for item in scripts:
            archive.writestr(item["member"], package_bytes())
    with connect() as db:
        before = db.execute("select count(*) as n from scripts where owner_id=%s", (creator["uid"],)).fetchone()["n"]
    with package_budget():
        with pytest.raises(PackageBusy):
            account_io.import_account(creator["uid"], output.getvalue())
    with connect() as db:
        assert db.execute("select count(*) as n from scripts where owner_id=%s", (creator["uid"],)).fetchone()["n"] == before
    result = account_io.import_account(creator["uid"], output.getvalue())
    assert result["scripts"] == 2 and not result["warnings"]


@pytest.mark.parametrize("member", ["cards.jsonl", "profile.json", "scripts/unused.zip"])
def test_account_outer_expansion_honors_configured_cap_and_preserves_default(creator, monkeypatch, member):
    output = io.BytesIO()
    payload = (json.dumps({"padding": "x" * 4096}) if member == "profile.json" else " " * 4096)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("account-manifest.json", json.dumps(dict(account_export_version=1, scripts=[])))
        archive.writestr(member, payload)
    monkeypatch.delenv("RPG_SCRIPT_PACK_MAX_EXPANDED_BYTES", raising=False)
    assert account_io.import_account(creator["uid"], output.getvalue())["ok"]
    monkeypatch.setenv("RPG_SCRIPT_PACK_MAX_EXPANDED_BYTES", "1024")
    with pytest.raises(ValueError, match="解压后过大"):
        account_io.import_account(creator["uid"], output.getvalue())


def test_account_nested_script_uses_configured_expansion_cap(creator, monkeypatch):
    files = example_files()
    files["chapters.jsonl"][0]["content"] = "x" * 300_000
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("account-manifest.json", json.dumps(dict(account_export_version=1,
                            scripts=[dict(origin_script_id=1, member="scripts/1.zip")])))
        archive.writestr("scripts/1.zip", package_bytes(files))
    monkeypatch.setenv("RPG_SCRIPT_PACK_MAX_EXPANDED_BYTES", "131072")
    result = account_io.import_account(creator["uid"], output.getvalue())
    assert result["scripts"] == 0
    assert any("expands too large" in warning for warning in result["warnings"])


def test_save_bundle_checks_envelope_before_decompression_and_round_trips(creator, monkeypatch):
    from tests.integration.test_authoring_regressions import configured

    _, revision, _ = configured(creator)
    created = preview.create(creator["uid"], revision["id"], "visitor", str(uuid.uuid4()))
    raw, _ = save_bundle.export_save_bundle(creator["uid"], created["save_id"])
    with package_budget():
        with pytest.raises(PackageBusy):
            save_bundle.import_save_bundle(creator["uid"], raw)
    with monkeypatch.context() as limited:
        limited.setenv("RPG_SCRIPT_PACK_MAX_EXPANDED_BYTES", "16")
        with pytest.raises(ValueError, match="解压后超过"):
            save_bundle.import_save_bundle(creator["uid"], raw)
    result = save_bundle.import_save_bundle(creator["uid"], raw)
    assert result["ok"] and result["save_id"] != created["save_id"]


def test_save_bundle_rejects_compressed_oversized_save_member(creator, monkeypatch):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("save.json", b" " * 4096)
    monkeypatch.setattr(script_pack, "MAX_MEMBER_BYTES", 128)
    with pytest.raises(ValueError, match="成员解压后过大"):
        save_bundle.import_save_bundle(creator["uid"], output.getvalue())
