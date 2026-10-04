from relayforge.core.ids import new_ulid


def test_ulids_are_valid_and_monotonic() -> None:
    values = [new_ulid() for _ in range(500)]
    alphabet = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
    assert all(len(value) == 26 and set(value) <= alphabet for value in values)
    assert values == sorted(values)
