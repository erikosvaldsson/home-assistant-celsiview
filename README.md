<p align="center">
  <img src="custom_components/celsiview/brand/logo@2x.png" alt="Celsiview" width="420">
</p>

# Home Assistant – Celsiview

A [Home Assistant](https://www.home-assistant.io/) custom integration that
imports sensor readings from [Celsiview](https://app.celsiview.se/) (Celsicom)
over its public HTTP API.

> **Unofficial, independent project.** This integration has **no relation of
> any kind** to Celsicom AB or the Celsiview service. It is not developed,
> sponsored, endorsed, reviewed, or supported by them, and the logo above is
> an original mark created for this project — not an official Celsiview
> asset. "Celsiview" and "Celsicom" are used here solely to describe what
> this integration talks to, and remain trademarks of their respective
> owners.

Celsiview devices sample every 30 s - 5 min but only upload to the cloud in
bulk, a few times a day. The integration handles this in two ways:

- **Entity state** – each selected location exposes the most recent sample as
  a Home Assistant sensor entity, refreshed on the configured poll interval.
- **Long-term statistics backfill** – after each poll, the integration pulls
  the raw sample stream from Celsiview's history endpoint, aggregates it
  into hourly `min`/`mean`/`max` buckets, and imports those directly into
  Home Assistant's long-term statistics. The result is that the history
  graph for each sensor reflects **on-device sample times**, not the time
  you happened to poll the API — even though the hardware only uploads a
  few times per day.

---

## Features

- Config flow – set up entirely from the Home Assistant UI, no YAML.
- Sensor picker – you choose which Celsiview locations become HA sensors.
  Importing every location in a large account would be wasteful, so nothing
  is imported until you tick it.
- Configurable poll interval – defaults to **15 minutes**, changeable from
  1 minute up to 24 hours from the integration options.
- Automatic units – the unit reported by Celsiview (e.g. `°C`, `%RH`, `MPa`)
  is forwarded to Home Assistant and common sensor types (temperature,
  humidity, pressure, CO₂, illuminance, voltage, current, power, energy,
  sound pressure) are mapped to the matching `device_class` so they appear
  correctly in the Energy/History dashboards and in voice assistants.
- Sample age attribute – each entity exposes the Celsiview sample timestamp
  as `last_value_time` / `last_value_time_iso` so you can see exactly how
  fresh a reading is, which matters when the hardware only phones home a
  few times per day.
- **Historical statistics backfill** – the integration fetches every raw
  sample from Celsiview's history endpoint, not just the latest. Samples
  are bucketed into hourly min/mean/max and imported as long-term
  statistics, so the Statistics dashboard and history graphs show every
  reading at its true on-device timestamp. On first setup, backfill goes
  back to the location's `valid_start`, chunked safely into 180-day
  windows. On every subsequent poll only the gap since the last imported
  hour is fetched, so incremental catch-up is cheap.
- Options flow – change the poll interval and the selected sensors at any
  time without removing the integration.

## Requirements

- Home Assistant 2024.4 or later.
- A Celsiview account with at least one location.
- A Celsiview **API key** – create one at
  [`app.celsiview.se/api/keys`](https://app.celsiview.se/api/keys). You will
  need the **application key** and, if the key has
  *client_secret_required* enabled, also the **client secret**.

## Installation

### HACS (recommended)

1. In Home Assistant, open **HACS → Integrations**.
2. Click the three-dot menu → **Custom repositories**.
3. Add this repository's URL and select category **Integration**.
4. Install **Celsiview** and restart Home Assistant.

Once this repository is accepted into the default HACS index the custom
repository step will no longer be needed.

### GPM (Generic Package Manager)

If you use [GPM](https://github.com/home-assistant-community-integrations/gpm)
to manage custom integrations, install this one with:

```bash
gpm install https://github.com/modvion/home-assistant-celsiview
```

Then restart Home Assistant.

### Manual

1. Copy `custom_components/celsiview` into your Home Assistant
   `config/custom_components/` directory so you end up with
   `config/custom_components/celsiview/manifest.json`.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & services → Add integration** and search for
   **Celsiview**.
2. Enter:
   - **Base URL** – defaults to `https://api.celsiview.se` (the API host).
     Note that `app.celsiview.se` is the **web app** and exposes its own
     `/api/v2/...` routes that behave differently — they silently filter
     some locations and return empty histories. Existing config entries
     pointing at `app.celsiview.se` are migrated automatically on upgrade.
   - **Application key** – from your Celsiview API key.
   - **Client secret** – only required if your API key has
     *client_secret_required* enabled; leave blank otherwise.
   - **Poll interval (minutes)** – how often Home Assistant should ask
     Celsiview for fresh data. Defaults to 15.
3. On the next screen, tick the locations you want to import. Only ticked
   locations are polled – nothing else from the account is loaded.

To change the selection or the poll interval later, open the integration's
**Configure** screen.

## Entities

Each selected Celsiview **Location** becomes one sensor entity with:

| Field | Source |
| --- | --- |
| State | `last_value` |
| Unit | `last_unit` |
| Device class | `last_stype` → HA mapping (e.g. `T` → `temperature`) |
| State class | `measurement` |
| `zid` attribute | Celsiview location ID |
| `sensor_type` attribute | `last_stype` (raw Celsiview code) |
| `last_value_time` attribute | Unix timestamp of the sample |
| `last_value_time_iso` attribute | Same timestamp, ISO 8601 UTC |

All selected locations are grouped under a single "hub" device named after
the Celsiview host.

## Polling behaviour and bulk uploads

Celsiview sensors upload their data in bulk a few times per day. Polling
the API every minute would not produce fresher *entity* values — it would
just add load on the Celsiview servers. The default 15-minute interval is
a sensible compromise.

Two things happen on every poll:

1. **One `GET /api/v2/locations` call** refreshes the current value of
   *all* selected locations in a single request.
2. **Per selected sensor, one `GET /api/v2/location/<zid>/history` call**
   pulls only the samples uploaded since the last hour we already
   imported. On the first poll after setup this can be a bigger request
   (fetching back to the location's `valid_start`, chunked into 180-day
   windows); from then on it's just "samples since the last hour". The
   latest hourly bucket is always re-imported so it fills in as more
   samples arrive within the same hour.

Hourly min/mean/max for each sensor are sent to Home Assistant's
statistics backend via `async_import_statistics`, so the `Statistics`
dashboard and the long-term-history graphs on each sensor entity line up
with the device's own sample timestamps rather than the poll times.

## Troubleshooting

- **"The application key was rejected"** – double-check that you copied the
  `application_key` (not the `zid`) from
  [`app.celsiview.se/api/keys`](https://app.celsiview.se/api/keys), and that
  the IP of your Home Assistant host is allowed on the key
  (`allowed_ips` empty means "any").
- **"No locations were returned"** – the API user connected to the key
  must have access to the locations. Check the `service_user_zid` on the
  API key and make sure that user is authorized on the account where your
  sensors live.
- **Values not updating** – remember Celsiview hardware uploads in bulk a
  few times per day. `last_value_time_iso` will tell you how old the latest
  reading actually is.

## Development

The integration is intentionally small and split by concern:

```
custom_components/celsiview/
├── __init__.py        # config-entry setup & unload
├── api.py             # aiohttp client + Location dataclass
├── config_flow.py     # config + options flow (credentials, selection)
├── const.py           # constants and sensor-type → device_class map
├── coordinator.py     # DataUpdateCoordinator
├── manifest.json
├── sensor.py          # sensor platform
├── strings.json
└── translations/
    └── en.json
```

The HTTP layer lives entirely in [`api.py`](custom_components/celsiview/api.py).
If you need to adjust the authentication header names, the request-key
signature scheme or the endpoint paths, that's the one file to touch.

## License

See [LICENSE](LICENSE) for details.

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed
by Celsicom AB. "Celsiview" and "Celsicom" are trademarks of their
respective owners.
