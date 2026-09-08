import { useState, useEffect, useRef, useCallback } from "react"

// ---------------------------------------------------------------------------
// Config — points at the FastAPI backend. Update VITE_API_URL when deploying.
// ---------------------------------------------------------------------------
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000"
const VENDOR_URL = import.meta.env.VITE_VENDOR_URL || "http://localhost:8777"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isRealHash(hash) {
  return typeof hash === "string" && hash.startsWith("0x") && hash.length === 66
}

function formatTimestamp(ts) {
  if (!ts) return "—"
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

// mono numeral, zero-padded
function numeral(n) {
  return String(n).padStart(2, "0")
}

// mono label → UPPERCASE, letter-spacing
function monoLabel(txt) {
  return txt.toUpperCase()
}

// section heading: numeral + title
function sectionHead(num, title) {
  return (
    <div className="section-head">
      <span className="section-num">{numeral(num)} /</span>
      <h2 className="section-title">{title}</h2>
    </div>
  )
}

// hairline rule
function hairline() {
  return <hr className="hairline-section" />
}

// ---------------------------------------------------------------------------
// Top bar
// ---------------------------------------------------------------------------

function TopBar() {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <h1 className="topbar-brand">HaggleMind</h1>
        <span className="topbar-tag">AUTONOMOUS BILL NEGOTIATOR</span>
      </div>
      <div className="topbar-right">
        <span className="topbar-chip">
          <span className="live-dot" aria-hidden="true" />
          BASE SEPOLIA · LIVE
        </span>
      </div>
      <hr className="hairline" />
    </header>
  )
}

// ---------------------------------------------------------------------------
// Hero
// ---------------------------------------------------------------------------

function Hero() {
  const chips = [
    "LIVE ON BASE SEPOLIA",
    "X402 SETTLED",
    "SIBYL MEMORY SDK",
    "DELETE MEMORY → PAYS MORE",
    "CHAIN-VERIFIED UI",
  ]

  return (
    <section className="hero">
      <p className="hero-kicker">
        BUILD LOG · SIBYL LABS MEMORY HACKATHON
        <span className="kicker-rule" aria-hidden="true" />
      </p>
      <h2 className="hero-headline">
        <span>Negotiation that</span>
        <span className="hero-accent">remembers.</span>
      </h2>
      <p className="hero-lede">
        HaggleMind keeps a load-bearing memory of every vendor: what worked,
        what failed, what it cost. That memory changes the price it
        pays. Settled onchain via x402.
      </p>
      <div className="hero-chips" role="list">
        {chips.map((c) => (
          <span key={c} className="chip" role="listitem">
            {c}
          </span>
        ))}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Section 01 — MEMORY
// ---------------------------------------------------------------------------

function MemorySection() {
  const [vendors, setVendors] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/memory`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setVendors(data.vendors || {})
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const vendorList = Object.entries(vendors)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .filter(([v]) => v.length > 0)

  return (
    <section className="section section-memory">
      {hairline()}
      {sectionHead(1, "What it remembers.")}

      <div className="memory-body">
        {error && (
          <p className="section-error">Error loading memory: {error}</p>
        )}

        {vendorList.length === 0 && !loading && (
          <p className="section-empty">
            No vendor memory yet — run the agent to populate Sibyl Memory.
          </p>
        )}

        {vendorList.map(([vendor, tactics]) => (
          <div key={vendor} className="vendor-plate">
            <div className="vendor-name">{vendor}</div>
            <div className="tactic-rows">
              {Object.entries(tactics).map(([tactic, data]) => {
                const conf = data?.confidence ?? 0
                const s = data?.successes ?? 0
                const f = data?.failures ?? 0
                const pct = Math.min(100, Math.max(2, conf * 100))
                return (
                  <div key={tactic} className="tactic-row">
                    <div className="tactic-left">
                      <span className="tactic-name">{tactic}</span>
                      <span className="tactic-sub">
                        {numeral(s)}s / {numeral(f)}f
                      </span>
                    </div>
                    <div className="tactic-bar-wrap" title={`${conf.toFixed(2)}`}>
                      <span className="bar-track" />
                      <span
                        className="bar-fill"
                        style={{ width: `${pct}%` }}
                        aria-label={`${conf.toFixed(2)} confidence`}
                      />
                    </div>
                    <span className="tactic-score">{conf.toFixed(2)}</span>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="section-refresh">
        <button className="refresh-link" onClick={refresh} disabled={loading}>
          refresh ↻ {loading ? "…" : ""}
        </button>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Inject control row — vendor select + amount + inject button
// ---------------------------------------------------------------------------

const VENDORS = ["Comcast", "Netflix", "Spotify", "DisneyPlus"]

function InjectControl({ onInject }) {
  const [vendor, setVendor] = useState(VENDORS[0])
  const [amount, setAmount] = useState("1.00")
  const [injecting, setInjecting] = useState(false)
  const [result, setResult] = useState(null)

  const handleInject = useCallback(async () => {
    setInjecting(true)
    setResult(null)
    try {
      const res = await fetch(`${API_URL}/api/inject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vendor, amount: parseFloat(amount) || 1.0 }),
      })
      const data = await res.json().catch(() => ({}))
      setResult(data)
      if (data?.injected) {
        onInject?.(vendor, parseFloat(amount) || 1.0)
      }
    } catch (err) {
      setResult({ injected: false, message: err.message })
    } finally {
      setInjecting(false)
    }
  }, [vendor, amount, onInject])

  return (
    <div className="inject-row">
      <label className="inject-label">
        <span className="inject-label-text">Vendor</span>
        <select
          className="inject-select"
          value={vendor}
          onChange={(e) => setVendor(e.target.value)}
        >
          {VENDORS.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      </label>

      <label className="inject-label">
        <span className="inject-label-text">Amount</span>
        <input
          className="inject-amount"
          type="number"
          step="0.01"
          min="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="1.00"
        />
      </label>

      <button
        className={`inject-btn ${injecting ? "inject-btn-busy" : ""}`}
        onClick={handleInject}
        disabled={injecting}
      >
        {injecting ? "injecting…" : "inject invoice"}
      </button>

      {result && (
        <span className={`inject-result ${result.injected ? "inject-result-ok" : "inject-result-err"}`}>
          {result.injected ? `injected · ${result.vendor} · $${result.amount.toFixed(2)}` : result.message || "inject failed"}
        </span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section 02 — ACTION (console)
// ---------------------------------------------------------------------------

function ConsoleSection({ onRunComplete }) {
  const [steps, setSteps] = useState([])
  const [loading, setLoading] = useState(false)
  const [runError, setRunError] = useState(null)
  const [vendor, setVendor] = useState(VENDORS[0])
  const [amount, setAmount] = useState("1.00")
  const pollRef = useRef(null)
  const endRef = useRef(null)
  const scrollContainerRef = useRef(null)
  const userScrolledUpRef = useRef(false)

  const fetchLogs = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/logs?limit=200`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      // action_steps hold the full terminal-style messages (message column).
      // Fall back to agent_logs only if action_steps is genuinely empty.
      const raw = data.action_steps && data.action_steps.length > 0
        ? data.action_steps
        : data.agent_logs || []
      // Normalise to a consistent shape for the console.
      // action_steps: { id, timestamp, vendor, step_num, step_type, message }
      // agent_logs:   { id, timestamp, vendor, tactic, note, ... }
      const normalised = raw.map((s) => {
        // Prefer the real message column; never fall back to JSON.stringify
        // (that dumps the whole row object as the message text).
        const msg =
          (s.message && typeof s.message === "string") ? s.message :
          (s.note && typeof s.note === "string") ? s.note :
          (s.step_type === "run") ? `HaggleMind starting negotiation for ${s.vendor || "…"}` :
          ""
        return {
          id: s.id ?? s.step_num ?? Math.random().toString(36).slice(2),
          ts: s.timestamp ?? s.ts ?? "",
          vendor: s.vendor ?? "",
          type: s.step_type ?? s.type ?? "info",
          message: msg,
        }
      })
      // newest first → reverse so console reads top-to-bottom chronologically
      const ordered = [...normalised].reverse()
      setSteps((prev) => {
        const seen = new Set(prev.map((p) => p.id))
        const fresh = ordered.filter((s) => !seen.has(s.id) && s.message !== "")
        return [...fresh, ...prev]
      })
    } catch {
      // silent — polling will retry
    }
  }, [])

  useEffect(() => {
    fetchLogs()
    const timer = setInterval(fetchLogs, 1500)
    return () => clearInterval(timer)
  }, [fetchLogs])

  // Inject-invoice hook: called when the user clicks "inject invoice" in the
  // control row.  The Run button also calls this internally before running.
  const injectInvoice = useCallback(async (v, amt) => {
    try {
      const res = await fetch(`${API_URL}/api/inject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vendor: v, amount: amt }),
      })
      const data = await res.json().catch(() => ({}))
      if (!data?.injected) {
        setRunError(`Inject failed: ${data?.message || "vendor unreachable"}`)
      }
    } catch (err) {
      setRunError(`Inject failed: ${err.message}`)
    }
  }, [])

  const runAgent = useCallback(async () => {
    setLoading(true)
    setRunError(null)
    setSteps([])
    try {
      // 1. Inject invoice for the selected vendor (if a vendor is selected)
      if (vendor) {
        await injectInvoice(vendor, parseFloat(amount) || 1.0)
      }

      // 2. Run the negotiation agent
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 90000)
      const res = await fetch(`${API_URL}/api/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vendor: vendor || null }),
        signal: controller.signal,
      })
      clearTimeout(timeout)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      await new Promise((r) => setTimeout(r, 1500))
      setLoading(false)
      onRunComplete?.()
    } catch (err) {
      if (err.name === "AbortError") {
        setRunError("Run timed out — checking logs for progress…")
        setTimeout(() => {
          setLoading(false)
          onRunComplete?.()
        }, 10000)
        return
      }
      setRunError(err.message)
      setLoading(false)
    }
  }, [vendor, amount, fetchLogs, onRunComplete, injectInvoice])

  // auto-scroll — only when user is at the bottom; stop when they scroll up
  useEffect(() => {
    const el = scrollContainerRef.current
    if (!el || !endRef.current) return
    const gap = el.scrollHeight - el.scrollTop - el.clientHeight
    if (gap < 40 && !userScrolledUpRef.current) {
      el.scrollTop = el.scrollHeight
    }
    if (gap < 40) {
      userScrolledUpRef.current = false
    }
  }, [steps])

  const onScroll = () => {
    const el = scrollContainerRef.current
    if (!el) return
    const gap = el.scrollHeight - el.scrollTop - el.clientHeight
    if (gap >= 40) {
      userScrolledUpRef.current = true
    }
  }

  // type → mono label (no emoji)
  const typeLabel = (type) => {
    switch (type) {
      case "run": return "RUN"
      case "info": return "·"
      case "memory": return "MEM"
      case "decision": return "DEC"
      case "action": return "ACT"
      case "vendor": return "VND"
      case "result": return "OK"
      case "payment": return "PAY"
      case "error": return "ERR"
      case "warning": return "WARN"
      default: return "·"
    }
  }

  const typeColorClass = (type) => {
    switch (type) {
      case "run": return "ts-run"
      case "error": return "ts-err"
      case "warning": return "ts-warn"
      case "payment": return "ts-pay"
      case "result": return "ts-ok"
      case "decision": return "ts-dec"
      case "memory": return "ts-mem"
      case "vendor": return "ts-vnd"
      case "action": return "ts-act"
      default: return "ts-info"
    }
  }

  return (
    <section className="section section-action">
      {hairline()}
      {sectionHead(2, "Watch it think.")}

      <div className="action-body">
        {runError && (
          <p className="section-error">{runError}</p>
        )}

        {/* Inject control row */}
        <InjectControl onInject={injectInvoice} />

        <div className="terminal" ref={scrollContainerRef} onScroll={onScroll}>
          {steps.length === 0 && !loading && (
            <div className="terminal-empty">Console idle — press Run to start</div>
          )}
          {steps.map((step) => (
            <div key={step.id} className={`terminal-line ${typeColorClass(step.type)}`}>
              <span className="terminal-ts">{formatTimestamp(step.ts)}</span>
              <span className="terminal-tag">{typeLabel(step.type)}</span>
              <span className="terminal-body">
                <span className="terminal-vendor">[{step.vendor}]</span>
                <span className="terminal-msg">{step.message || "·"}</span>
              </span>
            </div>
          ))}
          <div ref={endRef} />
        </div>

        <div className="terminal-caption">
          fig. 02 — live transcript, polled from /api/logs
        </div>

        <div className="action-control">
          <button
            className={`run-pill ${loading ? "run-pill-disabled" : "run-pill-active"}`}
            onClick={runAgent}
            disabled={loading}
          >
            {loading ? "Run in progress…" : "Run negotiation agent"}
          </button>
          {loading && (
            <span className="run-status">polling /api/logs · 90s timeout</span>
          )}
          {!loading && runError && (
            <span className="run-status run-status-err">{runError}</span>
          )}
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Mode chip — X402 ONCHAIN (teal outline) / DIRECT API (muted outline)
// ---------------------------------------------------------------------------

function ModeChip({ mode }) {
  const normalised = (mode || "unknown").toUpperCase().replace(/_/g, " ")
  const isOnchain = normalised === "X402 ONCHAIN"
  const isDirect = normalised === "DIRECT API"

  return (
    <span
      className={`mode-chip ${isOnchain ? "mode-chip-onchain" : isDirect ? "mode-chip-direct" : "mode-chip-unknown"}`}
      title={isDirect ? "settled off-chain (dev fallback)" : isOnchain ? "settled on-chain via x402" : normalised}
    >
      {normalised}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Section 03 — SETTLEMENT (on-chain proof)
// ---------------------------------------------------------------------------

function ChainProofSection() {
  const [txs, setTxs] = useState([])
  const [loading, setLoading] = useState(true)
  const [verifying, setVerifying] = useState({})
  const [proofs, setProofs] = useState({})
  const [error, setError] = useState(null)
  const [showAll, setShowAll] = useState(false)

  const fetchTxs = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/logs?limit=50`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setTxs(data.transactions || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchTxs()
  }, [fetchTxs])

  const verify = useCallback(async (tx) => {
    if (verifying[tx.id]) return
    setVerifying((prev) => ({ ...prev, [tx.id]: true }))
    try {
      const res = await fetch(
        `${API_URL}/api/chain-proof/${encodeURIComponent(tx.tx_hash)}`,
      )
      const data = await res.json()
      setProofs((prev) => ({ ...prev, [tx.id]: data }))
    } catch {
      setProofs((prev) => ({
        ...prev,
        [tx.id]: { verified: false, hash: tx.tx_hash, error: "Request failed" },
      }))
    } finally {
      setVerifying((prev) => ({ ...prev, [tx.id]: false }))
    }
  }, [])

  const realTxs = txs.filter((t) => isRealHash(t.tx_hash))
  const mockTxs = txs.filter((t) => !isRealHash(t.tx_hash))
  const displayTxs = showAll ? txs : realTxs

  return (
    <section className="section section-settlement">
      {hairline()}
      {sectionHead(3, "Proof, not promises.")}

      <div className="settlement-body">
        {error && (
          <p className="section-error">{error}</p>
        )}

        {txs.length === 0 && !loading && (
          <p className="section-empty">
            No transactions yet — run the agent to generate on-chain payments.
          </p>
        )}

        {/* toggle: show full history (mock + direct-api rows) */}
        {mockTxs.length > 0 && !loading && (
          <button
            className="history-toggle"
            onClick={() => setShowAll((v) => !v)}
          >
            {showAll
              ? `hide mock rows`
              : `show full history · ${mockTxs.length} mock`}
          </button>
        )}

        {/* real-hash rows (always shown unless hidden by toggle) */}
        {realTxs.length > 0 && (
          <div className="tx-table">
            {realTxs.map((tx) => (
              <TransactionRow
                key={tx.id}
                tx={tx}
                proof={proofs[tx.id]}
                verifying={verifying[tx.id]}
                onVerify={verify}
              />
            ))}
          </div>
        )}

        {/* mock / direct-api rows — only when toggle is open */}
        {showAll && mockTxs.length > 0 && (
          <div className="tx-table tx-table-mock">
            {mockTxs.map((tx) => (
              <TransactionRow
                key={tx.id}
                tx={tx}
                proof={proofs[tx.id]}
                verifying={verifying[tx.id]}
                onVerify={verify}
              />
            ))}
          </div>
        )}

        {realTxs.length === 0 &&
          mockTxs.length > 0 &&
          !loading && !showAll && (
            <p className="section-warn">
              All recorded transactions are vendor mock markers. Only real
              66-char hex hashes can be verified on-chain.
            </p>
          )}
      </div>
    </section>
  )
}

function TransactionRow({ tx, proof, verifying, onVerify }) {
  const real = isRealHash(tx.tx_hash)
  const verified = proof?.verified
  const raw = proof?.raw

  const mode = tx.payment_mode ?? "unknown"
  const amount = tx.amount_usd != null
    ? `$${Number(tx.amount_usd).toFixed(2)}`
    : "—"

  // middle-truncated hash: keep first 10 + last 6, drop the middle
  const hashShort = tx.tx_hash.slice(0, 10) + "···" + tx.tx_hash.slice(-6)

  return (
    <div className={`tx-row ${real ? "tx-row-real" : "tx-row-mock"}`}>
      {/* col 1: tx hash + basescan */}
      <div className="tx-cell tx-cell-hash">
        <span className="tx-hash-label">Tx</span>
        <code className="tx-hash-code">{hashShort}</code>
        {real && (
          <a
            href={`https://sepolia.basescan.org/tx/${tx.tx_hash}`}
            target="_blank"
            rel="noopener noreferrer"
            className="basescan-link"
            title="View on BaseScan"
          >
            basescan ↗
          </a>
        )}
        {!real && (
          <span className="tx-hash-mock-tag">mock</span>
        )}
      </div>

      {/* col 2: vendor */}
      <div className="tx-cell tx-cell-vendor">
        <span className="tx-vendor-name">{tx.vendor || "—"}</span>
      </div>

      {/* col 3: amount */}
      <div className="tx-cell tx-cell-amount">
        <span className="tx-amount">{amount}</span>
      </div>

      {/* col 4: mode chip */}
      <div className="tx-cell tx-cell-mode">
        <ModeChip mode={mode} />
      </div>

      {/* col 5: verify button */}
      <div className="tx-cell tx-cell-verify">
        {real ? (
          <button
            className={`verify-btn ${verifying ? "verify-btn-busy" : ""}`}
            onClick={() => onVerify(tx)}
            disabled={!!verifying}
          >
            {verifying ? "verifying…" : "verify on chain"}
          </button>
        ) : (
          <span className="verify-btn verify-btn-mock" title="Mock hash — cannot verify on-chain">
            verify on chain
          </span>
        )}
      </div>

      {/* col 6: basescan link (real hashes only) */}
      {real && (
        <div className="tx-cell tx-cell-basescan">
          <a
            href={`https://sepolia.basescan.org/tx/${tx.tx_hash}`}
            target="_blank"
            rel="noopener noreferrer"
            className="basescan-link"
          >
            basescan ↗
          </a>
        </div>
      )}

      {/* col 7: proof stamp */}
      {validProof(proof) && (
        <div className="tx-cell tx-cell-stamp">
          <div className={`proof-stamp ${verified ? "stamp-verified" : "stamp-rejected"}`}>
            {verified ? (
              <>
                <span>VERIFIED</span>
                {raw && (
                  <span className="stamp-detail">
                    · BLOCK {raw.blockNumber?.toLocaleString()}
                    · GAS {raw.gasUsed?.toLocaleString()}
                  </span>
                )}
              </>
            ) : (
              <>REJECTED · NOT ON CHAIN</>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function validProof(p) {
  return p != null && typeof p === "object"
}

// ---------------------------------------------------------------------------
// Footer — with vendor-server health dot
// ---------------------------------------------------------------------------

function Footer() {
  const [health, setHealth] = useState({ alive: false, status: "checking…" })
  const [hLoading, setHLoading] = useState(true)

  useEffect(() => {
    const f = async () => {
      setHLoading(true)
      try {
        const res = await fetch(`${API_URL}/api/vendor-health`)
        const data = await res.json().catch(() => ({}))
        setHealth(data)
      } catch {
        setHealth({ alive: false, status: "unreachable" })
      } finally {
        setHLoading(false)
      }
    }
    f()
    const timer = setInterval(f, 10000)
    return () => clearInterval(timer)
  }, [])

  return (
    <footer className="footer">
      <hr className="hairline" />
      <div className="footer-inner">
        <span className="footer-left">
          Sibyl Memory · Base · x402 — built for the Sibyl Labs Memory Hackathon
        </span>

        <span className="footer-health" title={health.status || "vendor server health"}>
          <span className={`vendor-health-dot ${health.alive ? "vendor-health-alive" : ""}`} aria-hidden="true" />
          <span className="vendor-health-label">
            {hLoading ? "terminal 1 · …" : health.alive ? "terminal 1 · alive" : "terminal 1 · down"}
          </span>
        </span>

        <a
          href="https://github.com/cipoklean/veriflow"
          target="_blank"
          rel="noopener noreferrer"
          className="footer-right"
        >
          repo ↗
        </a>
      </div>
    </footer>
  )
}

// ---------------------------------------------------------------------------
// App — layout shell
// ---------------------------------------------------------------------------

export default function App() {
  const [runComplete, setRunComplete] = useState(false)

  return (
    <div className="page">
      <TopBar />
      <main className="main">
        <Hero />
        <MemorySection />
        <ConsoleSection onRunComplete={() => setRunComplete(true)} />
        <ChainProofSection />
      </main>
      <Footer />
    </div>
  )
}
