"""Ecobee REST API client.

Auth: OAuth 2.0. Each request carries an access_token in the `Authorization: Bearer`
header. Access tokens expire after ~1 hour; this client refreshes them via the
refresh_token grant a minute before expiry. Both tokens live in a JSON credentials
file (path from `ECOBEE_CREDENTIALS_PATH`, default `./credentials.json`) so they
survive restarts. The refresh_token rotates on each grant, so the file is rewritten
in place after every refresh.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

BASE_URL = "https://api.ecobee.com/1"
TOKEN_URL = "https://api.ecobee.com/token"
TIMEOUT_SECONDS = 15.0
REFRESH_LEEWAY_MS = 60_000


class EcobeeClient:
    def __init__(self, credentials_path: Optional[str] = None):
        path = credentials_path or os.environ.get(
            "ECOBEE_CREDENTIALS_PATH", "./credentials.json"
        )
        self._credentials_path = Path(path)
        self._creds: dict = {}

    def _load(self) -> dict:
        if not self._creds:
            with open(self._credentials_path) as f:
                self._creds = json.load(f)
        return self._creds

    def _save(self) -> None:
        with open(self._credentials_path, "w") as f:
            json.dump(self._creds, f, indent=2)
            f.write("\n")

    async def _refresh(self) -> None:
        creds = self._load()
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": creds["refreshToken"],
                    "client_id": creds["apiKey"],
                },
            )
            resp.raise_for_status()
            body = resp.json()
        now_ms = int(time.time() * 1000)
        creds["accessToken"] = body["access_token"]
        creds["refreshToken"] = body["refresh_token"]
        creds["expiresAt"] = now_ms + body["expires_in"] * 1000
        self._creds = creds
        self._save()

    async def _ensure_token(self) -> str:
        creds = self._load()
        if time.time() * 1000 > creds.get("expiresAt", 0) - REFRESH_LEEWAY_MS:
            await self._refresh()
            creds = self._creds
        return creds["accessToken"]

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        token = await self._ensure_token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(f"{BASE_URL}{path}", params=params, headers=headers)
            if resp.status_code == 401:
                await self._refresh()
                headers["Authorization"] = f"Bearer {self._creds['accessToken']}"
                resp = await client.get(f"{BASE_URL}{path}", params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def get_full_state(self) -> list[dict]:
        """GET /thermostat with all read-only include flags — one fat call that
        backs every read tool. Returns the `thermostatList` array."""
        selection = json.dumps({
            "selection": {
                "selectionType": "registered",
                "selectionMatch": "",
                "includeRuntime": True,
                "includeExtendedRuntime": True,
                "includeSensors": True,
                "includeWeather": True,
                "includeProgram": True,
                "includeEvents": True,
                "includeAlerts": True,
                "includeHouseDetails": True,
                "includeSettings": True,
                "includeEquipmentStatus": True,
            }
        })
        data = await self._get("/thermostat", params={"json": selection})
        return data.get("thermostatList", [])

    async def get_runtime_report(
        self,
        thermostat_id: str,
        start_date: str,
        end_date: str,
        columns: list[str],
        include_sensors: bool = False,
    ) -> dict:
        """GET /runtimeReport — historical 5-minute interval data over a date range.

        Columns: e.g. `auxHeat1`, `compHeat1`, `compCool1`, `fan`, `zoneAveTemp`,
        `zoneHeatTemp`, `zoneCoolTemp`, `zoneHumidity`, `outdoorTemp`. Equipment
        columns are seconds of runtime per 5-minute slot; temperature columns are
        degrees F.
        """
        selection = {
            "selection": {
                "selectionType": "thermostats",
                "selectionMatch": thermostat_id,
            },
            "startDate": start_date,
            "endDate": end_date,
            "columns": ",".join(columns),
            "includeSensors": include_sensors,
        }
        return await self._get("/runtimeReport", params={"json": json.dumps(selection)})
