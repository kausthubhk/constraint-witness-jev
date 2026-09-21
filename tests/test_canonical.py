from contract_eval.canonical import canonical_bytes, canonical_sha256


def test_canonical_json_sorts_keys_and_normalizes_line_endings() -> None:
    assert canonical_bytes({"z": "a\r\nb", "a": None}) == b'{"a":null,"z":"a\\nb"}'
    assert canonical_sha256({"b": 1, "a": 2}) == canonical_sha256({"a": 2, "b": 1})


def test_absent_and_null_remain_distinct() -> None:
    assert canonical_sha256({"a": None}) != canonical_sha256({})
