# Contributing to HP Printer

Thanks for helping maintain this Home Assistant integration.

## Reporting issues

Open an issue at https://github.com/minimicro34/ha-hpprinter/issues and include:

- Home Assistant version and integration version
- HP printer model, firmware (if known), and connection method (HTTP or HTTPS)
- Steps to reproduce, expected behavior, and observed behavior
- Relevant debug logs and downloaded integration diagnostics, **after removing personal data, network credentials, IP addresses, serial numbers, and other identifiers**

Do not publish passwords, access tokens, or private printer configuration.

## Local development

Use Python 3.14, Node.js 22 and Make. From the repository root:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
make install-dev
make check
```

Individual targets: `make lint`, `make format-check`, `make syntax`, `make json`, `make test`, `make coverage`, and `make test-js`.

Coverage applies to the entire Python integration, with a minimum of 80%. The XML report is written to `coverage.xml`. Add meaningful regression tests for changed behavior rather than tests solely to increase coverage. JavaScript tests use Node's built-in test runner without npm dependencies. Both validation and signed release workflows use `make check`.

## Pull requests

- Target the `master` branch, keep changes focused, and explain their impact.
- Preserve existing entity unique IDs and device identifiers unless a migration is included.
- Run `make check` before submitting; GitHub Actions runs the same checks plus hassfest and HACS validation.
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
