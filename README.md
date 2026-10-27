# HP Printer integration for Home Assistant

## Maintenance fork

This repository is maintained by [@minimicro34](https://github.com/minimicro34), based on the original HP Printer integration by [@elad-bar](https://github.com/elad-bar/ha-hpprinter). Thanks to the original author and contributors for their work.

Version 3.0.3 is the current stable release, including resilient offline handling, polling controls, extended LEDM diagnostics and the bundled Lovelace dashboard card.

### Contributing

Bug reports and tested pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for reproduction details, CI checks, and compatibility guidelines.

### Licensing and upstream attribution

This project is based on the original [HP Printer integration by elad-bar](https://github.com/elad-bar/ha-hpprinter), with credit to its author and contributors.

The [GNU General Public License v3.0](LICENSE) applies to **new code and original contributions published by this fork starting with v3.0.0**, to the extent that their respective copyright holders have the right to license them under GPL-3.0.

The original upstream code was published without an explicit license. It is **not** retroactively relicensed by this repository's GPL-3.0 file, and its copyright and reuse permissions remain with the original rights holders. The presence of a GPL-3.0 file does not itself resolve permission to redistribute upstream code.

## Description

Configuration support multiple HP Printer devices through Configuration -> Integrations

[Changelog](https://github.com/minimicro34/ha-hpprinter/blob/master/CHANGELOG.md)

## How to

### Requirements

- HP Printer with EWS (Embedded Web Server) support

### Installations via HACS [![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

- In HACS, add `minimicro34/ha-hpprinter` as a custom integration repository, install **HP Printer**, then restart Home Assistant
- This fork is not necessarily listed in the default HACS catalog
- In Settings --> Devices & Services - (Lower Right) "Add Integration"

### Setup

To add integration use Configuration -> Integrations -> Add `HP Printer`
Integration supports **multiple** accounts and devices

| Fields name | Type    | Required | Default | Description                                  |
| ----------- | ------- | -------- | ------- | -------------------------------------------- |
| Host        | Textbox | +        | -       | Defines hostname or IP of the HP Printer EWS |
| Port        | Textbox | +        | 80      | Defines port of the HP Printer EWS           |
| Is SSL      | Boolean | +        | False   | Defines which protocol to use HTTP/S         |

It is also possible to change configuration after setting up using integration configuration.

#### Validation errors

| Errors                                                 |
| ------------------------------------------------------ |
| Invalid parameters provided                            |
| HP Printer Embedded Web Server (EWS) not was not found |

## Polling control (v3.0.3)

HP Printer supports two Home Assistant actions under the `hpprinter` domain:

- `hpprinter.suspend_polling`: stop HTTP requests immediately, mark the printer offline and keep the integration and previously cached counter/consumable values loaded. Repeated calls are safe.
- `hpprinter.force_update`: resume polling if suspended, clear the offline retry backoff and refresh the printer and its endpoints without waiting for normal polling intervals.

Both actions accept an optional `entry_id`. Without it, they target **all** loaded HP Printer configuration entries. For example, in a Home Assistant automation:

```yaml
actions:
  - action: hpprinter.suspend_polling
```

When the printer's HTTP port becomes reachable again:

```yaml
actions:
  - action: hpprinter.force_update
```

For printers controlled by a smart plug, keep the HP Printer integration enabled and call `suspend_polling` when power is cut (or port 80 is unavailable); call `force_update` after port 80 becomes reachable. This avoids removing entities from Home Assistant. The IPP integration, if used separately, does not need to change.

Without an automation, a failed status request marks the printer offline and starts exponential retry backoff (10, 20, 40, 80, 160, then up to 300 seconds). A warning is emitted only if the failure persists for 10 seconds; recovery is logged once if that warning was emitted. Previously fetched counter values are retained.

## HP Printer dashboard card (v3.0.3)

The integration bundles a Lovelace card showing printer status, print/copy/scan counters, ink levels and an expandable diagnostic section (Wi-Fi signal, channel and SSID, network packet statistics, memory, power-saving settings and paper tray information when supported by the printer).

Add a **Manual** card to a Home Assistant dashboard with:

```yaml
type: custom:hpprinter-card
title: HP Printer
```

The card discovers HP Printer entities automatically. If you have multiple HP Printer integrations, specify the relevant configuration entry:

```yaml
type: custom:hpprinter-card
title: Office printer
entry_id: YOUR_HPPRINTER_CONFIG_ENTRY_ID
```

In dashboards using storage-managed resources, the integration registers its versioned card resource automatically. If your dashboard uses YAML-managed resources, register `/hpprinter/hpprinter-card.js` as a JavaScript module in the Lovelace resources configuration. Refresh the browser after upgrading if it still shows the previous card version.

The diagnostic rows depend on the printer model and its LEDM endpoints; unavailable values may appear as a dash. SSIDs supplied in hexadecimal are decoded for display. The card currently uses French labels.

## Devices

Will extract data of the relevant devices, devices that are not available will be ignored.

### Main device

Device that holds entities related to the integration and relations to other sub devices as described below.

_Binary Sensor_

- ePrint Registered
- ePrint Status

_Sensor_

- Manufacture Date

### Printer

Device holds entities of sensors related to number of pages printed and relation to sub devices of consumables

_Sensor_

- Total pages printed
- Total black-and-white pages printed
- Total color pages printed
- Total single-sided pages printed
- Total double-sided pages printed
- Total jams
- Total miss picks

### Scanner

Device holds entities of sensors related to number of pages scanned

_Sensor_

- Total scanned pages
- Total scanned pages from ADF
- Total double-sided pages scanned
- Total pages from scanner glass
- Total jams
- Total miss picks

### Copy

Device holds entities of sensors related to number of pages copied

_Sensor_

- Total copies
- Total copies from ADF
- Total pages from scanner glass
- Total black-and-white copies
- Total color copies

### Fax

Device holds entities of sensors related to number of pages faxed

_Sensor_

- Total faxed

### Consumable

Devices (device per consumable) holds entities related to consumable (Ink, Toner, Printhead) of a printer device

_Binary Sensor_

- Status

_Sensor_

- Station
- Type
- Installation Date
- Level (will not be available for Printhead)
- Expiration Date (will not be available for Printhead)
- Remaining (will not be available for Printhead)
- Counterfeit Refilled
- Genuine Refilled
- Manufacture Date

## Troubleshooting

Before opening an issue, please provide logs and diagnostic file data related to the issue.

### Logs

For debug log level, please add the following to your config.yaml

```yaml
logger:
  default: warning
  logs:
    custom_components.hpprinter: debug
```

Or use the HA capability in device page:

1. Settings
2. Devices & Services
3. HP Printer
4. 3 dots menu
5. Enable debug logging

When done and would like to extract the log, repeat steps, in step #5 - Disable debug logging

### Diagnostic details

Please attach also diagnostic details of the integration, available in:

1. Settings
2. Devices & Services
3. HP Printer
4. 3 dots menu
5. Download diagnostics

Diagnostic file contains 3 section related to data extracted from the device:

- data.debug.rawData - Raw data extracted from all endpoints of the device, from that source you can extract ideas for additional entities to suggest
- data.debug.devicesConfig - Configuration of mapping to convert data from HP Printer EWS to HA devices and entities, that will be the section that new entities will be added
- data.debug.devicesData - Data extracted for HA entities, just relevant data points, according to mapped objects available in section `data.debug.devicesConfig`

## Translations

Integration translated from English to:

- German
- Danish
- Spanish
- French
- Dutch
- Norwegian
- Polish
- Portuguese

Translation is being auto-generated from Google Translate using `utils/generate_translations.py` script,

```json
{
  "en": "en",
  "de": "de",
  "dk": "da",
  "es": "es",
  "fr": "fr",
  "nb": "no",
  "nl": "nl",
  "pl": "pl",
  "pt-BR": "pt"
}
```

If you would like to add new translation language, please add to the `DESTINATION_LANGUAGES` constant the relevant language,
format is:

```json
{
  "HA language": "Google Translate language"
}
```

Script is translating only, new missing values, it will not override translated values.
