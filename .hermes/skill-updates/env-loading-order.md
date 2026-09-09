# FastAPI .env Loading Order Pitfall

**Problem**: When `api.py` loads `.env` AFTER importing modules that read environment variables, those modules see default values instead of your configured settings.

## The Bug Pattern (WRONG)

```python
# BAD ORDER
import os
import sys
from datetime import datetime, timezone

# ... setup sys.path ...

# Load .env TOO LATE — after imports
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Now import modules that need env vars
import agent
import x402_payment  # ← reads X402_ENABLED at import time

# X402_ENABLED is still False because agent/x402 loaded before .env was read
```

**Symptom**: 
- `X402_ENABLED=false` even though `.env` has `X402_ENABLED=true`
- All payments fall back to `direct_api` instead of going on-chain
- No error — just silently uses defaults

## The Fix (CORRECT)

```python
# GOOD ORDER — dotenv FIRST
import os
import sys
from datetime import datetime, timezone

# Load .env BEFORE any other imports
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# NOW safe to import modules that read env vars
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import agent
import x402_payment  # ← sees X402_ENABLED from .env
```

## Verification

Add startup logging to confirm env vars are loaded:

```python
@app.on_event("startup")
def _startup_log() -> None:
    print(f"[api] X402_ENABLED={os.environ.get('X402_ENABLED', 'not set')}")
    print(f"[api] VENDOR_URL={os.environ.get('VENDOR_URL', 'not set')}")
```

Then check the logs:
```bash
curl http://localhost:8000/api/health  # Should trigger startup log
# Or watch: journalctl -u hagglemind-api -f
```

Expected output:
```
[api] X402_ENABLED=true
[api] VENDOR_URL=http://localhost:8777
```

If you see `X402_ENABLED=False` or `not set`, check import order.

## Why This Happens

Python executes imports at module load time. When `x402_payment.py` does:
```python
X402_ENABLED = os.environ.get("X402_ENABLED", "false").lower() == "true"
```

...this runs IMMEDIATELY when the module is first imported. If `.env` hasn't been loaded yet, `os.environ` still has the default `False`. Subsequent `load_dotenv()` calls won't retroactively fix already-captured values.

## Files That Read Env Vars at Import Time

Check your codebase for modules that do this:
- `x402_payment.py`: `X402_ENABLED`, `PRIVATE_KEY`, `BASE_RPC`
- `agent.py`: `VENDOR_URL`, `X402_ENABLED`
- `vendor_server.py`: `X402_ENABLED`, `X402_RECEIVER_ADDRESS`

All of these must be imported AFTER `load_dotenv()` runs.
