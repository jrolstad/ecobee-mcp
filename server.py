#!/usr/bin/env python3
"""Ecobee Thermostat MCP Server — read-only access to thermostats, sensors,
weather, schedules, alerts, and historical runtime data."""

import os
import time
from typing import Any, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("ecobee")

CACHE_MAX_AGE = 5 * 60  # 5 minutes
_cache: dict = {}


def _cache_get(key: str) -> Any:
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_MAX_AGE:
        return entry["data"]
    return None


def _cache_set(key: str, data: Any) -> None:
    _cache[key] = {"ts": time.time(), "data": data}


async def _fetch_state() -> list[dict]:
    cached = _cache_get("state")
    if cached is not None:
        return cached
    from ecobee_client import EcobeeClient
    result = await EcobeeClient().get_full_state()
    _cache_set("state", result)
    return result


def _pick(state: list[dict], thermostat_id: Optional[str]) -> Optional[dict]:
    if not state:
        return None
    if thermostat_id is None:
        return state[0]
    for t in state:
        if t.get("identifier") == thermostat_id:
            return t
    return None


@mcp.tool()
async def list_thermostats() -> list[dict]:
    """
    List all Ecobee thermostats on the account.

    Each entry includes `identifier`, `name`, `modelNumber`, `brand`,
    `thermostatTime`, and `isRegistered`. Use `identifier` as the
    `thermostat_id` argument for the other tools.
    """
    state = await _fetch_state()
    return [
        {
            "identifier": t.get("identifier"),
            "name": t.get("name"),
            "modelNumber": t.get("modelNumber"),
            "brand": t.get("brand"),
            "thermostatTime": t.get("thermostatTime"),
            "isRegistered": t.get("isRegistered"),
        }
        for t in state
    ]


@mcp.tool()
async def get_thermostat_status(thermostat_id: Optional[str] = None) -> Optional[dict]:
    """
    Current operating state for a single thermostat.

    Returns current temp, humidity, HVAC mode, setpoints, equipment currently
    running, and active hold/vacation events. Temps from Ecobee are reported
    in tenths-of-a-degree-F (e.g. 723 == 72.3 °F).

    Args:
        thermostat_id: identifier from `list_thermostats`. Omit to use the first
            registered thermostat.
    """
    state = await _fetch_state()
    t = _pick(state, thermostat_id)
    if t is None:
        return None
    runtime = t.get("runtime", {})
    settings = t.get("settings", {})
    events = t.get("events", [])
    return {
        "identifier": t.get("identifier"),
        "name": t.get("name"),
        "thermostatTime": t.get("thermostatTime"),
        "connected": runtime.get("connected"),
        "actualTemperatureTenthsF": runtime.get("actualTemperature"),
        "actualHumidity": runtime.get("actualHumidity"),
        "desiredHeatTenthsF": runtime.get("desiredHeat"),
        "desiredCoolTenthsF": runtime.get("desiredCool"),
        "hvacMode": settings.get("hvacMode"),
        "fan": runtime.get("desiredFanMode"),
        "equipmentStatus": t.get("equipmentStatus", ""),
        "activeHold": next((e for e in events if e.get("running") and e.get("type") == "hold"), None),
        "activeVacation": next((e for e in events if e.get("running") and e.get("type") == "vacation"), None),
    }


@mcp.tool()
async def get_sensors(thermostat_id: Optional[str] = None) -> list[dict]:
    """
    Remote sensor readings (temperature, occupancy, humidity) for a thermostat.

    `inUse` indicates whether the sensor is currently averaged into the
    thermostat's room-temperature reading.

    Args:
        thermostat_id: identifier from `list_thermostats`. Omit for the first.
    """
    state = await _fetch_state()
    t = _pick(state, thermostat_id)
    if t is None:
        return []
    return t.get("remoteSensors", [])


@mcp.tool()
async def get_weather(thermostat_id: Optional[str] = None) -> Optional[dict]:
    """
    Weather conditions and forecast as the thermostat sees them (used to bias
    heat/cool decisions). Forecasts are listed under `forecasts`.

    Args:
        thermostat_id: identifier from `list_thermostats`. Omit for the first.
    """
    state = await _fetch_state()
    t = _pick(state, thermostat_id)
    if t is None:
        return None
    return t.get("weather")


@mcp.tool()
async def get_schedule(thermostat_id: Optional[str] = None) -> Optional[dict]:
    """
    Program schedule and comfort profiles (home/away/sleep climates) for a
    thermostat, plus the currently active climate ref.

    Args:
        thermostat_id: identifier from `list_thermostats`. Omit for the first.
    """
    state = await _fetch_state()
    t = _pick(state, thermostat_id)
    if t is None:
        return None
    return {
        "program": t.get("program"),
        "currentClimateRef": (t.get("program") or {}).get("currentClimateRef"),
    }


@mcp.tool()
async def get_alerts(thermostat_id: Optional[str] = None) -> list[dict]:
    """
    Active alerts for a thermostat (filter reminders, maintenance notices,
    temperature alerts, etc.).

    Args:
        thermostat_id: identifier from `list_thermostats`. Omit for the first.
    """
    state = await _fetch_state()
    t = _pick(state, thermostat_id)
    if t is None:
        return []
    return t.get("alerts", [])


@mcp.tool()
async def get_house_details(thermostat_id: Optional[str] = None) -> Optional[dict]:
    """
    House characteristics (style, size, floors, rooms, occupants, age, window
    efficiency) as configured on the thermostat.

    Args:
        thermostat_id: identifier from `list_thermostats`. Omit for the first.
    """
    state = await _fetch_state()
    t = _pick(state, thermostat_id)
    if t is None:
        return None
    return t.get("houseDetails")


@mcp.tool()
async def get_extended_runtime(thermostat_id: Optional[str] = None) -> Optional[dict]:
    """
    Near-real-time 5-minute interval runtime data — the last ~15 minutes.

    Each numeric field returns three readings (the three most recent 5-min slots).
    Equipment fields (`auxHeat1`, `compHeat1`, `compCool1`, `fan`, …) are seconds
    of runtime in that slot (300 = ran the full slot). Temperatures
    (`actualTemperature`, `desiredHeat`, `desiredCool`, `outdoorTemp`) are
    tenths of a degree F. Updated every 15 minutes by the thermostat — for
    longer history use `get_runtime_report`.

    Args:
        thermostat_id: identifier from `list_thermostats`. Omit for the first.
    """
    state = await _fetch_state()
    t = _pick(state, thermostat_id)
    if t is None:
        return None
    return t.get("extendedRuntime")


@mcp.tool()
async def list_vacations(thermostat_id: Optional[str] = None) -> list[dict]:
    """
    All vacation events scheduled on a thermostat (past, current, future).

    Each entry includes `name`, `startDate`/`startTime`, `endDate`/`endTime`,
    `heatHoldTemp`/`coolHoldTemp` (tenths of °F), and `running` (true if active
    now). Empty list if there are no vacation events.

    Args:
        thermostat_id: identifier from `list_thermostats`. Omit for the first.
    """
    state = await _fetch_state()
    t = _pick(state, thermostat_id)
    if t is None:
        return []
    return [e for e in t.get("events", []) if e.get("type") == "vacation"]


@mcp.tool()
async def get_settings(thermostat_id: Optional[str] = None) -> Optional[dict]:
    """
    Full thermostat settings — HVAC config, comfort thresholds, eco+ options,
    smart-home/away, ventilator schedules, humidifier settings, service
    reminders, etc. ~116 fields total.

    Args:
        thermostat_id: identifier from `list_thermostats`. Omit for the first.
    """
    state = await _fetch_state()
    t = _pick(state, thermostat_id)
    if t is None:
        return None
    return t.get("settings")


@mcp.tool()
async def get_demand_response(thermostat_id: Optional[str] = None) -> list[dict]:
    """
    Active and upcoming demand-response (DR) events from your utility's eco+
    program — temperature offsets, duty-cycle adjustments, and the time
    window the utility wants you to participate in.

    Returned as the subset of `events` with `type == "demandResponse"`. Empty
    list if your account isn't enrolled or no DR event is scheduled.

    Args:
        thermostat_id: identifier from `list_thermostats`. Omit for the first.
    """
    state = await _fetch_state()
    t = _pick(state, thermostat_id)
    if t is None:
        return []
    return [e for e in t.get("events", []) if e.get("type") == "demandResponse"]


@mcp.tool()
async def get_runtime_report(
    thermostat_id: str,
    start_date: str,
    end_date: str,
    columns: Optional[list[str]] = None,
) -> dict:
    """
    Historical 5-minute interval runtime data over a date range. This is the
    primary "what happened in the past" tool — Ecobee retains ~18 months of
    history.

    Equipment columns return **seconds of runtime in each 5-minute slot**
    (300 = ran the full slot). Temperature columns return tenths of a degree F.
    Max range per request: 31 days.

    Args:
        thermostat_id: identifier from `list_thermostats`.
        start_date: YYYY-MM-DD (inclusive).
        end_date: YYYY-MM-DD (inclusive).
        columns: list of column names; defaults to a useful all-purpose set
            (heat/cool/fan runtime + ambient/setpoint temps + humidity + outdoor
            temp). Common columns: `auxHeat1`, `compHeat1`, `compCool1`,
            `fan`, `zoneAveTemp`, `zoneHeatTemp`, `zoneCoolTemp`,
            `zoneHumidity`, `outdoorTemp`, `outdoorHumidity`.
    """
    cols = columns or [
        "auxHeat1",
        "compHeat1",
        "compCool1",
        "fan",
        "zoneAveTemp",
        "zoneHeatTemp",
        "zoneCoolTemp",
        "zoneHumidity",
        "outdoorTemp",
    ]
    key = f"runtime:{thermostat_id}:{start_date}:{end_date}:{','.join(cols)}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    from ecobee_client import EcobeeClient
    result = await EcobeeClient().get_runtime_report(
        thermostat_id, start_date, end_date, cols
    )
    _cache_set(key, result)
    return result


@mcp.tool()
async def reset_cache() -> str:
    """Clear all cached Ecobee data, forcing fresh data on the next request."""
    _cache.clear()
    return "Cache cleared."


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
