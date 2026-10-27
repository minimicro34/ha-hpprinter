# Contributing to HP Printer

Thanks for helping maintain this Home Assistant integration.

## Reporting issues

Open an issue at https://github.com/minimicro34/ha-hpprinter/issues and include:

- Home Assistant version and integration version
- HP printer model, firmware (if known), and connection method (HTTP or HTTPS)
- Steps to reproduce, expected behavior, and observed behavior
- Relevant debug logs and downloaded integration diagnostics, **after removing personal data, network credentials, IP addresses, serial numbers, and other identifiers**

Do not publish passwords, access tokens, or private printer configuration.

## Pull requests

- Target the `master` branch, keep changes focused, and explain their impact.
- Preserve existing entity unique IDs and device identifiers unless a migration is included.
- Run `ruff check custom_components/hpprinter` and `ruff format --check custom_components/hpprinter`.
- Validate Python syntax and JSON; GitHub Actions also runs hassfest and HACS validation.
- Test with a real printer where possible, including offline/online recovery and existing entity history.
- Add user-facing changes to `CHANGELOG.md`.

## Dashboard card contributions

The bundled Lovelace card lives in `custom_components/hpprinter/www/hpprinter-card.js`. Its resource is registered by the integration for storage-managed dashboards; keep the registration and versioned URL compatible with upgrades.

- Use entity registry unique IDs rather than hardcoded entity IDs; respect the selected `entry_id` when multiple printers are configured.
- Preserve existing card configuration (`type: custom:hpprinter-card`, optional `title` and `entry_id`).
- Handle missing, unknown, unavailable and disabled entities without breaking rendering.
- Escape printer-provided values before inserting them into HTML and do not expose credentials or private diagnostic payloads.
- Check the card with a real printer and refresh the frontend resource after changing JavaScript.
- Document user-visible card changes in the README and changelog.

## Attribution and licensing

This is a maintenance fork of the original integration by [elad-bar](https://github.com/elad-bar/ha-hpprinter). Original upstream code was published without an explicit license. GPL-3.0 is intended for original contributions to this fork from v3.0.0 onward and does not retroactively license upstream code. Contributors must have the right to submit their changes.
