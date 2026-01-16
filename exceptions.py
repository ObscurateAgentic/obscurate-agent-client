"""
Obscurate Client - Exception Classes

Strict, typed exceptions that provide clear error messages
for agent developers using the Dark Pool infrastructure.

These exceptions allow agents to make informed decisions
about retry logic and graceful degradation.
"""

from typing import Any


class ObscurateError(Exception):
    """Base exception for all Obscurate-related errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """
        Initialize the exception.

        Args:
            message: Human-readable error description.
            details: Optional structured details for debugging.
        """
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.message!r}, details={self.details})"


# =============================================================================
# WALLET & BALANCE ERRORS
# =============================================================================


class WalletError(ObscurateError):
    """Base class for wallet-related errors."""

    pass


class WalletLockedError(WalletError):
    """
    Raised when the wallet is locked and cannot perform operations.

    This typically means the encrypted note has not been loaded
    or the password is incorrect.
    """

    def __init__(
        self,
        message: str = "Wallet is locked. Load credentials before operations.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details)


class InsufficientBalanceError(WalletError):
    """
    Raised when a payment cannot be made due to insufficient funds.

    This allows agents to gracefully decline tasks that exceed
    their current balance without hard failures.
    """

    def __init__(
        self,
        required: float,
        available: float,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize with balance information.

        Args:
            required: Amount required for the operation (USDC).
            available: Currently available balance (USDC).
            message: Optional custom message.
            details: Optional additional details.
        """
        self.required = required
        self.available = available
        default_msg = f"Insufficient balance: need {required:.2f} USDC, have {available:.2f} USDC"
        super().__init__(message or default_msg, details)


class NoteExhaustedError(WalletError):
    """
    Raised when all available notes have been spent.

    The agent should either:
    1. Wait for pending deposits to confirm
    2. Request a top-up
    3. Decline incoming tasks
    """

    def __init__(
        self,
        message: str = "All privacy notes exhausted. Deposit required.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details)


# =============================================================================
# PRIVACY & ANONYMITY ERRORS
# =============================================================================


class PrivacyError(ObscurateError):
    """Base class for privacy-related errors."""

    pass


class InsufficientAnonymityError(PrivacyError):
    """
    Raised when an operation would compromise privacy guarantees.

    Examples:
    - Trying to spend a note that would deanonymize the agent
    - Attempting a payment that exceeds the anonymity set size
    - Connecting to a known tracking endpoint
    """

    def __init__(
        self,
        message: str = "Operation would compromise anonymity set.",
        anonymity_set_size: int | None = None,
        min_required: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize with anonymity metrics.

        Args:
            message: Description of the privacy concern.
            anonymity_set_size: Current anonymity set size.
            min_required: Minimum required anonymity set.
            details: Optional additional details.
        """
        self.anonymity_set_size = anonymity_set_size
        self.min_required = min_required
        full_details = details or {}
        if anonymity_set_size is not None:
            full_details["anonymity_set_size"] = anonymity_set_size
        if min_required is not None:
            full_details["min_required"] = min_required
        super().__init__(message, full_details)


class ProofGenerationError(PrivacyError):
    """
    Raised when ZK proof generation fails.

    This can occur due to:
    - Circuit compilation errors
    - Invalid witness data
    - Timeout during heavy computation
    """

    def __init__(
        self,
        message: str = "Failed to generate zero-knowledge proof.",
        phase: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize with proof generation context.

        Args:
            message: Description of the failure.
            phase: Which phase failed (compile, witness, prove, verify).
            details: Optional additional details.
        """
        self.phase = phase
        full_details = details or {}
        if phase:
            full_details["phase"] = phase
        super().__init__(message, full_details)


# =============================================================================
# NETWORK & SIDECAR ERRORS
# =============================================================================


class NetworkError(ObscurateError):
    """Base class for network-related errors."""

    pass


class SidecarUnavailableError(NetworkError):
    """
    Raised when the Privacy Sidecar cannot be reached.

    The agent should:
    1. Retry with exponential backoff
    2. Check sidecar health endpoint
    3. Fall back to non-private mode (if acceptable)
    """

    def __init__(
        self,
        url: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize with sidecar connection info.

        Args:
            url: The sidecar URL that was unreachable.
            message: Optional custom message.
            details: Optional additional details.
        """
        self.url = url
        default_msg = f"Privacy Sidecar unavailable at {url}"
        full_details = details or {}
        full_details["sidecar_url"] = url
        super().__init__(message or default_msg, full_details)


class PaymentGatewayError(NetworkError):
    """
    Raised when the x402 payment gateway rejects the payment.

    Possible causes:
    - Invalid proof format
    - Expired challenge
    - Facilitator rejection
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize with gateway error details.

        Args:
            code: Error code from the gateway.
            message: Error message from the gateway.
            details: Optional additional details.
        """
        self.code = code
        full_details = details or {}
        full_details["gateway_code"] = code
        super().__init__(message, full_details)


class ChallengeExpiredError(NetworkError):
    """
    Raised when an x402 payment challenge has expired.

    The agent should request a fresh challenge from the resource.
    """

    def __init__(
        self,
        resource: str,
        expired_at: int,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize with challenge expiry info.

        Args:
            resource: The resource URL that issued the challenge.
            expired_at: Unix timestamp when the challenge expired.
            message: Optional custom message.
            details: Optional additional details.
        """
        self.resource = resource
        self.expired_at = expired_at
        default_msg = f"Payment challenge expired for {resource}"
        full_details = details or {}
        full_details["resource"] = resource
        full_details["expired_at"] = expired_at
        super().__init__(message or default_msg, full_details)


# =============================================================================
# CONFIGURATION ERRORS
# =============================================================================


class ConfigurationError(ObscurateError):
    """
    Raised when the client is misconfigured.

    Check environment variables and initialization parameters.
    """

    def __init__(
        self,
        message: str,
        config_key: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize with configuration context.

        Args:
            message: Description of the configuration issue.
            config_key: The problematic configuration key.
            details: Optional additional details.
        """
        self.config_key = config_key
        full_details = details or {}
        if config_key:
            full_details["config_key"] = config_key
        super().__init__(message, full_details)


class DryRunError(ObscurateError):
    """
    Raised during dry-run mode to indicate a payment would have occurred.

    This is NOT an error in the traditional sense - it's used for
    testing and debugging payment flows without spending real funds.
    """

    def __init__(
        self,
        amount: float,
        resource: str,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize with simulated payment details.

        Args:
            amount: Amount that would have been paid (USDC).
            resource: Resource that would have been accessed.
            message: Optional custom message.
            details: Optional additional details.
        """
        self.amount = amount
        self.resource = resource
        default_msg = f"[DRY RUN] Would pay {amount:.4f} USDC for {resource}"
        full_details = details or {}
        full_details["simulated_amount"] = amount
        full_details["resource"] = resource
        super().__init__(message or default_msg, full_details)


# =============================================================================
# SPENDING LIMIT ERRORS
# =============================================================================


class SpendingLimitError(ObscurateError):
    """
    Raised when a payment would exceed configured spending limits.

    This protects agents from runaway costs during autonomous operation.
    """

    def __init__(
        self,
        requested: float,
        limit: float,
        period: str = "transaction",
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize with spending limit context.

        Args:
            requested: Amount requested for this operation (USDC).
            limit: The configured limit (USDC).
            period: The limit period (transaction, hourly, daily).
            message: Optional custom message.
            details: Optional additional details.
        """
        self.requested = requested
        self.limit = limit
        self.period = period
        default_msg = (
            f"Spending limit exceeded: {requested:.2f} USDC requested, "
            f"{limit:.2f} USDC {period} limit"
        )
        full_details = details or {}
        full_details["requested"] = requested
        full_details["limit"] = limit
        full_details["period"] = period
        super().__init__(message or default_msg, full_details)
