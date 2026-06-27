"""Regression: the CLI's post-download retry reprint must keep the Water Body line.

When the admin dataset is missing, the CLI offers to install it and then re-runs
the lookup. That retry path used to print only Region + admin hierarchy, dropping
the water body — so a lake/river point (e.g. Lake Taupō) showed no water body
whenever its country dataset had to be downloaded first.
"""

from __future__ import annotations

from cadis import _cli


def test_lookup_retry_after_install_renders_waterbody(monkeypatch, capsys):
    responses = iter(
        [
            {
                "execution": {"lookup_status": "failed"},
                "state": {
                    "world": {"classification": "country", "iso2": "NZ", "name": "New Zealand"},
                    "dataset": {"status": "missing", "iso2": "NZ"},
                },
            },
            {
                "execution": {"lookup_status": "ok"},
                "result": {
                    "country": {"name": "New Zealand"},
                    "waterbody": {
                        "name": "Lake Taupo",
                        "feature_id": "curated_r1130806",
                        "names": {"en": "Lake Taupo", "native": "Taupō"},
                    },
                    "admin_hierarchy": [
                        {"rank": 0, "name": "Waikato"},
                        {"rank": 1, "name": "Taupō District"},
                    ],
                },
            },
        ]
    )
    monkeypatch.setattr(_cli, "api_lookup", lambda lat, lon: next(responses))
    monkeypatch.setattr(_cli, "api_info", lambda: {"supported_iso2": ["NZ"]})
    monkeypatch.setattr(_cli, "api_reinstall", lambda iso2, **kwargs: {"bootstrap_status": "ready"})
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    code = _cli.main(["lookup", "-38.75122492478569", "175.87743741652008"])
    out = capsys.readouterr().out

    assert code == 0
    assert "Water Body: Lake Taupo" in out
    assert "Taupō(native)" in out
    assert "Rank 0: Waikato" in out
