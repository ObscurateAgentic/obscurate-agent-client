"""
Obscurate Client - Utility Functions

Helper functions for:
- x402 header parsing
- Challenge extraction
- Response validation
- Logging utilities
"""

import base64
import json
import logging
import re
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("obscurate")


# =============================================================================
# DATA MODELS
# =============================================================================


class X402Challenge(BaseModel):
    """
    Represents an x402 payment challenge.

    This is the standard format returned by services that require
    payment via the HTTP 402 protocol.
    """

    version: str = Field(default="1")
    scheme: str = Field(description="Payment scheme (exact, upto)")
    network: str = Field(description="Blockchain network")
    max_amount_required: str = Field(
        alias="maxAmountRequired", description="Maximum payment amount"
    )
    resource: str = Field(description="Resource URL being accessed")
    description: str | None = Field(default=None, description="Human-readable description")
    facilitator: str | None = Field(default=None, description="Payment facilitator address")
    facilitator_data: str | None = Field(
        default=None, alias="facilitatorData", description="Opaque facilitator data"
    )
    nonce: str = Field(description="Unique challenge nonce")
    expiry: int = Field(description="Unix timestamp when challenge expires")

    model_config = ConfigDict(populate_by_name=True)

    @property
    def amount_float(self) -> float:
        """Get the max amount as a float."""
        return float(self.max_amount_required)

    def is_expired(self) -> bool:
        """Check if this challenge has expired."""
        return time.time() > self.expiry

    @classmethod
    def from_header(cls, header_value: str) -> "X402Challenge":
        """
        Parse an x402 challenge from a WWW-Authenticate or x402-Challenge header.

        Args:
            header_value: The raw header value (may be base64 encoded).

        Returns:
            Parsed X402Challenge object.

        Raises:
            ValueError: If the header cannot be parsed.
        """
        # Try to extract x402 scheme prefix
        if header_value.startswith("x402 "):
            header_value = header_value[5:]

        # Try base64 decode first
        try:
            decoded = base64.b64decode(header_value).decode("utf-8")
            data = json.loads(decoded)
            return cls.model_validate(data)
        except Exception:
            pass

        # Try direct JSON
        try:
            data = json.loads(header_value)
            return cls.model_validate(data)
        except Exception as e:
            raise ValueError(f"Cannot parse x402 challenge: {e}") from e

    @classmethod
    def from_response_body(cls, body: dict[str, Any] | list[Any]) -> "X402Challenge":
        """
        Parse an x402 challenge from a response body.

        Args:
            body: The parsed JSON response body.

        Returns:
            Parsed X402Challenge object.

        Raises:
            ValueError: If the body cannot be parsed.
        """
        # Handle array format (some gateways return [challenge])
        if isinstance(body, list) and len(body) > 0:
            body = body[0]

        # Handle nested format
        if isinstance(body, dict):
            if "x402" in body:
                body = body["x402"]
            if isinstance(body, dict) and "accepts" in body and isinstance(body["accepts"], list):
                body = body["accepts"][0]

        if not isinstance(body, dict):
            raise ValueError(f"Expected dict, got {type(body)}")

        return cls.model_validate(body)


class PaymentResult(BaseModel):
    """Result of a successful payment operation."""

    auth_header: str = Field(alias="authHeader", description="X-PAYMENT header value")
    amount_paid: float = Field(alias="amountPaid", description="Actual amount paid (USDC)")
    remaining_balance: float = Field(
        alias="remainingBalance", description="Balance after payment"
    )
    nullifier_hash: str | None = Field(
        default=None, alias="nullifierHash", description="Nullifier of spent note"
    )
    proof_id: str | None = Field(default=None, alias="proofId", description="ZK proof identifier")

    model_config = ConfigDict(populate_by_name=True)


class WalletBalance(BaseModel):
    """Wallet balance information."""

    total_usdc: float = Field(alias="totalUsdc", description="Total balance in USDC")
    note_count: int = Field(alias="noteCount", description="Number of available notes")
    largest_note: float = Field(alias="largestNote", description="Largest single note value")
    smallest_note: float = Field(alias="smallestNote", description="Smallest single note value")
    chain: str = Field(description="Active blockchain")

    model_config = ConfigDict(populate_by_name=True)


class SidecarHealth(BaseModel):
    """Sidecar health status."""

    status: str = Field(description="Health status (healthy, degraded, unhealthy)")
    version: str = Field(description="Sidecar version")
    uptime: int = Field(description="Uptime in seconds")
    mode: str = Field(description="Operation mode (mock, real)")
    chains: list[dict[str, Any]] = Field(description="Chain connectivity status")

    model_config = ConfigDict(populate_by_name=True)


# =============================================================================
# HEADER PARSING UTILITIES
# =============================================================================


def extract_challenge_from_response(
    status_code: int,
    headers: dict[str, str],
    body: bytes | str | dict[str, Any] | None = None,
) -> X402Challenge | None:
    """
    Extract an x402 challenge from an HTTP response.

    Checks multiple locations in priority order:
    1. WWW-Authenticate header
    2. x402-Challenge header
    3. Response body

    Args:
        status_code: HTTP status code (should be 402).
        headers: Response headers (case-insensitive dict).
        body: Optional response body.

    Returns:
        Parsed X402Challenge if found, None otherwise.
    """
    if status_code != 402:
        return None

    # Normalize headers to lowercase
    norm_headers = {k.lower(): v for k, v in headers.items()}

    # Try WWW-Authenticate header
    if "www-authenticate" in norm_headers:
        try:
            return X402Challenge.from_header(norm_headers["www-authenticate"])
        except ValueError:
            pass

    # Try x402-Challenge header
    if "x402-challenge" in norm_headers:
        try:
            return X402Challenge.from_header(norm_headers["x402-challenge"])
        except ValueError:
            pass

    # Try response body
    if body:
        try:
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            if isinstance(body, str):
                body = json.loads(body)
            return X402Challenge.from_response_body(body)  # type: ignore[arg-type]
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def build_payment_header(auth_header: str) -> dict[str, str]:
    """
    Build HTTP headers including the payment authorization.

    Args:
        auth_header: The X-PAYMENT header value from the sidecar.

    Returns:
        Dict with the X-PAYMENT header.
    """
    return {"X-PAYMENT": auth_header}


def parse_payment_requirements(header: str) -> dict[str, Any]:
    """
    Parse x402 payment requirements from a header.

    Args:
        header: Raw header value.

    Returns:
        Dict with parsed payment requirements.
    """
    result: dict[str, Any] = {}

    # Parse key=value pairs
    pairs = re.findall(r'(\w+)="?([^",\s]+)"?', header)
    for key, value in pairs:
        # Convert numeric values
        if value.isdigit():
            result[key] = int(value)
        elif value.replace(".", "", 1).isdigit():
            result[key] = float(value)
        else:
            result[key] = value

    return result


# =============================================================================
# LOGGING UTILITIES
# =============================================================================


class PaymentLogger:
    """
    Structured logger for payment operations.

    Logs all payment activities in a format suitable for
    auditing and debugging while redacting sensitive data.
    """

    def __init__(self, logger_name: str = "obscurate.payments") -> None:
        """
        Initialize the payment logger.

        Args:
            logger_name: Name for the logger instance.
        """
        self.logger = logging.getLogger(logger_name)

    def log_payment_attempt(
        self,
        resource: str,
        amount: float,
        challenge_nonce: str | None = None,
    ) -> None:
        """Log a payment attempt."""
        self.logger.info(
            "Payment attempt",
            extra={
                "event": "payment_attempt",
                "resource": self._redact_url(resource),
                "amount_usdc": amount,
                "challenge_nonce": challenge_nonce[:8] + "..." if challenge_nonce else None,
            },
        )

    def log_payment_success(
        self,
        resource: str,
        amount: float,
        remaining_balance: float,
    ) -> None:
        """Log a successful payment."""
        self.logger.info(
            "Payment successful",
            extra={
                "event": "payment_success",
                "resource": self._redact_url(resource),
                "amount_usdc": amount,
                "remaining_balance": remaining_balance,
            },
        )

    def log_payment_failure(
        self,
        resource: str,
        error: str,
        error_code: str | None = None,
    ) -> None:
        """Log a payment failure."""
        self.logger.warning(
            "Payment failed",
            extra={
                "event": "payment_failure",
                "resource": self._redact_url(resource),
                "error": error,
                "error_code": error_code,
            },
        )

    def log_dry_run(
        self,
        resource: str,
        amount: float,
    ) -> None:
        """Log a dry-run payment."""
        self.logger.info(
            "[DRY RUN] Simulated payment",
            extra={
                "event": "payment_dry_run",
                "resource": self._redact_url(resource),
                "simulated_amount_usdc": amount,
            },
        )

    @staticmethod
    def _redact_url(url: str) -> str:
        """Redact sensitive parts of URLs for logging."""
        # Remove query parameters that might contain secrets
        if "?" in url:
            base, _ = url.split("?", 1)
            return f"{base}?[REDACTED]"
        return url


# =============================================================================
# VALIDATION UTILITIES
# =============================================================================


def validate_usdc_amount(amount: float, max_amount: float | None = None) -> None:
    """
    Validate a USDC amount.

    Args:
        amount: Amount to validate.
        max_amount: Optional maximum allowed amount.

    Raises:
        ValueError: If amount is invalid.
    """
    if amount < 0:
        raise ValueError(f"Amount cannot be negative: {amount}")

    if amount == 0:
        raise ValueError("Amount cannot be zero")

    # USDC has 6 decimals
    if amount < 0.000001:
        raise ValueError(f"Amount below minimum precision (6 decimals): {amount}")

    if max_amount is not None and amount > max_amount:
        raise ValueError(f"Amount {amount} exceeds maximum {max_amount}")


def validate_sidecar_url(url: str) -> str:
    """
    Validate and normalize a sidecar URL.

    Args:
        url: The sidecar URL to validate.

    Returns:
        Normalized URL.

    Raises:
        ValueError: If URL is invalid.
    """
    if not url:
        raise ValueError("Sidecar URL cannot be empty")

    # Remove trailing slash
    url = url.rstrip("/")

    # Validate scheme
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL scheme: {url}")

    return url
