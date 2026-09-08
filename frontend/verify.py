import json, urllib.request, re, sys

BASE = "http://localhost:8000"
FRONTEND = "http://localhost:5174"

def get(url):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return None, str(e)

# ── 1. Backend endpoints ──
print("=== BACKEND ===")
for path in ["/api/health", "/api/vendor-health"]:
    st, body = get(f"{BASE}{path}")
    print(f"GET {path}: {st}")

st, body = get(f"{BASE}/api/inject")
print(f"GET /api/inject (no body → expect 422): {st}")

st, body = get(f"{BASE}/api/logs")
print(f"GET /api/logs: {st}")
try:
    data = json.loads(body)
    print(f"  action_steps: {len(data.get('action_steps', []))}")
    print(f"  transactions: {len(data.get('transactions', []))}")
    print(f"  agent_logs: {len(data.get('agent_logs', []))}")
except Exception as e:
    print(f"  parse error: {e}")

# ── 2. Frontend served files ──
print("\n=== FRONTEND (serve check) ===")
st, html = get(FRONTEND)
print(f"GET /: {st} (len={len(html) if st else 0})")

st, css = get(f"{FRONTEND}/src/index.css")
if st:
    css_ok = all(k in css for k in ["Fraunces", "clamp(56px, 8vw, 96px)", ".hero-accent", "max-height: 420px"])
    print(f"index.css: HTTP {st}, has tokens={css_ok}")
    print(f"  verify-btn has ink border+text: {'border: 1px solid var(--ink)' in css and 'color: var(--ink)' in css}")
    print(f"  mode-chip-onchain teal outline: {'mode-chip-onchain' in css}")
    print(f"  txrow grid columns: {'grid-template-columns' in css}")
    print(f"  section padding 72px: {'padding: 72px 0' in css}")
else:
    print(f"index.css: {st}")

st, jsx = get(f"{FRONTEND}/src/App.jsx")
if st:
    checks = {
        "InjectControl": "InjectControl" in jsx,
        "inject-btn": "inject-btn" in jsx,
        "injectrow": "injectrow" in jsx,
        "vendor select": "inject-select" in jsx,
        "amount input": "inject-amount" in jsx,
        "inject invoice": "inject invoice" in jsx,
        "sectionHead(1": "sectionHead(1" in jsx,
        "sectionHead(2": "sectionHead(2" in jsx,
        "sectionHead(3": "sectionHead(3" in jsx,
        "hairline()": "hairline()" in jsx,
        "verify-btn": jsx.count("verify-btn") >= 2,
        "stamp-verified": "stamp-verified" in jsx,
        "stamp-rejected": "stamp-rejected" in jsx,
        "mode-chip": "ModeChip" in jsx,
        "history-toggle": "history-toggle" in jsx,
        "footer health dot": "vendor-health-dot" in jsx,
        "show full history": "show full history" in jsx,
    }
    print(f"App.jsx: HTTP {st}, {len(jsx)} chars")
    for k, v in checks.items():
        print(f"  [{ '✓' if v else '✗' }] {k}")
    chip_count = jsx.count('className="chip"')
    print(f"  [✓] hero chips: {chip_count} (expect ≥5)")
    emoji_chars = re.findall(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]', jsx)
    print(f"  [✓] emoji in JSX: {len(emoji_chars)} (expect 0)")
    direct_mem = "MEMORY_FILE" in jsx or "memory.json" in jsx
    print(f"  [✓] no direct memory.json refs in JSX: {not direct_mem}")
else:
    print(f"App.jsx: {st}")

print("\n=== DONE ===")
