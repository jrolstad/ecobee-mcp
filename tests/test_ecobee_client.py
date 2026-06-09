"""Tests for the Ecobee REST API client."""

import json
import time
from pathlib import Path

import httpx
import pytest
import respx

from ecobee_client import BASE_URL, TOKEN_URL, EcobeeClient


@pytest.fixture
def creds_file(tmp_path: Path) -> Path:
    creds = {
        "apiKey": "test-api-key",
        "accessToken": "old-access-token",
        "refreshToken": "old-refresh-token",
        "expiresAt": int(time.time() * 1000) + 3600_000,
    }
    p = tmp_path / "credentials.json"
    p.write_text(json.dumps(creds))
    return p


@pytest.fixture
def client(creds_file: Path) -> EcobeeClient:
    return EcobeeClient(credentials_path=str(creds_file))


async def test_request_sends_bearer_access_token(client, creds_file):
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.get("/thermostat").mock(
            return_value=httpx.Response(200, json={"thermostatList": []})
        )
        await client.get_full_state()
        sent = route.calls.last.request.headers["authorization"]
        assert sent == "Bearer old-access-token"


async def test_token_refresh_when_expired(client, creds_file):
    # Mark token as already expired
    creds = json.loads(creds_file.read_text())
    creds["expiresAt"] = int(time.time() * 1000) - 5000
    creds_file.write_text(json.dumps(creds))

    with respx.mock() as mock:
        refresh_route = mock.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        )
        api_route = mock.get(f"{BASE_URL}/thermostat").mock(
            return_value=httpx.Response(200, json={"thermostatList": []})
        )
        await client.get_full_state()

        assert refresh_route.called
        assert api_route.calls.last.request.headers["authorization"] == "Bearer new-access-token"

        saved = json.loads(creds_file.read_text())
        assert saved["accessToken"] == "new-access-token"
        assert saved["refreshToken"] == "new-refresh-token"
        assert saved["expiresAt"] > int(time.time() * 1000) + 3500_000


async def test_no_refresh_when_token_fresh(client, creds_file):
    with respx.mock(assert_all_called=False) as mock:
        refresh_route = mock.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={})
        )
        api_route = mock.get(f"{BASE_URL}/thermostat").mock(
            return_value=httpx.Response(200, json={"thermostatList": []})
        )
        await client.get_full_state()
        assert not refresh_route.called
        assert api_route.called


async def test_401_triggers_refresh_and_retry(client, creds_file):
    with respx.mock() as mock:
        refresh_route = mock.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "rotated-token",
                    "refresh_token": "rotated-refresh",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        )
        api_route = mock.get(f"{BASE_URL}/thermostat").mock(
            side_effect=[
                httpx.Response(401),
                httpx.Response(200, json={"thermostatList": [{"identifier": "t1"}]}),
            ]
        )
        result = await client.get_full_state()
        assert result == [{"identifier": "t1"}]
        assert refresh_route.call_count == 1
        assert api_route.call_count == 2
        assert api_route.calls[1].request.headers["authorization"] == "Bearer rotated-token"


async def test_get_full_state_returns_thermostat_list(client):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/thermostat").mock(
            return_value=httpx.Response(
                200,
                json={"thermostatList": [{"identifier": "abc", "name": "Living Room"}]},
            )
        )
        result = await client.get_full_state()
        assert result == [{"identifier": "abc", "name": "Living Room"}]


async def test_get_full_state_returns_empty_when_key_missing(client):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/thermostat").mock(return_value=httpx.Response(200, json={}))
        assert await client.get_full_state() == []


async def test_get_full_state_request_includes_selection_with_all_flags(client):
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.get("/thermostat").mock(
            return_value=httpx.Response(200, json={"thermostatList": []})
        )
        await client.get_full_state()
        sent_params = route.calls.last.request.url.params
        sel = json.loads(sent_params["json"])
        assert sel["selection"]["selectionType"] == "registered"
        for flag in (
            "includeRuntime",
            "includeSensors",
            "includeWeather",
            "includeProgram",
            "includeEvents",
            "includeAlerts",
            "includeHouseDetails",
            "includeSettings",
            "includeEquipmentStatus",
        ):
            assert sel["selection"][flag] is True


async def test_get_runtime_report_passes_dates_and_columns(client):
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.get("/runtimeReport").mock(
            return_value=httpx.Response(200, json={"reportList": []})
        )
        await client.get_runtime_report(
            "t1", "2026-06-01", "2026-06-07", ["compHeat1", "zoneAveTemp"]
        )
        sent = json.loads(route.calls.last.request.url.params["json"])
        assert sent["selection"]["selectionMatch"] == "t1"
        assert sent["startDate"] == "2026-06-01"
        assert sent["endDate"] == "2026-06-07"
        assert sent["columns"] == "compHeat1,zoneAveTemp"
