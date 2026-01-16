# 🌑 Obscurate Client

**Privacy-First Python SDK for AI Agents**

Give your autonomous agents "Dark Pool" capabilities with automatic x402 payment handling and zero-knowledge proof generation.

[![PyPI version](https://badge.fury.io/py/obscurate-client.svg)](https://pypi.org/project/obscurate-client/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

---

## 🚀 Quick Start

```bash
pip install obscurate-client
```

```python
from obscurate import DarkPoolClient

async with DarkPoolClient() as client:
    # Load your encrypted wallet note
    client.load_credentials(encrypted_note, password)
    
    # Check balance
    balance = await client.wallet.get_balance()
    print(f"💰 Balance: {balance.total_usdc} USDC")
    
    # Make a request - payments are handled automatically!
    response = await client.http.get("https://api.expensive-data.com/premium")
    print(response.json())
```

**That's it.** If the endpoint returns `402 Payment Required`, the client automatically:
1. Extracts the payment challenge
2. Generates a zero-knowledge proof via the Privacy Sidecar
3. Retries the request with the payment authorization

---

## 🎯 Features

### ✅ Automatic x402 Payment Handling
```python
# No manual 402 handling needed
response = await client.http.get("https://api.data.com/premium")
# If payment required → handled silently
```

### ✅ Spending Limits
```python
# Protect against runaway costs
client = DarkPoolClient(
    max_spend_per_tx=5.0,    # Max $5 per transaction
    max_spend_hourly=100.0,   # Max $100 per hour
)
```

### ✅ Dry-Run Mode
```python
# Test your agent without spending real money
client = DarkPoolClient(dry_run=True)

# This will log the payment but not execute it
response = await client.http.get("https://api.data.com/premium")
# Raises DryRunError with payment details
```

### ✅ Pay-Protected Decorators
```python
@client.pay_protected(max_spend=10.0)
async def fetch_alpha_dataset():
    """Buy premium dataset with spending limit."""
    response = await client.http.get("https://api.data.com/alpha")
    return response.json()
```

### ✅ Sync and Async Support
```python
# Async (recommended)
async with DarkPoolClient() as client:
    balance = await client.wallet.get_balance()

# Sync (for legacy code)
with SyncDarkPoolClient() as client:
    balance = client.wallet.get_balance()
```

---

## 📖 Real-World Example: Buy a Dataset

```python
import asyncio
from obscurate import DarkPoolClient, InsufficientBalanceError

async def buy_dataset():
    """
    Example: An AI agent buying a premium dataset anonymously.
    
    The agent:
    1. Checks if it can afford the dataset
    2. Makes the purchase with automatic x402 handling
    3. Returns the data to train on
    """
    async with DarkPoolClient(
        sidecar_url="http://localhost:3000",
        max_spend_per_tx=50.0,  # Cap at $50
    ) as client:
        # Load wallet from secure storage
        encrypted_note = get_from_vault("AGENT_NOTE")
        password = get_from_vault("AGENT_PASSWORD")
        client.load_credentials(encrypted_note, password)
        
        # Check balance before attempting purchase
        balance = await client.wallet.get_balance()
        print(f"💰 Available: {balance.total_usdc} USDC")
        
        if balance.total_usdc < 10.0:
            print("⚠️ Low balance, requesting top-up...")
            return None
        
        try:
            # Purchase the dataset - payment handled automatically
            response = await client.http.post(
                "https://api.datamarket.ai/v1/datasets/premium-crypto-trades",
                json={
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                    "format": "parquet",
                },
            )
            
            dataset_url = response.json()["download_url"]
            print(f"✅ Dataset purchased: {dataset_url}")
            return dataset_url
            
        except InsufficientBalanceError as e:
            print(f"❌ Cannot afford: need {e.required}, have {e.available}")
            return None

asyncio.run(buy_dataset())
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OBSCURATE_SIDECAR_URL` | Privacy Sidecar URL | `http://localhost:3000` |
| `OBSCURATE_DRY_RUN` | Enable dry-run mode | `false` |
| `OBSCURATE_MAX_SPEND_TX` | Max USDC per transaction | `0` (no limit) |
| `OBSCURATE_MAX_SPEND_HOURLY` | Max USDC per hour | `0` (no limit) |
| `OBSCURATE_MAX_RETRIES` | Payment retry attempts | `3` |
| `OBSCURATE_TIMEOUT` | Request timeout (seconds) | `30` |

### Constructor Arguments

```python
client = DarkPoolClient(
    sidecar_url="http://sidecar:3000",
    encrypted_note="...",           # Your encrypted note
    note_password="...",            # Note decryption password
    dry_run=False,                  # Enable dry-run mode
    max_spend_per_tx=10.0,          # Max per transaction
    max_spend_hourly=100.0,         # Max per hour
    max_retries=3,                  # Payment retries
    timeout=30.0,                   # Request timeout
)
```

---

## 🛡️ Error Handling

The SDK provides typed exceptions for clean error handling:

```python
from obscurate import (
    DarkPoolClient,
    InsufficientBalanceError,
    SpendingLimitError,
    ProofGenerationError,
    SidecarUnavailableError,
)

async with DarkPoolClient() as client:
    try:
        response = await client.http.get("https://api.data.com/premium")
        
    except InsufficientBalanceError as e:
        # Not enough funds
        print(f"Need {e.required} USDC, have {e.available} USDC")
        # → Request deposit or decline task
        
    except SpendingLimitError as e:
        # Would exceed configured limits
        print(f"Limit exceeded: {e.requested} > {e.limit} ({e.period})")
        # → Wait or increase limits
        
    except ProofGenerationError as e:
        # ZK proof generation failed
        print(f"Proof failed at phase: {e.phase}")
        # → Retry or fall back
        
    except SidecarUnavailableError as e:
        # Sidecar is down
        print(f"Sidecar unreachable: {e.url}")
        # → Retry with backoff
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     YOUR AI AGENT                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              obscurate-client (this SDK)                │   │
│  │  • Automatic 402 detection                              │   │
│  │  • Spending limits                                      │   │
│  │  • Dry-run mode                                         │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Privacy Sidecar (TypeScript)               │   │
│  │  • ZK proof generation                                  │   │
│  │  • Note management                                      │   │
│  │  • Transaction signing                                  │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

The agent **never** handles private keys or signs transactions directly.
All cryptographic operations are delegated to the Privacy Sidecar.

---

## 🧪 Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy obscurate_client/

# Linting
ruff check obscurate_client/
```

---

## 📜 License

MIT License - see [LICENSE](LICENSE) for details.

---

## 🔗 Links

- **Twitter**: [@ObscurateAgent](https://x.com/ObscurateAgent)

---

<p align="center">
  <sub>Built with 🖤 by the Obscurate team</sub>
</p>

