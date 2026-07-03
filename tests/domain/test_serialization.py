"""Serialization contract tests for domain schemas."""

from pydantic import BaseModel

from tests.domain.fixtures import (
    confirmed_event_bundle,
    daily_report_fixture,
    early_signal_bundle,
    run_state_fixture,
    tech_finance_bundle,
    tool_envelope_fixture,
)


def assert_round_trips(model: BaseModel) -> None:
    dumped = model.model_dump_json()
    restored = model.__class__.model_validate_json(dumped)
    assert restored.model_dump(mode="json") == model.model_dump(mode="json")


def test_core_fixtures_round_trip_json() -> None:
    objects = [run_state_fixture(), daily_report_fixture(), tool_envelope_fixture()]

    for bundle_factory in [early_signal_bundle, confirmed_event_bundle, tech_finance_bundle]:
        bundle = bundle_factory()
        for value in bundle.values():
            if isinstance(value, list):
                objects.extend(value)
            else:
                objects.append(value)

    for model in objects:
        assert_round_trips(model)


def test_enum_values_serialize_as_strings_in_json_dump() -> None:
    run = run_state_fixture()
    payload = run.model_dump(mode="json")
    assert payload["phase"] == "scouting"
    assert payload["status"] == "running"
    assert payload["enabled_sources"] == [
        "hacker_news",
        "github",
        "api_changelog",
        "investor_relations",
    ]

