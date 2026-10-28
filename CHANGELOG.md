# Changelog

All notable changes to this project are documented in this file. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-28

### Added

- `BomClient` with forecast locations, observation stations, observations,
  daily town forecasts (FTP), hourly forecasts and warnings (BoM app API).
- Typed, null-safe models and parsers for the BoM FTP products and app API.
- Support for Python 3.12 to 3.15.
- Anonymous FTP transport built on `aioftp`, with injectable transports for
  testing.
