"""
Obscurate Client - Privacy-First Python SDK

Give your AI agents "Dark Pool" capabilities with automatic
x402 payment handling and zero-knowledge proof generation.

Quick Start:
    from obscurate import DarkPoolClient

    async with DarkPoolClient() as client:
        # Load wallet credentials
        client.load_credentials(encrypted_note, password)

        # Check balance
        balance = await client.wallet.get_balance()
        print(f"Balance: {balance.total_usdc} USDC")

        # Make a request - payments are handled automatically!
        response = await client.http.get("https://api.data.com/premium")
        print(response.json())

Configuration:
    Set these environment variables or pass to constructor:
    - OBSCURATE_SIDECAR_URL: Privacy Sidecar URL (default: localhost:3000)
    - OBSCURATE_DRY_RUN: Enable dry-run mode for testing
    - OBSCURATE_MAX_SPEND_TX: Max USDC per transaction
    - OBSCURATE_MAX_SPEND_HOURLY: Max USDC per hour

Decorators:
    @client.pay_protected(max_spend=5.0)
    async def fetch_alpha():
        response = await client.http.get("https://api.data.com/alpha")
        return response.json()

For more information: https://docs.obscurate.xyz
"""

from .core import (
    # Main client classes
    DarkPoolClient,
    DarkPoolConfig,
    HTTPInterface,
    SyncDarkPoolClient,
    # Interface classes
    WalletInterface,
    # Convenience functions
    create_client,
)
from .exceptions import (
    ChallengeExpiredError,
    # Configuration errors
    ConfigurationError,
    DryRunError,
    InsufficientAnonymityError,
    InsufficientBalanceError,
    # Network errors
    NetworkError,
    NoteExhaustedError,
    # Base
    ObscurateError,
    PaymentGatewayError,
    # Privacy errors
    PrivacyError,
    ProofGenerationError,
    SidecarUnavailableError,
    SpendingLimitError,
    # Wallet errors
    WalletError,
    WalletLockedError,
)
from .utils import (
    # Utilities
    PaymentLogger,
    PaymentResult,
    SidecarHealth,
    WalletBalance,
    # Data models
    X402Challenge,
    build_payment_header,
    extract_challenge_from_response,
    validate_usdc_amount,
)

__version__ = "0.1.0"
__all__ = [
    # Version
    "__version__",
    # Main client
    "DarkPoolClient",
    "DarkPoolConfig",
    "SyncDarkPoolClient",
    "create_client",
    # Interfaces
    "WalletInterface",
    "HTTPInterface",
    # Data models
    "X402Challenge",
    "PaymentResult",
    "WalletBalance",
    "SidecarHealth",
    # Base exceptions
    "ObscurateError",
    # Wallet exceptions
    "WalletError",
    "WalletLockedError",
    "InsufficientBalanceError",
    "NoteExhaustedError",
    # Privacy exceptions
    "PrivacyError",
    "InsufficientAnonymityError",
    "ProofGenerationError",
    # Network exceptions
    "NetworkError",
    "SidecarUnavailableError",
    "PaymentGatewayError",
    "ChallengeExpiredError",
    # Config exceptions
    "ConfigurationError",
    "DryRunError",
    "SpendingLimitError",
    # Utilities
    "PaymentLogger",
    "extract_challenge_from_response",
    "build_payment_header",
    "validate_usdc_amount",
]
