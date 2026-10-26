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

## Attribution and licensing

This is a maintenance fork of the original integration by [elad-bar](https://github.com/elad-bar/ha-hpprinter). Original upstream code was published without an explicit license. GPL-3.0 is intended for original contributions to this fork from v3.0.0 onward and does not retroactively license upstream code. Contributors must have the right to submit their changes.
