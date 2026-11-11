<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/energy_metrics_eon/brand/dark_logo.png">
    <img alt="Energy Monitoring for E.ON Hungary" src="custom_components/energy_metrics_eon/brand/logo.png" width="480">
  </picture>
</p>

# Energy Monitoring for E.ON Hungary

A Home Assistant integration that imports hourly electricity **consumption and feed-in** from the
**E.ON Hungary** smart meter portal into long-term statistics, ready for the **Energy dashboard**.
It reads the portal's scheduled e-mail export. No scraping, no IMAP, no open ports.

[![HACS validation](https://github.com/baranyit/energy-metrics-eon/actions/workflows/hacs.yml/badge.svg)](https://github.com/baranyit/energy-metrics-eon/actions/workflows/hacs.yml)
[![Hassfest](https://github.com/baranyit/energy-metrics-eon/actions/workflows/hassfest.yml/badge.svg)](https://github.com/baranyit/energy-metrics-eon/actions/workflows/hassfest.yml)

🇭🇺 **[Magyar nyelvű leírás](README.hu.md)**

> **Status: beta (0.1.0).** Data typically arrives a day late, because the portal sends its export
> once a day. This is an unofficial project, not affiliated with or endorsed by E.ON. Use it at
> your own risk.

## What it does

One config entry is one metering point (POD). For each it provides:

- two **long-term statistics** for the Energy dashboard: `energy_metrics_eon:<name>_import` (grid
  consumption) and `energy_metrics_eon:<name>_export` (return to grid), in hourly kWh,
- four **diagnostic sensors**: last processed e-mail, next e-mail check, newest consumption data
  and newest feed-in data,
- two **actions**: `energy_metrics_eon.import_file` to backfill history from a downloaded file and
  `energy_metrics_eon.check_now` to look for a new e-mail right away.

The 15-minute values of the portal are summed into hours and always land on the right hours, even
when they arrive late or more than once.

## Why e-mail?

The portal
([e-portal.eon-hungaria.com/w1000/tavleolv](https://e-portal.eon-hungaria.com/w1000/tavleolv))
sits entirely behind Cloudflare bot protection and its login uses reCAPTCHA, so Home Assistant
cannot sign in and query it directly. The portal can, however, e-mail the data every day, and that
is what this integration processes:

```
E.ON portal ──daily e-mail──▶ Gmail ◀────── polling ────── Home Assistant
                              (Apps Script)                (statistics import)
```

- **Home Assistant stays private.** It only makes outgoing requests; it does not need to be
  reachable from the internet.
- **Gmail stays private.** A small Apps Script in your own Google account hands over only the
  e-mails with the configured subject, and only for a secret token. It is read-only.
- **Few requests.** After each e-mail the integration pauses for 22 hours, then checks hourly
  (see [when e-mails are checked](#when-are-e-mails-checked)).

## Installation

HACS (custom repository) or manual copy:

1. HACS → ⋮ → Custom repositories → add `https://github.com/baranyit/energy-metrics-eon`
   as an *Integration*, install **Energy Monitoring for E.ON Hungary**, restart Home Assistant.
   Manual: copy `custom_components/energy_metrics_eon` into your Home Assistant `custom_components`.

   [![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=baranyit&repository=energy-metrics-eon&category=integration)
2. Settings → Devices & services → Add integration → **Energy Monitoring for E.ON Hungary**
   (after the [setup](#setup) steps below, which give you the URL and the token it asks for).

Requires Home Assistant 2024.12 or newer and `openpyxl` (installed automatically).

## Setup

### 1. Scheduled export on the portal

1. Sign in to the portal and pick the metering point on the *Távleolvasás* (remote reading) page.
2. Set up a scheduled export: **daily** frequency, **15-minute** (intraday) resolution, with the
   consumption and feed-in meter variables (usually `+A` and `-A`), in **XLSX** (or CSV) format,
   sent to your Gmail address.
3. Use exactly this e-mail subject: `energy-metrics-eon` (if you choose another one, change the
   `QUERY` line in the script).

### 2. Apps Script in your Gmail account

1. Open [script.google.com](https://script.google.com) and create a **New project**.
2. Paste the contents of [apps_script/Code.gs](apps_script/Code.gs) and save.
3. Select the `setup` function and run it. Grant Gmail access, then copy the token from the
   **Execution log**. Google warns that the app is not verified: that is your own script. Click
   **Advanced → Go to … (unsafe)**, then **Allow**.
4. **Deploy → New deployment → Web app**: execute as *Me*, access: *Anyone*. Copy the URL ending
   in `…/exec`.

Run `rotateToken` to replace the token at any time. The consent screen mentions full Gmail access
because Apps Script's `GmailApp` service has no narrower scope.

### 3. The integration

Add the integration and enter the `…/exec` URL, the token and the column names. Setup makes one
request to the script to check the URL and the token.

### 4. Energy dashboard

Settings → Dashboards → Energy: choose `energy_metrics_eon:<name>_import` as grid consumption and
`energy_metrics_eon:<name>_export` as return to grid. They appear after the first successful import.

## Options

All of these are asked at setup and, except the name, can be changed later with *Reconfigure*.

| Option | Default | Meaning |
|---|---|---|
| Name | `E.ON` | Used to build the statistic ids. Cannot be changed later. |
| Apps Script web app URL | none | The `…/exec` URL of your deployment. |
| Token | none | The token printed by the script's `setup` function. |
| Consumption column name | `+A` | Meter variable in the export header. May be left empty. |
| Feed-in column name | `-A` | Leave empty if there is no feed-in. At least one of the two columns is needed. |
| Metering point (POD) id | empty | Only needed when the export contains several metering points (e.g. `HU000…`). |
| Timestamps mark the end of the interval | off | Enable if the first row of a day is `00:15`, otherwise data shifts by 15 minutes. |

### When are e-mails checked?

E.ON sends the export once a day, so the integration does not poll needlessly:

- For **22 hours after the last processed e-mail** it does not poll at all.
- After that it asks the Apps Script **every hour** until the next e-mail arrives, then pauses for
  22 hours again. The daily e-mail is therefore imported within an hour, with only a few requests
  per day.
- The 2-hour margin covers an e-mail arriving somewhat earlier than the day before.
- On first start, and until the first e-mail has been processed, it polls hourly; the first run
  processes all earlier e-mails matching the search.
- If an e-mail cannot be read, it retries hourly, ignoring the pause, until the problem is fixed.

The **Next e-mail check** sensor shows when the next poll happens. To check right away (e.g. when
the e-mail came earlier than usual):

```yaml
action: energy_metrics_eon.check_now
```

### Backfilling history

A CSV/XLSX file downloaded by hand from the portal can be imported too. Copy it into a directory
Home Assistant is allowed to read (e.g. `/config/eon/`) and call:

```yaml
action: energy_metrics_eon.import_file
data:
  path: /config/eon/export.xlsx
```

The response shows the detected file layout, meter variables and the number of hours written. The
same period can be imported any number of times: values are replaced, never added up.

## How the data is processed

- **Hourly kWh.** 15-minute values are summed into hours. Wh and MWh are converted to kWh.
- **Hungarian local time.** Timestamps are read as Hungarian local time; the repeated hour at the
  autumn DST change is handled.
- **Two file layouts**, detected automatically: the scheduled e-mail export (e.g. `adatok.xlsx`:
  one sheet per metering point, rows of Pod / Időbélyeg / Változó / Érték / Mértékegység) and the
  table downloaded from the portal (`MertErtekek_*.xlsx`: `Dátum/Idő`, `+A`, `-A` columns).
- **Merged per 15-minute interval.** A new value replaces the stored one, and intervals missing
  from a file keep their stored value. Hourly values are always recomputed from these, so
  overlapping or re-sent data is never added up and an incomplete file can never lower an hour
  that was already complete.
- **Incomplete hours** (e.g. an export cut off at the end of the day) are imported with the sum of
  the intervals received so far and completed by the next export.

## Known limitations

- Data is not live: it follows the portal's daily e-mail, typically a day late.
- Only Gmail is supported as the mailbox, through the Apps Script.
- One config entry handles one metering point. If the export contains several, set the POD id;
  add the integration again for more points.
- The UI follows the Home Assistant language (English and Hungarian), but statistic names are
  English (e.g. "E.ON consumption").
- The name of an entry cannot be changed later, because the statistic ids are built from it.

## Troubleshooting

- **Nothing is imported.** Check the **Last processed e-mail** and **Next e-mail check** sensors,
  then run `energy_metrics_eon.check_now`. Make sure the e-mail subject matches the script's `QUERY`.
- **An attachment cannot be read.** Processing stops and the error lists the meter variables found
  in the file. After fixing the column names it continues from there.
- **The token is rejected.** Home Assistant asks for the new one (re-authentication); `rotateToken`
  in the script creates a new token.
- **The script cannot be reached.** Check that it is deployed as a web app with access set to
  *Anyone*, and that the URL ends in `…/exec`.
- **Values are shifted by 15 minutes.** Toggle *Timestamps mark the end of the interval* with
  *Reconfigure*.

## Development

The parser, the merging and the polling schedule can be tested without Home Assistant:

```bash
python3 -m unittest discover -s tests -v
```

The portal's internal API, for reference (not reachable outside a browser):
`/sap/opu/odata/sap/ZWB5_ONLINE_SRV/Login` (login, with a reCAPTCHA token) and
`/sap/opu/odata/sap/ZWB5_W1000/MeasData(...)` (time series, `Bearer <guid>`).

## License

MIT, see [LICENSE](LICENSE).
