# ecobee-mcp

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that wraps the [Ecobee](https://www.ecobee.com) thermostat cloud API. Query your Ecobee thermostats conversationally from Claude Code, Claude.ai, or any MCP-compatible client.

**Read-only.** This server only fetches data; it never changes a setpoint, hold, or mode.

## Tools

| Tool | Description |
|------|-------------|
| `list_thermostats` | Thermostats on the account (identifier, name, model, time) |
| `get_thermostat_status` | Current temp, humidity, setpoints, HVAC mode, running equipment, active holds |
| `get_sensors` | Remote-sensor readings (temperature, occupancy, humidity) |
| `get_weather` | Forecast as the thermostat sees it |
| `get_schedule` | Program schedule and comfort profiles (home/away/sleep) |
| `get_alerts` | Active alerts (filter, maintenance, temperature) |
| `get_house_details` | House characteristics (style, size, floors, occupants) |
| `get_extended_runtime` | Last ~15 minutes of 5-minute interval runtime data (near real-time) |
| `list_vacations` | All vacation events on the thermostat (past, current, future) |
| `get_settings` | Full thermostat settings (HVAC config, eco+, smart home/away, ventilator, humidifier — ~116 fields) |
| `get_demand_response` | Active/upcoming utility eco+ demand-response events |
| `get_runtime_report` | Historical 5-minute runtime data over a date range (Ecobee retains ~18 months) |
| `reset_cache` | Clear the in-process cache |

Temperatures from Ecobee are in **tenths of a degree Fahrenheit** (e.g. `723` is 72.3 °F). Equipment runtime columns in `get_runtime_report` are **seconds per 5-minute slot** (300 = ran the full slot).

## Configuration

Ecobee uses OAuth 2.0. You need three things:

1. An **API key** from the [Ecobee developer portal](https://www.ecobee.com/developers/). The portal closed to new registrations in March 2024, so this only works with a grandfathered key.
2. An initial **access token** + **refresh token** (one-time bootstrap via Ecobee's PIN flow — see [Bootstrapping tokens](#bootstrapping-tokens)).
3. A **credentials file** (`credentials.json`) holding all of the above. The server reads from this file and rewrites it after every token refresh.

```json
{
  "apiKey": "your-ecobee-api-key",
  "accessToken": "your-current-access-token",
  "refreshToken": "your-current-refresh-token",
  "expiresAt": 1780975892000
}
```

Set `ECOBEE_CREDENTIALS_PATH` if the file lives somewhere other than `./credentials.json`.

### Why credentials live in a file, not in env vars

Ecobee's `refreshToken` **rotates** — every time the server refreshes the access token, the response includes a *new* refresh token that supersedes the old one. The server has to write that new pair back somewhere persistent or it'll lose access on the next restart.

Environment variables (e.g. `~/.claude.json` `mcpServers.ecobee.env`) are read once at process start and never updated by the server, so they're the wrong home for rotating secrets. A JSON file that the server owns and rewrites in place is the right pattern. That's why the only thing in the MCP client config is `ECOBEE_CREDENTIALS_PATH` pointing at the real credential store.

Static-credential services (e.g. a username/password that's re-used on every login) don't have this problem and can live entirely in env vars.

The server keeps an in-process cache with a 5-minute TTL.

### Bootstrapping tokens

Once, before first run, exchange your API key for a token pair using Ecobee's PIN flow:

```bash
# 1. Get a PIN
curl "https://api.ecobee.com/authorize?response_type=ecobeePin&client_id=<your-api-key>&scope=smartRead"

# 2. Go to https://www.ecobee.com → My Apps → Add Application → paste the PIN → Authorize

# 3. Exchange the auth code from step 1 for tokens
curl -X POST "https://api.ecobee.com/token" \
  -d "grant_type=ecobeePin" \
  -d "code=<code-from-step-1>" \
  -d "client_id=<your-api-key>"
```

Drop the `access_token`, `refresh_token`, and (current-time-ms + `expires_in` * 1000) into `credentials.json`. From there the server refreshes on its own.

## Run locally (stdio)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env  # then edit if needed
.venv\Scripts\python server.py
```

### Connect to Claude Code

Add to `~/.claude.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "ecobee": {
      "type": "stdio",
      "command": "C:\\code\\rolstad-home-workspace\\repos\\ecobee-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\code\\rolstad-home-workspace\\repos\\ecobee-mcp\\server.py"],
      "env": {
        "ECOBEE_CREDENTIALS_PATH": "C:\\code\\rolstad-home-workspace\\repos\\ecobee-mcp\\credentials.json"
      }
    }
  }
}
```

## Run hosted (HTTP)

Set `MCP_TRANSPORT=streamable-http` and the server exposes a Streamable HTTP endpoint on `PORT` (default `8000`). The included `Dockerfile` defaults to this mode.

```bash
docker build -t ecobee-mcp .
docker run --rm -p 8000:8000 \
  -v $(pwd)/credentials.json:/app/credentials.json \
  ecobee-mcp
```

## Project structure

```
ecobee_client.py   # OAuth refresh + httpx REST client; persists credentials.json
server.py          # FastMCP tool definitions + in-process cache + transport toggle
requirements.txt
Dockerfile         # python:3.11-slim, streamable-http transport by default
.env.example
tests/             # pytest suite (unit tests for client + server)
```
