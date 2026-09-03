"""
Mock Vendor API — simulates bill vendors (Comcast, Netflix, etc.) with hidden negotiation rules.

Run: python vendor_server.py

The vendor has hidden rules that determine whether a negotiation tactic succeeds.
The agent does NOT know these rules — it learns them through trial and error,
stored in memory.json as confidence scores.

Hidden rules can be changed via the /chaos endpoint (called by the Time-Machine CLI).
"""

import json
import random
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests
import base64

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PORT = 8777
VENDOR_SERVER_URL = f"http://localhost:{PORT}"

# x402 config — enable x402 payment-gating on the /pay-x402 endpoint
X402_ENABLED = False  # Set True when you have the x402 SDK + a facilitator
X402_FACILITATOR_URL = "https://x402.org/facilitator"
X402_RECEIVER_ADDRESS = "0xYourBaseSepoliaAddressHere"  # Set to your wallet

# Default hidden rules per vendor. The agent NEVER sees these — it only sees
# the accept/reject response and must infer what works from memory.json.
DEFAULT_RULES = {
    "Comcast": {
        "competitor_promo": {"accept_prob": 0.85, "discount": 0.40, "label": "Competitor promo works well"},
        "loyalty_discount": {"accept_prob": 0.55, "discount": 0.15, "label": "Loyalty discount sometimes works"},
        "budget_hardship": {"accept_prob": 0.25, "discount": 0.10, "label": "Budget hardship rarely works"},
    },
    "Netflix": {
        "competitor_promo": {"accept_prob": 0.70, "discount": 0.30, "label": "Competitor promo works"},
        "loyalty_discount": {"accept_prob": 0.45, "discount": 0.10, "label": "Loyalty discount sometimes works"},
    },
    "Spotify": {
        "competitor_promo": {"accept_prob": 0.40, "discount": 0.20, "label": "Competitor promo rarely works"},
        "loyalty_discount": {"accept_prob": 0.75, "discount": 0.25, "label": "Loyalty discount works well"},
    },
    "DisneyPlus": {
        "competitor_promo": {"accept_prob": 0.60, "discount": 0.25, "label": "Competitor promo sometimes works"},
        "budget_hardship": {"accept_prob": 0.50, "discount": 0.15, "label": "Budget hardship sometimes works"},
    },
}

# In-memory state
vendor_rules = {}
pending_invoices = {}  # vendor -> {"amount": float, "paid": bool, "negotiated_amount": float|None, "negotiation_history": []}
vendor_tactic_stats = {}  # vendor -> tactic -> {"called": int, "accepted": int}

# Load rules from file if it exists, else use defaults
RULES_FILE = "vendor_rules.json"


def load_rules():
    global vendor_rules
    try:
        with open(RULES_FILE, "r") as f:
            vendor_rules = json.load(f)
        print(f"[vendor] Loaded rules from {RULES_FILE}")
    except FileNotFoundError:
        vendor_rules = json.loads(json.dumps(DEFAULT_RULES))  # deep copy
        print("[vendor] No rules file found, using defaults")


def save_rules():
    with open(RULES_FILE, "w") as f:
        json.dump(vendor_rules, f, indent=2)
    print(f"[vendor] Saved rules to {RULES_FILE}")


def reset_rules():
    global vendor_rules
    vendor_rules = json.loads(json.dumps(DEFAULT_RULES))
    # Also write to disk so persistence works across restarts
    with open(RULES_FILE, "w") as f:
        json.dump(vendor_rules, f, indent=2)
    print("[vendor] Rules reset to defaults")


# ---------------------------------------------------------------------------
# Vendor logic
# ---------------------------------------------------------------------------

def ensure_vendor(vendor: str):
    """Ensure a vendor has rules and invoice state initialized."""
    if vendor not in vendor_rules:
        # Copy default rule patterns from closest match or use generic
        vendor_rules[vendor] = {
            "competitor_promo": {"accept_prob": 0.50, "discount": 0.25, "label": "Generic competitor promo"},
            "loyalty_discount": {"accept_prob": 0.40, "discount": 0.10, "label": "Generic loyalty discount"},
            "budget_hardship": {"accept_prob": 0.30, "discount": 0.08, "label": "Generic budget hardship"},
        }
    if vendor not in pending_invoices:
        pending_invoices[vendor] = {
            "amount": 0,
            "paid": False,
            "negotiated_amount": None,
            "negotiation_history": [],
        }
    if vendor not in vendor_tactic_stats:
        vendor_tactic_stats[vendor] = {}


def negotiate(vendor: str, tactic: str, amount: float, agent_note: str = "") -> dict:
    """
    Simulate a negotiation attempt.
    Returns {"accepted": bool, "final_amount": float, "reason": str, "vendor_response": str}
    """
    ensure_vendor(vendor)

    if vendor not in vendor_rules or tactic not in vendor_rules[vendor]:
        return {
            "accepted": False,
            "final_amount": amount,
            "reason": f"Unknown tactic '{tactic}' for vendor '{vendor}'",
            "vendor_response": "We don't have a program for that.",
        }

    rule = vendor_rules[vendor][tactic]
    accept_prob = rule["accept_prob"]
    discount = rule["discount"]

    # Track stats
    if vendor not in vendor_tactic_stats:
        vendor_tactic_stats[vendor] = {}
    if tactic not in vendor_tactic_stats[vendor]:
        vendor_tactic_stats[vendor][tactic] = {"called": 0, "accepted": 0}
    vendor_tactic_stats[vendor][tactic]["called"] += 1

    # Random roll to determine if vendor accepts
    roll = random.random()
    accepted = roll < accept_prob

    # Vendor response text varies by tactic
    responses = {
        "competitor_promo": [
            "I can offer you a retention deal. We value your business.",
            "I see you've been with us a while. Let me see what I can do.",
            "I understand you have options. Let me check on available offers.",
            "We'd hate to lose you. Let me review your account.",
        ],
        "loyalty_discount": [
            "As a loyal customer, I can apply a courtesy discount.",
            "Thank you for your continued loyalty. Let me look into this.",
            "We appreciate long-term customers. Let me check available programs.",
        ],
        "budget_hardship": [
            "I'm sorry to hear that. Let me see if there are any assistance options.",
            "I understand. Let me check what programs might help.",
            "Unfortunately our options are limited, but let me review your account.",
        ],
    }

    vendor_responses = responses.get(tactic, ["Let me review your account."])

    if accepted:
        final_amount = round(amount * (1 - discount), 2)
        reason = f"{rule['label']} — accepted (roll: {roll:.2f} < {accept_prob})"
        vendor_response = random.choice(vendor_responses)
        vendor_tactic_stats[vendor][tactic]["accepted"] += 1
    else:
        final_amount = amount
        reason = f"{rule['label']} — rejected (roll: {roll:.2f} >= {accept_prob})"
        vendor_response = random.choice([
            "I'm sorry, I'm not able to offer a discount at this time.",
            "We don't have any promotions available for your account.",
            "I've reviewed your account and I'm unable to lower the rate.",
            "There are no current offers that apply to your service.",
        ])

    # Record negotiation history
    pending_invoices[vendor]["negotiation_history"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tactic": tactic,
        "requested_amount": amount,
        "accepted": accepted,
        "final_amount": final_amount,
        "vendor_response": vendor_response,
    })

    return {
        "accepted": accepted,
        "final_amount": final_amount,
        "reason": reason,
        "vendor_response": vendor_response,
    }


def pay_invoice(vendor: str, amount: float) -> dict:
    """Simulate paying an invoice."""
    ensure_vendor(vendor)
    pending_invoices[vendor]["paid"] = True
    pending_invoices[vendor]["negotiated_amount"] = amount
    return {
        "paid": True,
        "amount": amount,
        "vendor": vendor,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class VendorHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Quiet by default — the CLI handles output
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self._send_json({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})

        elif parsed.path == "/invoice":
            vendor = parsed.query.split("vendor=")[-1] if "vendor=" in parsed.query else None
            if vendor and vendor in pending_invoices:
                inv = pending_invoices[vendor]
                self._send_json({
                    "vendor": vendor,
                    "amount": inv["amount"],
                    "paid": inv["paid"],
                    "negotiated_amount": inv["negotiated_amount"],
                    "has_invoice": inv["amount"] > 0,
                })
            else:
                self._send_json({"error": "No invoice found", "vendor": vendor}, 404)

        elif parsed.path == "/rules":
            # Debug endpoint — NOT used by the agent. For the human to inspect.
            self._send_json(vendor_rules)

        elif parsed.path == "/stats":
            self._send_json(vendor_tactic_stats)

        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}

        if parsed.path == "/inject_invoice":
            vendor = data.get("vendor", "")
            amount = float(data.get("amount", 0))
            ensure_vendor(vendor)
            pending_invoices[vendor] = {
                "amount": amount,
                "paid": False,
                "negotiated_amount": None,
                "negotiation_history": [],
            }
            self._send_json({
                "status": "injected",
                "vendor": vendor,
                "amount": amount,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        elif parsed.path == "/negotiate":
            vendor = data.get("vendor", "")
            tactic = data.get("tactic", "")
            amount = float(data.get("amount", 0))
            agent_note = data.get("note", "")
            result = negotiate(vendor, tactic, amount, agent_note)
            self._send_json(result)

        elif parsed.path == "/pay":
            vendor = data.get("vendor", "")
            amount = float(data.get("amount", 0))
            result = pay_invoice(vendor, amount)
            self._send_json(result)

        elif parsed.path == "/pay-x402":
            # x402 payment-gated endpoint — simulates the 402 flow
            self._handle_x402_pay(data)

        elif parsed.path == "/chaos":
            vendor = data.get("vendor", "")
            if vendor and vendor in vendor_rules:
                tactics = list(vendor_rules[vendor].keys())
                tactic = random.choice(tactics)
                old_prob = vendor_rules[vendor][tactic]["accept_prob"]
                new_prob = round(random.uniform(0.05, 0.30), 2)  # Force failure range
                vendor_rules[vendor][tactic]["accept_prob"] = new_prob
                save_rules()  # persist mutated rules to disk
                self._send_json({
                    "status": "chaos_applied",
                    "vendor": vendor,
                    "tactic": tactic,
                    "old_accept_prob": old_prob,
                    "new_accept_prob": new_prob,
                    "label": vendor_rules[vendor][tactic]["label"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            else:
                self._send_json({"error": f"Unknown vendor: {vendor}"}, 404)

        elif parsed.path == "/reset_rules":
            reset_rules()
            self._send_json({"status": "reset"})

        else:
            self._send_json({"error": "Not found"}, 404)

    def _handle_x402_pay(self, data: dict):
        """Handle x402 payment-gated request on /pay-x402.

        If the request has no PAYMENT-SIGNATURE header, return 402 with
        PAYMENT-REQUIRED header containing payment specs.
        If the request has a valid signature, accept the payment.
        """
        vendor = data.get("vendor", "")
        amount_usd = float(data.get("amount_usd", 0))

        # Check for payment signature
        sig_header = self.headers.get("PAYMENT-SIGNATURE") or self.headers.get("payment-signature")

        if not sig_header:
            # Return 402 Payment Required
            import base64
            from datetime import datetime, timezone

            # Build PaymentRequired V2
            payment_required = {
                "x402_version": 2,
                "accepts": [
                    {
                        "network": "eip155:84532",  # Base Sepolia
                        "price": {
                            "amount": str(amount_usd),
                            "asset": "usdc",
                            "decimals": 6,
                        },
                        "payTo": X402_RECEIVER_ADDRESS,
                        "scheme": "exact",
                    }
                ],
                "resource": {
                    "path": "/pay-x402",
                    "method": "POST",
                },
                "extensions": {},
            }

            pr_b64 = base64.b64encode(json.dumps(payment_required).encode()).decode()

            self.send_response(402)
            self.send_header("Content-Type", "application/json")
            self.send_header("PAYMENT-REQUIRED", pr_b64)
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": "Payment required",
                "amount_usd": amount_usd,
                "vendor": vendor,
            }, indent=2).encode())
            return

        # Verify signature (simplified — real impl would verify on-chain)
        # For the demo, accept any signature as valid
        print(f"[vendor] x402 payment received for {vendor}: ${amount_usd:.2f}")
        print(f"[vendor] Signature: {sig_header[:50]}...")

        # Accept payment
        result = pay_invoice(vendor, amount_usd)
        result["tx_hash"] = f"0x_vendor_x402_{vendor}_{int(time.time())}_{random.randint(10000, 99999)}"
        result["mode"] = "x402_verified"
        result["settled_by"] = "vendor_server_x402"

        self._send_json(result)


def run_server(port=PORT):
    load_rules()
    server = HTTPServer(("localhost", port), VendorHandler)
    print(f"[vendor] Mock Vendor API running on http://localhost:{port}")
    print(f"[vendor] Endpoints: POST /inject_invoice, POST /negotiate, POST /pay, POST /pay-x402, POST /chaos, GET /invoice, GET /rules, GET /health")
    print(f"[vendor] x402: /pay-x402 is {'ENABLED' if X402_ENABLED else 'disabled (returns direct payment)'}")
    print(f"[vendor] Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[vendor] Shutting down.")
        server.shutdown()


if __name__ == "__main__":
    run_server()
