# E.ON W1000 → Home Assistant Energy dashboard

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Validate](https://github.com/baranyit/eon-energy-metrics/actions/workflows/validate.yml/badge.svg)](https://github.com/baranyit/eon-energy-metrics/actions/workflows/validate.yml)

🇭🇺 **[Magyar nyelvű leírás](README.hu.md)**

Home Assistant custom integration that imports hourly electricity
**consumption and feed-in** from the E.ON Hungary smart meter portal
([e-portal.eon-hungaria.com/w1000/tavleolv](https://e-portal.eon-hungaria.com/w1000/tavleolv))
into Home Assistant long-term statistics, ready for the **Energy dashboard**.
It reads the portal's **scheduled e-mail export**.

## Why e-mail?

The portal sits entirely behind Cloudflare bot protection and its login uses
reCAPTCHA, so Home Assistant cannot sign in and query it directly. The portal
can, however, e-mail the data every day, and that is what this integration
processes:

```
E.ON portal ──daily e-mail──▶ Gmail ◀────── polling ────── Home Assistant
                              (Apps Script)                (statistics import)
```

Home Assistant does not need to be reachable from the internet, and no IMAP
is needed. Data typically arrives a day late, but always lands on the right
hours.

## Setup

### 1. Scheduled export on the portal

1. Sign in to the portal and pick the metering point on the *Távleolvasás*
   (remote reading) page.
2. Set up a scheduled export: **daily** frequency, **15-minute** (intraday)
   resolution, with the consumption and feed-in meter variables (usually `+A`
   and `-A`), in **XLSX** (or CSV) format, sent to your Gmail address.
3. Use exactly this e-mail subject: `eon-energy-metrics`
   (if you choose another one, change the `QUERY` line in the script).

### 2. Apps Script in your Gmail account

1. Open [script.google.com](https://script.google.com) and create a **New project**.
2. Paste the contents of [apps_script/Code.gs](apps_script/Code.gs) and save.
3. Select the `setup` function and run it. Grant Gmail access, then copy the
   token from the **Execution log**.
   Google warns that the app is not verified: that is your own script. Click
   **Advanced → Go to … (unsafe)**, then **Allow**.
4. **Deploy → New deployment → Web app**: execute as *Me*, access: *Anyone*.
   Copy the URL ending in `…/exec`.

The script is read-only and only returns e-mails with the configured subject,
and only for the token. Run `rotateToken` to replace the token at any time.
The consent screen mentions full Gmail access because Apps Script's `GmailApp`
service has no narrower scope.

### 3. The integration

1. Install via HACS: **HACS → ⋮ → Custom repositories**, repository
   `https://github.com/baranyit/eon-energy-metrics`, type **Integration**.
   Then find "E.ON W1000", download it and restart Home Assistant.

   [![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=baranyit&repository=eon-energy-metrics&category=integration)

   Manual install: copy `custom_components/eon_w1000` into Home Assistant's
   `config/custom_components` directory.
2. **Settings → Devices & services → Add integration → E.ON W1000**.
3. Enter the `…/exec` URL, the token and the column names.

### 4. Energy dashboard

**Settings → Dashboards → Energy**: choose `eon_w1000:<name>_import` as grid
consumption and `eon_w1000:<name>_export` as return to grid. They appear after
the first successful import.

## Backfilling history

A CSV/XLSX file downloaded by hand from the portal can be imported too. Copy
it into a directory Home Assistant is allowed to read (e.g. `/config/eon/`)
and call:

```yaml
action: eon_w1000.import_file
data:
  path: /config/eon/export.xlsx
```

The response shows the detected file layout, meter variables and the number of
hours written. The same period can be imported any number of times: values are
replaced, never added up.

## When are e-mails checked?

E.ON sends the export once a day, so the integration does not poll needlessly:

- For **22 hours after the last processed e-mail** it does not poll at all.
- After that it asks the Apps Script **every hour** until the next e-mail
  arrives, then pauses for 22 hours again. The daily e-mail is therefore
  imported within an hour, with only a few requests per day.
- The 2-hour margin covers an e-mail arriving somewhat earlier than the day
  before.
- On first start, and until the first e-mail has been processed, it polls
  hourly; the first run processes all earlier e-mails matching the search.
- If an e-mail cannot be read, it retries hourly, ignoring the pause, until the
  problem is fixed.
- The **Next e-mail check** sensor shows when the next poll happens. To check
  right away (e.g. when the e-mail came earlier than usual):

  ```yaml
  action: eon_w1000.check_now
  ```

## How it works, limitations

- 15-minute values are summed into hourly kWh. Timestamps are read as
  Hungarian local time; the repeated hour at the autumn DST change is handled.
- If a timestamp marks the **end** of its interval (the first row of a day is
  `00:15`), enable the corresponding option, otherwise data shifts by 15 minutes.
- Two layouts are detected automatically: the scheduled e-mail export (e.g.
  `adatok.xlsx`: one sheet per metering point, rows of
  Pod / Időbélyeg / Változó / Érték / Mértékegység) and the table downloaded
  from the portal (`MertErtekek_*.xlsx`: `Dátum/Idő`, `+A`, `-A` columns).
  Wh and MWh are converted to kWh.
- If an attachment cannot be read, processing stops and the error lists the
  meter variables found in the file. After fixing the settings it continues
  from there.
- One config entry handles one metering point. If the export contains several,
  set the POD id in the options; add the integration again for more points.
- Data is merged per 15-minute interval: a new value replaces the stored one,
  and intervals missing from a file keep their stored value. Hourly values are
  always recomputed from these, so overlapping or re-sent data is never added
  up and an incomplete file can never lower an hour that was already complete.
- An incomplete hour (e.g. an export cut off at the end of the day) is imported
  with the sum of the intervals received so far and completed by the next export.
- Four diagnostic sensors show the last processed e-mail, the next check and
  the newest imported data.
- The UI follows the Home Assistant language (English and Hungarian);
  statistic names are English (e.g. "E.ON consumption").

## Development

The parser, the merging and the polling schedule can be tested without Home
Assistant:

```bash
python3 -m unittest discover -s tests -v
```

The portal's internal API, for reference (not reachable outside a browser):
`/sap/opu/odata/sap/ZWB5_ONLINE_SRV/Login` (login, with a reCAPTCHA token) and
`/sap/opu/odata/sap/ZWB5_W1000/MeasData(...)` (time series, `Bearer <guid>`).

## License

MIT, see [LICENSE](LICENSE). This project is not affiliated with E.ON.
