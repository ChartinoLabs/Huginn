# Changelog

All notable changes to Huginn are documented in this file.

<!-- towncrier release notes start -->

## 0.2.0 - 2026-06-17

### Added

- Added a concepts documentation page for pruning, explaining the motivation, lifecycle placement, and relationship to reconciliation. ([#142](https://github.com/ChartinoLabs/Huginn/pull/142))

### Internal

- Relax mainline dependency version floors to true minimums, pin dev dependencies to exact versions, and add CI job to test lowest dependency bounds. ([#143](https://github.com/ChartinoLabs/Huginn/pull/143))


## 0.1.0 - 2026-06-15

### Added

- Initial release of the `huginn-framework` package with async-first test automation, plugin-based architecture, and SSH/HTTP/NETCONF brokers.
