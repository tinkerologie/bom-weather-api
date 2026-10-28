# Agent instructions

`bom-weather-api`: async client for Australian Bureau of Meteorology data,
published to PyPI and used by the `ha-bom-australia` Home Assistant
integration. Python 3.12+, `src/` layout, hatchling, uv.

## Layout

- `src/bom_weather_api/client.py`: `BomClient`, the only public entry point for I/O
- `ftp.py`: `FtpTransport` (aioftp) and the `FileTransport` protocol used to inject fakes in tests
- `parsers.py`: pure, synchronous parsers (DBF, précis XML, observation XML, app API JSON). XML is parsed with `defusedxml`.
- `models.py`: frozen, slotted dataclasses. Every field except identifiers is optional.
- `tests/fixtures/`: real BoM responses captured on 2026-10-28 (trimmed)

## Rules

- Never raise on missing or `null` values; return `None`. Raise `BomParseError` only when a response has the wrong shape.
- Map transport errors to the `BomError` hierarchy; never leak `aiohttp` or `aioftp` exceptions.
- Never use `api.bom.gov.au` (the bom.gov.au website API) or impersonate a browser. Send the honest default User-Agent.
- Keep the public API exported from `__init__.py` and typed (`mypy --strict` must pass).
- Coverage must stay ≥ 95%.

## Commands

```bash
uv sync
uv run pytest --cov
uv run ruff format . && uv run ruff check . && uv run mypy
```

## Releases

Bump `src/bom_weather_api/_version.py` (SemVer), update `CHANGELOG.md`, then
publish a GitHub release tagged `vX.Y.Z`. The release workflow checks the tag
against the version and publishes to PyPI with trusted publishing.
