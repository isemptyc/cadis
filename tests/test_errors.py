from cadis._errors import normalize_reason


def test_normalize_reason_map():
    assert normalize_reason("missing_dataset") == "missing_dataset"
    assert normalize_reason(ValueError("bad")) == "invalid_input"
    assert normalize_reason(RuntimeError("broken")) == "global_init_failed"
    assert normalize_reason(Exception("x")) == "internal_error"
