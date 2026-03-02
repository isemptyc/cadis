from __future__ import annotations

import json

from cadis import _cli


def test_lookup_json_passthrough(monkeypatch, capsys):
    payload = {
        "lookup_status": "ok",
        "engine": "cadis",
        "version": "0.1.0",
        "reason": None,
        "world_context": {"iso2": "TW"},
        "admin_result": {"name": "Xinyi District"},
    }
    monkeypatch.setattr(_cli, "api_lookup", lambda lat, lon: payload)

    code = _cli.main(["lookup", "25.0330", "121.5654", "--json"])
    out = capsys.readouterr().out

    assert code == 0
    assert json.loads(out) == payload


def test_lookup_failed_human(monkeypatch, capsys):
    monkeypatch.setattr(
        _cli,
        "api_lookup",
        lambda lat, lon: {"lookup_status": "failed", "reason": "missing_dataset"},
    )

    code = _cli.main(["lookup", "25.0330", "121.5654"])
    out = capsys.readouterr().out

    assert code == 1
    assert out.strip() == "Lookup failed: missing_dataset"


def test_lookup_partial_human(monkeypatch, capsys):
    monkeypatch.setattr(
        _cli,
        "api_lookup",
        lambda lat, lon: {"lookup_status": "partial", "reason": "missing_dataset"},
    )

    code = _cli.main(["lookup", "25.0330", "121.5654"])
    out = capsys.readouterr().out

    assert code == 0
    assert out.strip() == "Lookup partial: missing_dataset"


def test_info_json_passthrough(monkeypatch, capsys):
    payload = {
        "schema_version": "1",
        "version": "0.1.0",
        "system_iso2": ["JP", "TW"],
        "offline_iso2": ["TW"],
    }
    monkeypatch.setattr(_cli, "api_info", lambda: payload)

    code = _cli.main(["info"])
    out = capsys.readouterr().out

    assert code == 0
    assert json.loads(out) == payload
