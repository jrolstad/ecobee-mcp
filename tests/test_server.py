"""Tests for the FastMCP server tools (cache + tool happy paths)."""

import time
from unittest.mock import AsyncMock, patch

import pytest

import server


@pytest.fixture(autouse=True)
def clear_cache():
    server._cache.clear()
    yield
    server._cache.clear()


THERMOSTATS = [
    {
        "identifier": "abc",
        "name": "Living Room",
        "modelNumber": "apolloSmart",
        "brand": "ecobee",
        "thermostatTime": "2026-06-08 12:00:00",
        "isRegistered": True,
        "runtime": {
            "connected": True,
            "actualTemperature": 723,
            "actualHumidity": 45,
            "desiredHeat": 700,
            "desiredCool": 750,
            "desiredFanMode": "auto",
        },
        "settings": {"hvacMode": "heat"},
        "equipmentStatus": "fan",
        "events": [
            {"type": "hold", "running": True, "name": "h1"},
            {"type": "vacation", "running": False, "name": "v1", "startDate": "2026-07-01"},
            {"type": "vacation", "running": True, "name": "v-now", "startDate": "2026-06-01"},
            {"type": "demandResponse", "running": True, "name": "dr-active", "heatHoldTemp": 680},
        ],
        "remoteSensors": [
            {"id": "rs:100", "name": "Bedroom", "inUse": True}
        ],
        "weather": {"forecasts": [{"temperature": 680}]},
        "program": {"currentClimateRef": "home", "schedule": [["home"]]},
        "alerts": [{"alertNumber": 1, "alertText": "Filter"}],
        "houseDetails": {"style": "detached", "size": 2400},
        "extendedRuntime": {
            "runtimeInterval": 12,
            "actualTemperature": [720, 721, 722],
            "compHeat1": [120, 60, 0],
        },
        "settings": {
            "hvacMode": "heat",
            "fanMinOnTime": 5,
            "lastServiceDate": "2024-01-15",
        },
    },
    {
        "identifier": "xyz",
        "name": "Cabin",
        "modelNumber": "vulcanSmart",
        "brand": "ecobee",
        "thermostatTime": "2026-06-08 11:55:00",
        "isRegistered": True,
        "runtime": {"actualTemperature": 650},
        "settings": {"hvacMode": "off"},
        "events": [],
        "remoteSensors": [],
        "alerts": [],
    },
]


@pytest.fixture
def mock_client():
    instance = AsyncMock()
    instance.get_full_state.return_value = THERMOSTATS
    instance.get_runtime_report.return_value = {"reportList": [{"thermostatIdentifier": "abc"}]}
    with patch("ecobee_client.EcobeeClient", return_value=instance) as ctor:
        yield ctor, instance


async def test_list_thermostats_returns_summary(mock_client):
    result = await server.list_thermostats()
    assert result == [
        {
            "identifier": "abc",
            "name": "Living Room",
            "modelNumber": "apolloSmart",
            "brand": "ecobee",
            "thermostatTime": "2026-06-08 12:00:00",
            "isRegistered": True,
        },
        {
            "identifier": "xyz",
            "name": "Cabin",
            "modelNumber": "vulcanSmart",
            "brand": "ecobee",
            "thermostatTime": "2026-06-08 11:55:00",
            "isRegistered": True,
        },
    ]


async def test_get_thermostat_status_defaults_to_first(mock_client):
    result = await server.get_thermostat_status()
    assert result["identifier"] == "abc"
    assert result["actualTemperatureTenthsF"] == 723
    assert result["hvacMode"] == "heat"
    assert result["activeHold"]["name"] == "h1"
    assert result["activeVacation"]["name"] == "v-now"
    assert result["equipmentStatus"] == "fan"


async def test_get_thermostat_status_by_id(mock_client):
    result = await server.get_thermostat_status("xyz")
    assert result["identifier"] == "xyz"
    assert result["hvacMode"] == "off"


async def test_get_thermostat_status_unknown_returns_none(mock_client):
    assert await server.get_thermostat_status("nonexistent") is None


async def test_get_sensors_returns_array(mock_client):
    result = await server.get_sensors()
    assert result == [{"id": "rs:100", "name": "Bedroom", "inUse": True}]


async def test_get_sensors_unknown_returns_empty(mock_client):
    assert await server.get_sensors("nonexistent") == []


async def test_get_weather_returns_forecast(mock_client):
    result = await server.get_weather()
    assert result == {"forecasts": [{"temperature": 680}]}


async def test_get_schedule_returns_program_and_current_ref(mock_client):
    result = await server.get_schedule()
    assert result["currentClimateRef"] == "home"
    assert result["program"]["schedule"] == [["home"]]


async def test_get_alerts_returns_array(mock_client):
    assert await server.get_alerts() == [{"alertNumber": 1, "alertText": "Filter"}]


async def test_get_house_details_returns_object(mock_client):
    assert await server.get_house_details() == {"style": "detached", "size": 2400}


async def test_get_extended_runtime_returns_recent_intervals(mock_client):
    result = await server.get_extended_runtime()
    assert result["actualTemperature"] == [720, 721, 722]
    assert result["compHeat1"] == [120, 60, 0]


async def test_get_extended_runtime_unknown_returns_none(mock_client):
    assert await server.get_extended_runtime("nonexistent") is None


async def test_list_vacations_returns_only_vacation_events(mock_client):
    result = await server.list_vacations()
    assert [v["name"] for v in result] == ["v1", "v-now"]
    assert all(e["type"] == "vacation" for e in result)


async def test_list_vacations_returns_empty_when_no_vacations(mock_client):
    assert await server.list_vacations("xyz") == []


async def test_get_settings_returns_full_settings(mock_client):
    result = await server.get_settings()
    assert result["hvacMode"] == "heat"
    assert result["fanMinOnTime"] == 5


async def test_get_settings_unknown_returns_none(mock_client):
    assert await server.get_settings("nonexistent") is None


async def test_get_demand_response_returns_only_dr_events(mock_client):
    result = await server.get_demand_response()
    assert len(result) == 1
    assert result[0]["name"] == "dr-active"
    assert result[0]["type"] == "demandResponse"


async def test_get_demand_response_empty_when_no_dr_events(mock_client):
    assert await server.get_demand_response("xyz") == []


async def test_state_cache_serves_repeat_calls(mock_client):
    _ctor, instance = mock_client
    await server.list_thermostats()
    await server.get_thermostat_status()
    await server.get_sensors()
    instance.get_full_state.assert_awaited_once()


async def test_state_cache_refetches_after_ttl(mock_client):
    _ctor, instance = mock_client
    await server.list_thermostats()
    server._cache["state"]["ts"] = time.time() - server.CACHE_MAX_AGE - 1
    await server.list_thermostats()
    assert instance.get_full_state.await_count == 2


async def test_reset_cache_forces_refetch(mock_client):
    _ctor, instance = mock_client
    await server.list_thermostats()
    msg = await server.reset_cache()
    assert msg == "Cache cleared."
    await server.list_thermostats()
    assert instance.get_full_state.await_count == 2


async def test_runtime_report_passes_columns(mock_client):
    _ctor, instance = mock_client
    await server.get_runtime_report("abc", "2026-06-01", "2026-06-07", ["compHeat1"])
    instance.get_runtime_report.assert_awaited_once_with(
        "abc", "2026-06-01", "2026-06-07", ["compHeat1"], include_sensors=False
    )


async def test_runtime_report_passes_include_sensors(mock_client):
    _ctor, instance = mock_client
    await server.get_runtime_report(
        "abc", "2026-06-01", "2026-06-07", ["zoneAveTemp"], include_sensors=True
    )
    instance.get_runtime_report.assert_awaited_once_with(
        "abc", "2026-06-01", "2026-06-07", ["zoneAveTemp"], include_sensors=True
    )


async def test_runtime_report_cache_key_distinguishes_include_sensors(mock_client):
    _ctor, instance = mock_client
    await server.get_runtime_report("abc", "2026-06-01", "2026-06-07", ["compHeat1"])
    await server.get_runtime_report(
        "abc", "2026-06-01", "2026-06-07", ["compHeat1"], include_sensors=True
    )
    assert instance.get_runtime_report.await_count == 2


async def test_runtime_report_uses_default_columns_when_none(mock_client):
    _ctor, instance = mock_client
    await server.get_runtime_report("abc", "2026-06-01", "2026-06-07")
    args = instance.get_runtime_report.await_args.args
    assert args[0] == "abc"
    assert "compHeat1" in args[3]
    assert "zoneAveTemp" in args[3]


async def test_runtime_report_cached(mock_client):
    _ctor, instance = mock_client
    await server.get_runtime_report("abc", "2026-06-01", "2026-06-07", ["compHeat1"])
    await server.get_runtime_report("abc", "2026-06-01", "2026-06-07", ["compHeat1"])
    instance.get_runtime_report.assert_awaited_once()
