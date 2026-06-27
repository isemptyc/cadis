"""`cadis lookup` accepts coordinates pasted as 'lat, lon' or 'lat,lon'.

Copy-pasting a coordinate pair (e.g. from a map) yields a comma, which argparse
otherwise rejected ("invalid float value: '26.6,'"). The CLI normalizes the
coordinate tokens before parsing.
"""

from __future__ import annotations

from cadis import _cli


def test_comma_space_two_tokens():
    assert _cli._normalize_lookup_argv(["lookup", "26.628,", "56.553"]) == ["lookup", "26.628", "56.553"]


def test_comma_single_token():
    assert _cli._normalize_lookup_argv(["lookup", "26.628,56.553"]) == ["lookup", "26.628", "56.553"]


def test_plain_two_tokens_unchanged():
    assert _cli._normalize_lookup_argv(["lookup", "25.03", "121.56"]) == ["lookup", "25.03", "121.56"]


def test_negative_with_comma():
    assert _cli._normalize_lookup_argv(["lookup", "-38.751,", "175.877"]) == ["lookup", "-38.751", "175.877"]


def test_json_flag_preserved_either_position():
    assert _cli._normalize_lookup_argv(["lookup", "26.6,", "56.5", "--json"]) == [
        "lookup", "26.6", "56.5", "--json",
    ]
    assert _cli._normalize_lookup_argv(["lookup", "--json", "26.6,", "56.5"]) == [
        "lookup", "26.6", "56.5", "--json",
    ]


def test_non_lookup_commands_untouched():
    assert _cli._normalize_lookup_argv(["info", "--json"]) == ["info", "--json"]
    assert _cli._normalize_lookup_argv(["prepare", "--iso2", "TW"]) == ["prepare", "--iso2", "TW"]


def test_main_parses_pasted_coordinate(monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(
        _cli,
        "api_lookup",
        lambda lat, lon: captured.update(lat=lat, lon=lon)
        or {"execution": {"lookup_status": "ok"}, "result": {"country": {"name": "X"}, "admin_hierarchy": []}},
    )
    code = _cli.main(["lookup", "26.628389256782302,", "56.5539789367912"])
    assert code == 0
    assert captured == {"lat": 26.628389256782302, "lon": 56.5539789367912}
