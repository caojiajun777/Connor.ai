"""Centralized id helper tests."""

from app.core.ids import IdPrefix, deterministic_id, random_id


def test_deterministic_id_is_stable_and_uses_prefix() -> None:
    payload = {"b": 2, "a": [1, 2, 3]}

    first = deterministic_id(IdPrefix.CANDIDATE, payload)
    second = deterministic_id("cand", {"a": [1, 2, 3], "b": 2})

    assert first == second
    assert first.startswith("cand_")
    assert len(first.split("_")[-1]) == 32


def test_random_id_uses_safe_parts_and_unique_token() -> None:
    first = random_id(IdPrefix.RUN, parts=["2026-07-04"], length=16)
    second = random_id(IdPrefix.RUN, parts=["2026-07-04"], length=16)

    assert first.startswith("run_2026-07-04_")
    assert second.startswith("run_2026-07-04_")
    assert first != second
