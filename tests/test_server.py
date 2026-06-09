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
            {"type": "vacation", "running": False, "name": "v1"},
        ],
        "remoteSensors": [
            {"id": "rs:100", "name": "Bedroom", "inUse": True}
        ],
        "weather": {"forecasts": [{"temperature": 680}]},
        "program": {"currentClimateRef": "home", "schedule": [["home"]]},
        "alerts": [{"alertNumber": 1, "alertText": "Filter"}],
        "houseDetails": {"style": "detached", "size": 2400},
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
    assert result["activeVacation"] is None
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
        "abc", "2026-06-01", "2026-06-07", ["compHeat1"]
    )


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
