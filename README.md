# Home Assistant – Celsiview

A [Home Assistant](https://www.home-assistant.io/) custom integration that
imports sensor readings from [Celsiview](https://app.celsiview.se/) (Celsicom)
over its public HTTP API.

Celsiview devices upload their samples to the cloud in bulk a few times per
day rather than streaming live, so this integration is a polling integration:
Home Assistant reads the most recently reported value for each location you
select and exposes it as a sensor entity.

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
   - **Base URL** – usually `https://app.celsiview.se`.
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
the API every minute would not produce fresher data – it would just add
load on the Celsiview servers. The default 15-minute interval is a sensible
compromise; if the hardware you use uploads less often than that you can
safely move the interval up to one hour or more.

The integration performs a **single** `GET /api/v2/locations` request per
poll regardless of how many sensors you have selected, so selecting more
sensors does not increase API load.

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
