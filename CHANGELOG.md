# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2024-01-15

### Added

- Initial release of `obscurate-client`
- `DarkPoolClient` - Main async client with automatic x402 payment handling
- `SyncDarkPoolClient` - Synchronous wrapper for legacy code
- `WalletInterface` - Balance checks and wallet operations
- `HTTPInterface` - HTTP client with automatic 402 interception
- `@pay_protected` decorator for spending limits
- Dry-run mode for testing without real payments
- Configuration via environment variables
- Comprehensive exception hierarchy:
  - `WalletLockedError`
  - `InsufficientBalanceError`
  - `InsufficientAnonymityError`
  - `ProofGenerationError`
  - `SidecarUnavailableError`
  - `SpendingLimitError`
  - `DryRunError`
- Full type hints and Google-style docstrings
- 48 unit tests with 100% pass rate

### Security

- Never exposes private keys or signing operations
- All cryptographic operations delegated to Privacy Sidecar
- Spending limits to prevent runaway costs
- Dry-run mode for safe testing
