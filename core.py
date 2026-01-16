"""
Obscurate Client - Core Module

The main DarkPoolClient implementation providing:
- Sync and Async HTTP clients with automatic 402 handling
- Wallet operations (balance, deposits, withdrawals)
- Spending limits and dry-run mode
- Pay-protected decorators for agent developers

Usage:
    from obscurate import DarkPoolClient

    async with DarkPoolClient() as client:
        # Check balance
        balance = await client.wallet.get_balance()

        # Make a payment-protected request
        response = await client.http.get("https://api.data.com/premium")
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import (
    Any,
    ParamSpec,
    TypeVar,
)

import httpx

from .exceptions import (
    ChallengeExpiredError,
    ConfigurationError,
    DryRunError,
    InsufficientBalanceError,
    NoteExhaustedError,
    PaymentGatewayError,
    ProofGenerationError,
    SidecarUnavailableError,
    SpendingLimitError,
    WalletLockedError,
)
from .utils import (
    PaymentLogger,
    PaymentResult,
    SidecarHealth,
    WalletBalance,
    X402Challenge,
    build_payment_header,
    extract_challenge_from_response,
    validate_sidecar_url,
)

logger = logging.getLogger("obscurate")

# Type variables for decorators
P = ParamSpec("P")
T = TypeVar("T")


# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass
class DarkPoolConfig:
    """
    Configuration for the DarkPoolClient.

    Can be set via constructor arguments or environment variables.

    Environment Variables:
        OBSCURATE_SIDECAR_URL: Privacy Sidecar URL
        OBSCURATE_DRY_RUN: Enable dry-run mode (true/false)
        OBSCURATE_MAX_SPEND_TX: Max spend per transaction (USDC)
        OBSCURATE_MAX_SPEND_HOURLY: Max spend per hour (USDC)
        OBSCURATE_MAX_RETRIES: Max payment retries
        OBSCURATE_TIMEOUT: Request timeout in seconds
    """

    sidecar_url: str = field(
        default_factory=lambda: os.environ.get(
            "OBSCURATE_SIDECAR_URL", "http://localhost:3000"
        )
    )

    dry_run: bool = field(
        default_factory=lambda: os.environ.get("OBSCURATE_DRY_RUN", "").lower()
        in ("true", "1", "yes")
    )

    # Spending limits (0 = no limit)
    max_spend_per_tx: float = field(
        default_factory=lambda: float(os.environ.get("OBSCURATE_MAX_SPEND_TX", "0"))
    )
    max_spend_hourly: float = field(
        default_factory=lambda: float(os.environ.get("OBSCURATE_MAX_SPEND_HOURLY", "0"))
    )

    # Network settings
    max_retries: int = field(
        default_factory=lambda: int(os.environ.get("OBSCURATE_MAX_RETRIES", "3"))
    )
    timeout: float = field(
        default_factory=lambda: float(os.environ.get("OBSCURATE_TIMEOUT", "30.0"))
    )

    # Credentials (loaded separately for security)
    encrypted_note: str | None = None
    note_password: str | None = None

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        self.sidecar_url = validate_sidecar_url(self.sidecar_url)


# =============================================================================
# WALLET INTERFACE
# =============================================================================


class WalletInterface:
    """
    Wallet operations interface.

    Provides access to balance checks, deposits, and note management
    through the Privacy Sidecar.
    """

    def __init__(self, client: DarkPoolClient) -> None:
        """
        Initialize the wallet interface.

        Args:
            client: Parent DarkPoolClient instance.
        """
        self._client = client

    async def get_balance(self) -> WalletBalance:
        """
        Get the current wallet balance.

        Returns:
            WalletBalance with total USDC and note breakdown.

        Raises:
            WalletLockedError: If credentials not loaded.
            SidecarUnavailableError: If sidecar unreachable.
        """
        self._client._ensure_unlocked()

        response = await self._client._sidecar_request(
            "POST",
            "/api/balance",
            json={
                "encryptedNote": self._client._config.encrypted_note,
                "notePassword": self._client._config.note_password,
            },
        )

        return WalletBalance.model_validate(response)

    async def get_largest_note(self) -> float:
        """
        Get the value of the largest available note.

        Useful for checking if a specific payment can be made
        without merging notes.

        Returns:
            Value of largest note in USDC.
        """
        balance = await self.get_balance()
        return balance.largest_note

    async def can_afford(self, amount: float) -> bool:
        """
        Check if a payment can be afforded.

        Args:
            amount: Amount to check (USDC).

        Returns:
            True if payment can be made, False otherwise.
        """
        try:
            balance = await self.get_balance()
            return balance.total_usdc >= amount
        except Exception:
            return False


# =============================================================================
# HTTP INTERFACE
# =============================================================================


class HTTPInterface:
    """
    HTTP client with automatic x402 payment handling.

    All requests through this interface will automatically:
    1. Detect 402 Payment Required responses
    2. Extract the payment challenge
    3. Request payment authorization from the Sidecar
    4. Retry the request with the payment header
    """

    def __init__(self, client: DarkPoolClient) -> None:
        """
        Initialize the HTTP interface.

        Args:
            client: Parent DarkPoolClient instance.
        """
        self._client = client

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auto_pay: bool = True,
        max_spend: float | None = None,
    ) -> httpx.Response:
        """
        Make a GET request with automatic payment handling.

        Args:
            url: Target URL.
            params: Optional query parameters.
            headers: Optional additional headers.
            auto_pay: Whether to auto-pay on 402 (default: True).
            max_spend: Maximum amount to spend (overrides config).

        Returns:
            The HTTP response.

        Raises:
            InsufficientBalanceError: If payment required but insufficient funds.
            SpendingLimitError: If payment would exceed limits.
        """
        return await self._request(
            "GET",
            url,
            params=params,
            headers=headers,
            auto_pay=auto_pay,
            max_spend=max_spend,
        )

    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        data: bytes | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auto_pay: bool = True,
        max_spend: float | None = None,
    ) -> httpx.Response:
        """
        Make a POST request with automatic payment handling.

        Args:
            url: Target URL.
            json: Optional JSON body.
            data: Optional raw body data.
            params: Optional query parameters.
            headers: Optional additional headers.
            auto_pay: Whether to auto-pay on 402 (default: True).
            max_spend: Maximum amount to spend (overrides config).

        Returns:
            The HTTP response.

        Raises:
            InsufficientBalanceError: If payment required but insufficient funds.
            SpendingLimitError: If payment would exceed limits.
        """
        return await self._request(
            "POST",
            url,
            json=json,
            content=data,
            params=params,
            headers=headers,
            auto_pay=auto_pay,
            max_spend=max_spend,
        )

    async def put(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        auto_pay: bool = True,
        max_spend: float | None = None,
    ) -> httpx.Response:
        """Make a PUT request with automatic payment handling."""
        return await self._request(
            "PUT",
            url,
            json=json,
            content=data,
            headers=headers,
            auto_pay=auto_pay,
            max_spend=max_spend,
        )

    async def delete(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        auto_pay: bool = True,
        max_spend: float | None = None,
    ) -> httpx.Response:
        """Make a DELETE request with automatic payment handling."""
        return await self._request(
            "DELETE",
            url,
            headers=headers,
            auto_pay=auto_pay,
            max_spend=max_spend,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        auto_pay: bool = True,
        max_spend: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Internal request method with 402 interception.

        THE DARK POOL MAGIC:
        1. Make the original request
        2. If 402, extract challenge
        3. Validate spending limits
        4. Request payment from Sidecar (ZK proof generation)
        5. Retry with X-PAYMENT header
        """
        http_client = self._client._http_client
        if http_client is None:
            raise ConfigurationError("Client not connected. Call connect() first.")

        config = self._client._config
        payment_logger = self._client._payment_logger

        # Merge headers
        request_headers = dict(kwargs.pop("headers", None) or {})

        for attempt in range(1, config.max_retries + 1):
            # Make the request
            response = await http_client.request(
                method, url, headers=request_headers, **kwargs
            )

            # Not a payment challenge - return as-is
            if response.status_code != 402:
                return response

            # No auto-pay - return the 402
            if not auto_pay:
                return response

            # Extract the challenge
            challenge = extract_challenge_from_response(
                response.status_code,
                dict(response.headers),
                response.content,
            )

            if not challenge:
                logger.warning(f"Got 402 but could not extract challenge from {url}")
                return response

            # Check if challenge is expired
            if challenge.is_expired():
                raise ChallengeExpiredError(
                    resource=url,
                    expired_at=challenge.expiry,
                )

            # Validate spending limits
            amount = challenge.amount_float
            effective_max = max_spend or config.max_spend_per_tx

            if effective_max > 0 and amount > effective_max:
                raise SpendingLimitError(
                    requested=amount,
                    limit=effective_max,
                    period="transaction",
                )

            # Check hourly limit
            if config.max_spend_hourly > 0:
                hourly_spent = self._client._get_hourly_spend()
                if hourly_spent + amount > config.max_spend_hourly:
                    raise SpendingLimitError(
                        requested=amount,
                        limit=config.max_spend_hourly - hourly_spent,
                        period="hourly",
                    )

            # Log the payment attempt
            payment_logger.log_payment_attempt(
                resource=url,
                amount=amount,
                challenge_nonce=challenge.nonce,
            )

            # DRY RUN MODE: Log but don't pay
            if config.dry_run:
                payment_logger.log_dry_run(resource=url, amount=amount)
                raise DryRunError(amount=amount, resource=url)

            # Request payment from Sidecar
            try:
                payment_result = await self._client._request_payment(challenge)
            except InsufficientBalanceError:
                payment_logger.log_payment_failure(
                    resource=url,
                    error="Insufficient balance",
                    error_code="INSUFFICIENT_BALANCE",
                )
                raise

            # Track spending
            self._client._record_spend(payment_result.amount_paid)

            # Log success
            payment_logger.log_payment_success(
                resource=url,
                amount=payment_result.amount_paid,
                remaining_balance=payment_result.remaining_balance,
            )

            # Add payment header and retry
            request_headers.update(build_payment_header(payment_result.auth_header))

            logger.debug(f"Retrying {method} {url} with payment (attempt {attempt})")

        # Max retries exceeded
        return response


# =============================================================================
# MAIN CLIENT
# =============================================================================


class DarkPoolClient:
    """
    The main Dark Pool client for privacy-preserving payments.

    This client wraps the Privacy Sidecar API and provides:
    - Automatic x402 payment handling
    - Spending limits and dry-run mode
    - Structured logging for auditing
    - Type-safe interfaces

    Usage:
        # Async context manager (recommended)
        async with DarkPoolClient() as client:
            balance = await client.wallet.get_balance()
            response = await client.http.get("https://api.example.com/data")

        # Manual lifecycle
        client = DarkPoolClient()
        await client.connect()
        try:
            # ... use client ...
        finally:
            await client.close()

    Configuration:
        Set via constructor or environment variables:
        - OBSCURATE_SIDECAR_URL: Sidecar URL
        - OBSCURATE_DRY_RUN: Enable dry-run mode
        - OBSCURATE_MAX_SPEND_TX: Max spend per transaction
    """

    def __init__(
        self,
        sidecar_url: str | None = None,
        *,
        encrypted_note: str | None = None,
        note_password: str | None = None,
        dry_run: bool | None = None,
        max_spend_per_tx: float | None = None,
        max_spend_hourly: float | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
    ) -> None:
        """
        Initialize the Dark Pool client.

        Args:
            sidecar_url: Privacy Sidecar URL (or use OBSCURATE_SIDECAR_URL).
            encrypted_note: Encrypted wallet note.
            note_password: Password to decrypt the note.
            dry_run: Enable dry-run mode (logs payments without executing).
            max_spend_per_tx: Maximum USDC per transaction (0 = no limit).
            max_spend_hourly: Maximum USDC per hour (0 = no limit).
            max_retries: Maximum payment retry attempts.
            timeout: Request timeout in seconds.
        """
        # Build configuration
        self._config = DarkPoolConfig()

        # Override from constructor
        if sidecar_url:
            self._config.sidecar_url = validate_sidecar_url(sidecar_url)
        if dry_run is not None:
            self._config.dry_run = dry_run
        if max_spend_per_tx is not None:
            self._config.max_spend_per_tx = max_spend_per_tx
        if max_spend_hourly is not None:
            self._config.max_spend_hourly = max_spend_hourly
        if max_retries is not None:
            self._config.max_retries = max_retries
        if timeout is not None:
            self._config.timeout = timeout

        # Set credentials
        self._config.encrypted_note = encrypted_note
        self._config.note_password = note_password

        # Internal state
        self._http_client: httpx.AsyncClient | None = None
        self._sidecar_client: httpx.AsyncClient | None = None
        self._payment_logger = PaymentLogger()
        self._spend_history: list[tuple[float, float]] = []  # (timestamp, amount)

        # Public interfaces
        self.wallet = WalletInterface(self)
        self.http = HTTPInterface(self)

    async def __aenter__(self) -> DarkPoolClient:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Async context manager exit."""
        await self.close()

    async def connect(self) -> None:
        """
        Initialize HTTP clients and verify sidecar connectivity.

        Raises:
            SidecarUnavailableError: If sidecar is unreachable.
        """
        if self._http_client is not None:
            return

        timeout = httpx.Timeout(
            timeout=self._config.timeout,
            connect=5.0,
            read=self._config.timeout,
            write=self._config.timeout,
            pool=5.0,
        )

        # External HTTP client
        self._http_client = httpx.AsyncClient(timeout=timeout)

        # Sidecar HTTP client
        self._sidecar_client = httpx.AsyncClient(
            base_url=self._config.sidecar_url,
            timeout=timeout,
        )

        # Verify sidecar connectivity
        try:
            health = await self.health()
            logger.info(
                f"Connected to Sidecar v{health.version} ({health.mode} mode, {health.status})"
            )
        except Exception as e:
            await self.close()
            raise SidecarUnavailableError(self._config.sidecar_url) from e

    async def close(self) -> None:
        """Close HTTP clients and cleanup resources."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        if self._sidecar_client:
            await self._sidecar_client.aclose()
            self._sidecar_client = None

    def load_credentials(self, encrypted_note: str, note_password: str) -> None:
        """
        Load wallet credentials.

        Call this before making payments if credentials weren't
        provided in the constructor.

        Args:
            encrypted_note: The encrypted note string.
            note_password: Password to decrypt the note.
        """
        self._config.encrypted_note = encrypted_note
        self._config.note_password = note_password

    def is_unlocked(self) -> bool:
        """Check if wallet credentials are loaded."""
        return bool(self._config.encrypted_note and self._config.note_password)

    async def health(self) -> SidecarHealth:
        """
        Check sidecar health status.

        Returns:
            SidecarHealth with status and version info.

        Raises:
            SidecarUnavailableError: If sidecar unreachable.
        """
        response = await self._sidecar_request("GET", "/health")
        return SidecarHealth.model_validate(response)

    def pay_protected(
        self,
        max_spend: float | None = None,
        _on_payment: Callable[[float, str], None] | None = None,  # Reserved for future use
    ) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
        """
        Decorator to protect a function with automatic payments.

        Any HTTP requests made within the decorated function will
        automatically handle 402 challenges up to the specified limit.

        Args:
            max_spend: Maximum USDC to spend in this function.
            on_payment: Optional callback when payment is made (amount, resource).

        Returns:
            Decorator function.

        Usage:
            @client.pay_protected(max_spend=5.0)
            async def fetch_premium_data():
                response = await client.http.get("https://api.data.com/premium")
                return response.json()
        """

        def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
            @functools.wraps(func)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                # Store original max spend
                original_max = self._config.max_spend_per_tx

                try:
                    # Apply the limit
                    if max_spend is not None:
                        self._config.max_spend_per_tx = max_spend

                    return await func(*args, **kwargs)
                finally:
                    # Restore original
                    self._config.max_spend_per_tx = original_max

            return wrapper

        return decorator

    # =========================================================================
    # INTERNAL METHODS
    # =========================================================================

    def _ensure_unlocked(self) -> None:
        """Ensure wallet is unlocked, raise if not."""
        if not self.is_unlocked():
            raise WalletLockedError()

    def _get_hourly_spend(self) -> float:
        """Get total spend in the last hour."""
        now = time.time()
        one_hour_ago = now - 3600

        # Clean old entries and sum recent
        self._spend_history = [
            (ts, amount) for ts, amount in self._spend_history if ts > one_hour_ago
        ]

        return sum(amount for _, amount in self._spend_history)

    def _record_spend(self, amount: float) -> None:
        """Record a spend for limit tracking."""
        self._spend_history.append((time.time(), amount))

    async def _sidecar_request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make a request to the sidecar API."""
        if not self._sidecar_client:
            raise ConfigurationError("Client not connected. Call connect() first.")

        try:
            response = await self._sidecar_client.request(method, path, **kwargs)

            if response.status_code >= 400:
                error_body = response.json() if response.content else {}
                error_info = error_body.get("error", {})

                raise PaymentGatewayError(
                    code=error_info.get("code", "UNKNOWN"),
                    message=error_info.get("message", f"Sidecar error: {response.status_code}"),
                    details=error_info,
                )

            return response.json()  # type: ignore[no-any-return]
        except httpx.RequestError as e:
            raise SidecarUnavailableError(self._config.sidecar_url) from e

    async def _request_payment(self, challenge: X402Challenge) -> PaymentResult:
        """
        Request payment authorization from the sidecar.

        This is where the ZK magic happens - we delegate proof
        generation to the sidecar.
        """
        self._ensure_unlocked()

        # Check balance first
        try:
            balance = await self.wallet.get_balance()
            if balance.total_usdc < challenge.amount_float:
                raise InsufficientBalanceError(
                    required=challenge.amount_float,
                    available=balance.total_usdc,
                )
        except InsufficientBalanceError:
            raise
        except Exception:
            # Continue - sidecar will validate
            pass

        try:
            response = await self._sidecar_request(
                "POST",
                "/api/pay/generate",
                json={
                    "encryptedNote": self._config.encrypted_note,
                    "notePassword": self._config.note_password,
                    "challenge": challenge.model_dump(by_alias=True),
                },
            )

            return PaymentResult.model_validate(response)

        except PaymentGatewayError as e:
            if e.code == "INSUFFICIENT_BALANCE":
                details = e.details or {}
                raise InsufficientBalanceError(
                    required=challenge.amount_float,
                    available=details.get("available", 0),
                ) from e
            if e.code == "NOTE_EXHAUSTED":
                raise NoteExhaustedError() from e
            if e.code == "PROOF_GENERATION_FAILED":
                raise ProofGenerationError(
                    phase=e.details.get("phase") if e.details else None,
                ) from e
            raise


# =============================================================================
# SYNCHRONOUS WRAPPER
# =============================================================================


class SyncDarkPoolClient:
    """
    Synchronous wrapper around DarkPoolClient.

    For agents that don't use async/await, this provides
    a blocking interface to the same functionality.

    Usage:
        with SyncDarkPoolClient() as client:
            balance = client.wallet.get_balance()
            response = client.http.get("https://api.example.com/data")
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the sync client (same args as DarkPoolClient)."""
        self._async_client = DarkPoolClient(*args, **kwargs)
        self._loop: asyncio.AbstractEventLoop | None = None

    def __enter__(self) -> SyncDarkPoolClient:
        """Sync context manager entry."""
        self._loop = asyncio.new_event_loop()
        self._loop.run_until_complete(self._async_client.connect())
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Sync context manager exit."""
        if self._loop:
            self._loop.run_until_complete(self._async_client.close())
            self._loop.close()
            self._loop = None

    def _run(self, coro: Awaitable[T]) -> T:
        """Run a coroutine synchronously."""
        if not self._loop:
            raise ConfigurationError("Client not connected. Use with statement.")
        return self._loop.run_until_complete(coro)

    @property
    def wallet(self) -> SyncWalletInterface:
        """Get the sync wallet interface."""
        return SyncWalletInterface(self)

    @property
    def http(self) -> SyncHTTPInterface:
        """Get the sync HTTP interface."""
        return SyncHTTPInterface(self)


class SyncWalletInterface:
    """Synchronous wallet interface."""

    def __init__(self, client: SyncDarkPoolClient) -> None:
        self._client = client

    def get_balance(self) -> WalletBalance:
        """Get wallet balance (blocking)."""
        return self._client._run(self._client._async_client.wallet.get_balance())

    def can_afford(self, amount: float) -> bool:
        """Check if payment can be afforded (blocking)."""
        return self._client._run(self._client._async_client.wallet.can_afford(amount))


class SyncHTTPInterface:
    """Synchronous HTTP interface."""

    def __init__(self, client: SyncDarkPoolClient) -> None:
        self._client = client

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make a GET request (blocking)."""
        return self._client._run(self._client._async_client.http.get(url, **kwargs))

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Make a POST request (blocking)."""
        return self._client._run(self._client._async_client.http.post(url, **kwargs))


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


@asynccontextmanager
async def create_client(
    encrypted_note: str | None = None,
    note_password: str | None = None,
    **kwargs: Any,
) -> AsyncIterator[DarkPoolClient]:
    """
    Convenience function to create a connected DarkPoolClient.

    Args:
        encrypted_note: Encrypted wallet note.
        note_password: Note decryption password.
        **kwargs: Additional DarkPoolClient arguments.

    Yields:
        Connected DarkPoolClient.

    Usage:
        async with create_client(note, password) as client:
            balance = await client.wallet.get_balance()
    """
    client = DarkPoolClient(
        encrypted_note=encrypted_note,
        note_password=note_password,
        **kwargs,
    )
    try:
        await client.connect()
        yield client
    finally:
        await client.close()
