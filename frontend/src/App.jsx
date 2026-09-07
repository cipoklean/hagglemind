import { useState, useEffect, useRef, useCallback } from "react"

// ---------------------------------------------------------------------------
// Config — points at the FastAPI backend.  Update API_URL when deploying.
// ---------------------------------------------------------------------------
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function confidenceColor(c) {
  if (c == null || isNaN(c)) return "bg-surface-500"
  if (c >= 0.7) return "bg-accent-green"
  if (c >= 0.4) return "bg-accent-yellow"
  return "bg-accent-red"
}

function confidenceLabel(c) {
  if (c == null || isNaN(c)) return "—"
  if (c >= 0.7) return "Strong"
  if (c >= 0.4) return "Fair"
  return "Weak"
}

function formatTimestamp(ts) {
  if (!ts) return "—"
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

function isRealHash(hash) {
  return typeof hash === "string" && hash.startsWith("0x") && hash.length === 66
}

// ---------------------------------------------------------------------------
// Section A — The Agent's Brain
// ---------------------------------------------------------------------------

function MemorySection({ onRefresh }) {
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

  const vendorList = Object.entries(vendors).sort((a, b) => a[0].localeCompare(b[0]))

  return (
    <section className="panel">
      <div className="panel-header">
        <h2 className="panel-title">
          <span className="title-icon">🧠</span> The Agent's Brain
        </h2>
        <button
          className="btn btn-ghost"
          onClick={refresh}
          disabled={loading}
          title="Fetch latest from Sibyl Memory"
        >
          {loading ? "…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="mb-3 px-3 py-2 bg-accent-red/10 border border-accent-red/30 rounded text-sm text-accent-red">
          Error loading memory: {error}
        </div>
      )}

      {vendorList.length === 0 && !loading && (
        <div className="empty-state">
          <div className="empty-icon">📭</div>
          <p>No vendor memory yet</p>
          <p className="text-xs text-surface-500 mt-1">
            Run the agent to populate Sibyl Memory
          </p>
        </div>
      )}

      {vendorList.length > 0 && (
        <div className="memory-grid">
          {vendorList.map(([vendor, tactics]) => (
            <div key={vendor} className="vendor-card">
              <div className="vendor-name">{vendor}</div>
              <div className="tactic-list">
                {Object.entries(tactics).map(([tactic, data]) => {
                  const conf = data?.confidence ?? 0
                  return (
                    <div key={tactic} className="tactic-row">
                      <div className="tactic-info">
                        <span className="tactic-name">{tactic}</span>
                        <span className="tactic-stats">
                          {data?.successes ?? 0}s / {data?.failures ?? 0}f
                        </span>
                      </div>
                      <div className="conf-cell">
                        <div className="conf-bar-wrap" title={`${conf.toFixed(2)} — ${confidenceLabel(conf)}`}>
                          <div className="conf-bar">
                            <div className={`conf-fill ${confidenceColor(conf)}`}
                              style={{ width: `${Math.min(100, Math.max(4, conf * 100))}%` }} />
                          </div>
                        </div>
                        <span className="conf-value">{conf.toFixed(2)}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      <style>{`
        .memory-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
          gap: 10px;
        }
        .vendor-card {
          background: rgba(30, 41, 59, 0.6);
          border: 1px solid rgba(51, 65, 85, 0.6);
          border-radius: 8px;
          padding: 10px;
        }
        .vendor-name {
          font-weight: 600;
          font-size: 13px;
          color: #94a3b8;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          margin-bottom: 6px;
        }
        .tactic-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 6px;
          padding: 3px 0;
        }
        .tactic-info {
          display: flex;
          flex-direction: column;
          min-width: 0;
          flex: 1;
        }
        .tactic-name {
          font-size: 12px;
          color: #e2e8f0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .tactic-stats {
          font-size: 10px;
          color: #64748b;
        }
        .conf-cell {
          display: flex;
          align-items: center;
          gap: 5px;
          flex-shrink: 0;
        }
        .conf-bar-wrap {
          width: 44px;
          height: 5px;
          background: #1e293b;
          border-radius: 3px;
          overflow: hidden;
        }
        .conf-bar {
          height: 100%;
          border-radius: 3px;
          transition: width 0.3s;
        }
        .conf-fill { width: 4%; }
        .conf-value {
          font-size: 11px;
          font-weight: 600;
          color: #cbd5e1;
          min-width: 32px;
          text-align: right;
          font-variant-numeric: tabular-nums;
        }
      `}</style>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Section B — Live Agent Console
// ---------------------------------------------------------------------------

function ConsoleSection({ onRunComplete }) {
  const [steps, setSteps] = useState([])
  const [loading, setLoading] = useState(false)
  const [runError, setRunError] = useState(null)
  const pollRef = useRef(null)
  const endRef = useRef(null)

  const fetchLogs = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/logs?limit=200`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      // action_steps are the terminal-style steps; fall back to agent_logs if missing
      const raw = data.action_steps || data.agent_logs || []
      // Normalise to a consistent shape for the console
      const normalised = raw.map((s) => ({
        id: s.id ?? s.step_num ?? Math.random().toString(36).slice(2),
        ts: s.timestamp ?? s.ts ?? "",
        vendor: s.vendor ?? "",
        type: s.step_type ?? s.type ?? "info",
        message: s.message ?? s.note ?? JSON.stringify(s),
      }))
      // newest first → reverse so console reads top-to-bottom chronologically
      const ordered = [...normalised].reverse()
      setSteps((prev) => {
        // keep a stable running log — append new items without duplication
        const seen = new Set(prev.map((p) => p.id))
        const fresh = ordered.filter((s) => !seen.has(s.id))
        return [...fresh, ...prev]
      })
    } catch {
      // silent — polling will retry
    }
  }, [])

  // Initial load
  useEffect(() => {
    fetchLogs()
    const timer = setInterval(fetchLogs, 1500)
    return () => clearInterval(timer)
  }, [fetchLogs])

  const runAgent = useCallback(async () => {
    setLoading(true)
    setRunError(null)
    // clear prior steps for a clean console
    setSteps([])
    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 90000) // 90s for full run
      const res = await fetch(`${API_URL}/api/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vendor: null }),
        signal: controller.signal,
      })
      clearTimeout(timeout)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      // The server blocks until the run finishes, so at this point the console
      // should already be populated by the background /api/logs poll.
      // Wait a moment for the last steps to flush, then mark complete.
      await new Promise((r) => setTimeout(r, 1500))
      setLoading(false)
      onRunComplete?.()
    } catch (err) {
      if (err.name === "AbortError") {
        // Fetch timed out — the server may still be running.  Keep polling.
        setRunError("Run timed out — checking logs for progress…")
        // Let the existing /api/logs poll continue; after ~10s with no new
        // steps we give up and clear loading.
        setTimeout(() => {
          setLoading(false)
          onRunComplete?.()
        }, 10000)
        return
      }
      setRunError(err.message)
      setLoading(false)
    }
  }, [fetchLogs, onRunComplete])

  // auto-scroll
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [steps])

  const typeIcon = (type) => {
    switch (type) {
      case "run": return "🚀"
      case "info": return "·"
      case "memory": return "📚"
      case "decision": return "🎯"
      case "action": return "⚡"
      case "vendor": return "💬"
      case "result": return "✅"
      case "payment": return "💸"
      case "error": return "❌"
      case "warning": return "⚠️"
      default: return "·"
    }
  }

  const typeColor = (type) => {
    switch (type) {
      case "run": return "text-accent-purple"
      case "error": return "text-accent-red"
      case "warning": return "text-accent-yellow"
      case "payment": return "text-accent-green"
      case "result": return "text-accent-green"
      case "decision": return "text-accent-blue"
      case "memory": return "text-surface-400"
      default: return "text-surface-400"
    }
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <h2 className="panel-title">
          <span className="title-icon">⚡</span> Live Agent Console
        </h2>
        <button
          className={`btn btn-primary ${loading ? "btn-disabled" : ""}`}
          onClick={runAgent}
          disabled={loading}
        >
          {loading ? "Running…" : "▶ Run Negotiation Agent"}
        </button>
      </div>

      {runError && (
        <div className="mb-3 px-3 py-2 bg-accent-red/10 border border-accent-red/30 rounded text-sm text-accent-red">
          Run error: {runError}
        </div>
      )}

      {steps.length === 0 && !loading && (
        <div className="empty-state">
          <div className="empty-icon">⏳</div>
          <p>Console idle — press Run to start</p>
        </div>
      )}

      <div className="console-output">
        {steps.map((step) => (
          <div key={step.id} className={`console-line ${typeColor(step.type)}`}>
            <span className="console-ts">{formatTimestamp(step.ts).slice(11, 19)}</span>
            <span className="console-icon">{typeIcon(step.type)}</span>
            <span className="console-msg">{step.message || "·"}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      {loading && (
        <div className="mt-2 text-xs text-surface-500 flex items-center gap-2">
          <span className="blink">●</span> Polling for completion…
        </div>
      )}

      <style>{`
        .console-output {
          background: #020617;
          border: 1px solid #1e293b;
          border-radius: 8px;
          padding: 12px 14px;
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
          font-size: 12px;
          line-height: 1.7;
          min-height: 180px;
          max-height: 320px;
          overflow-y: auto;
        }
        .console-line {
          display: flex;
          gap: 8px;
          align-items: baseline;
          white-space: pre-wrap;
          word-break: break-word;
        }
        .console-ts {
          color: #475569;
          flex-shrink: 0;
          min-width: 70px;
        }
        .console-icon {
          flex-shrink: 0;
        }
        .console-msg {
          color: #cbd5e1;
        }
        .blink {
          animation: blink 1s step-end infinite;
        }
        @keyframes blink {
          50% { opacity: 0; }
        }
      `}</style>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Section C — On-Chain Proof
// ---------------------------------------------------------------------------

function ChainProofSection() {
  const [txs, setTxs] = useState([])
  const [loading, setLoading] = useState(true)
  const [verifying, setVerifying] = useState({})
  const [proofs, setProofs] = useState({})
  const [error, setError] = useState(null)

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
      const res = await fetch(`${API_URL}/api/chain-proof/${encodeURIComponent(tx.tx_hash)}`)
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

  return (
    <section className="panel">
      <div className="panel-header">
        <h2 className="panel-title">
          <span className="title-icon">⛓️</span> On-Chain Proof
        </h2>
        <button className="btn btn-ghost" onClick={fetchTxs} disabled={loading}>
          {loading ? "…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="mb-3 px-3 py-2 bg-accent-red/10 border border-accent-red/30 rounded text-sm text-accent-red">
          {error}
        </div>
      )}

      {txs.length === 0 && !loading && (
        <div className="empty-state">
          <div className="empty-icon">🔗</div>
          <p>No transactions yet</p>
          <p className="text-xs text-surface-500 mt-1">Run the agent to generate on-chain payments</p>
        </div>
      )}

      {/* Real txs first */}
      {realTxs.length > 0 && (
        <div className="proof-list">
          <div className="proof-section-label">REAL ON-CHAIN TRANSACTIONS</div>
          {realTxs.map((tx) => (
            <TransactionRow key={tx.id} tx={tx} proof={proofs[tx.id]} verifying={verifying[tx.id]} onVerify={verify} />
          ))}
        </div>
      )}

      {/* Mock txs last, visually deprioritised */}
      {mockTxs.length > 0 && (
        <div className="proof-list">
          <div className="proof-section-label mock">MOCK VENDOR MARKERS (NOT ON-CHAIN)</div>
          {mockTxs.map((tx) => (
            <TransactionRow key={tx.id} tx={tx} proof={proofs[tx.id]} verifying={verifying[tx.id]} onVerify={verify} />
          ))}
        </div>
      )}

      {realTxs.length === 0 && mockTxs.length > 0 && !loading && (
        <div className="mt-2 px-3 py-2 bg-accent-yellow/10 border border-accent-yellow/30 rounded text-xs text-accent-yellow">
          ⚠️ All recorded transactions are vendor mock markers. Only real 66-char hex hashes can be verified on-chain.
        </div>
      )}

      <style>{`
        .proof-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .proof-section-label {
          font-size: 10px;
          font-weight: 600;
          letter-spacing: 0.08em;
          color: #64748b;
          margin-bottom: 4px;
          padding-left: 2px;
        }
        .proof-section-label.mock {
          color: #64748b;
          font-style: italic;
        }
      `}</style>
    </section>
  )
}

function TransactionRow({ tx, proof, verifying, onVerify }) {
  const real = isRealHash(tx.tx_hash)
  const verified = proof?.verified
  const raw = proof?.raw

  return (
    <div className={`tx-row ${real ? "tx-real" : "tx-mock"}`}>
      <div className="tx-main">
        <div className="tx-hash">
          <span className="tx-hash-label">Tx</span>
          <code className="tx-hash-value">{tx.tx_hash.slice(0, 10)}…{tx.tx_hash.slice(-6)}</code>
          {real && (
            <a href={`https://sepolia.basescan.org/tx/${tx.tx_hash}`} target="_blank" rel="noopener noreferrer"
              className="tx-basescan-link" title="View on BaseScan">
              ↗
            </a>
          )}
        </div>
        <div className="tx-meta">
          <span className="tx-vendor">{tx.vendor}</span>
          <span className="tx-sep">·</span>
          <span className="tx-amount">${Number(tx.amount_usd).toFixed(2)}</span>
          <span className="tx-sep">·</span>
          <span className="tx-mode">{tx.payment_mode?.replace("_", " ") ?? "unknown"}</span>
        </div>
      </div>

      <div className="tx-actions">
        {real && (
          <button
            className={`btn-verify ${verifying ? "btn-verifying" : ""}`}
            onClick={() => onVerify(tx)}
            disabled={!!verifying}
          >
            {verifying ? "Verifying…" : "Verify on Chain"}
          </button>
        )}
        {!real && (
          <button className="btn-verify btn-mock" disabled title="Mock hash — cannot verify on-chain">
            Verify on Chain
          </button>
        )}
        {real && (
          <a href={`https://sepolia.basescan.org/tx/${tx.tx_hash}`} target="_blank" rel="noopener noreferrer"
            className="btn btn-ghost btn-sm">
            BaseScan ↗
          </a>
        )}
      </div>

      {verified !== undefined && (
        <div className={`tx-proof ${verified ? "proof-ok" : "proof-fail"}`}>
          {verified ? (
            <>
              <div className="proof-badge">⛓️ Chain Verified</div>
              {raw && (
                <div className="proof-detail">
                  <div className="proof-row">
                    <span className="proof-k">Block</span>
                    <span className="proof-v">{raw.blockNumber?.toLocaleString()}</span>
                  </div>
                  <div className="proof-row">
                    <span className="proof-k">Gas</span>
                    <span className="proof-v">{raw.gasUsed?.toLocaleString()}</span>
                  </div>
                  <div className="proof-row">
                    <span className="proof-k">Timestamp</span>
                    <span className="proof-v">{raw.timestamp ? formatTimestamp(raw.timestamp) : "—"}</span>
                  </div>
                  {raw.logs && raw.logs.length > 0 && (
                    <div className="proof-row proof-transfer">
                      <span className="proof-k">USDC Transfer</span>
                      <span className="proof-v">
                        {raw.logs[0].from.slice(0, 6)}…{raw.logs[0].from.slice(-4)} →
                        {raw.logs[0].to.slice(0, 6)}…{raw.logs[0].to.slice(-4)}
                        {" "}{raw.logs[0].value_usd.toFixed(2)} USDC
                      </span>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="proof-badge proof-fail-badge">❌ Not Verified</div>
          )}
        </div>
      )}

      <style>{`
        .tx-row {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 8px 10px;
          background: rgba(15, 23, 42, 0.5);
          border: 1px solid rgba(51, 65, 85, 0.4);
          border-radius: 6px;
          flex-wrap: wrap;
        }
        .tx-real {
          border-left: 2px solid #22c55e;
        }
        .tx-mock {
          opacity: 0.6;
          border-left: 2px solid #475569;
        }
        .tx-main {
          flex: 1;
          min-width: 0;
        }
        .tx-hash {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .tx-hash-label {
          font-size: 10px;
          color: #64748b;
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }
        .tx-hash-value {
          font-family: ui-monospace, monospace;
          font-size: 12px;
          color: #e2e8f0;
          background: rgba(30, 41, 59, 0.6);
          padding: 1px 5px;
          border-radius: 4px;
        }
        .tx-basescan-link {
          color: #64748b;
          text-decoration: none;
          font-size: 13px;
        }
        .tx-basescan-link:hover { color: #94a3b8; }
        .tx-meta {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-top: 3px;
          font-size: 11px;
          color: #94a3b8;
        }
        .tx-sep { color: #475569; }
        .tx-vendor { font-weight: 600; color: #e2e8f0; }
        .tx-amount { color: #22c55e; font-weight: 600; }
        .tx-mode {
          text-transform: capitalize;
          color: #64748b;
        }
        .tx-actions {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-shrink: 0;
        }
        .btn-verify {
          background: #1e293b;
          color: #e2e8f0;
          border: 1px solid #334155;
          border-radius: 5px;
          padding: 4px 10px;
          font-size: 11px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.15s;
        }
        .btn-verify:hover:not(:disabled) {
          background: #334155;
          border-color: #475569;
        }
        .btn-verify.btn-verifying {
          opacity: 0.6;
          cursor: wait;
        }
        .btn-verify.btn-mock {
          opacity: 0.35;
          cursor: not-allowed;
          border-color: #334155;
        }
        .tx-proof {
          flex: 1;
          min-width: 140px;
        }
        .proof-badge {
          font-size: 11px;
          font-weight: 600;
          color: #22c55e;
          display: flex;
          align-items: center;
          gap: 4px;
          margin-bottom: 4px;
        }
        .proof-fail-badge {
          color: #ef4444;
        }
        .proof-detail {
          background: rgba(30, 41, 59, 0.4);
          border-radius: 4px;
          padding: 4px 8px;
          font-size: 11px;
        }
        .proof-row {
          display: flex;
          gap: 8px;
          padding: 1px 0;
        }
        .proof-transfer {
          color: #22c55e;
        }
        .proof-k {
          color: #64748b;
          flex-shrink: 0;
          min-width: 60px;
        }
        .proof-v {
          color: #cbd5e1;
          font-family: ui-monospace, monospace;
          font-size: 10px;
        }
      `}</style>
    </div>
  )
}

// ---------------------------------------------------------------------------
// App — layout shell
// ---------------------------------------------------------------------------

export default function App() {
  const [runComplete, setRunComplete] = useState(false)

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-left">
          <span className="header-logo">⚖️</span>
          <span className="header-title">HaggleMind</span>
          <span className="header-sub">Autonomous Bill Negotiator</span>
        </div>
        <div className="header-right">
          <span className="header-badge">Web3 · Base Sepolia</span>
          <span className="header-dot" id="live-dot" />
        </div>
      </header>

      <main className="app-main">
        <div className="dash-grid">
          <div className="dash-col dash-col-wide">
            <MemorySection />
          </div>
          <div className="dash-col dash-col-narrow">
            <ConsoleSection onRunComplete={() => setRunComplete(true)} />
          </div>
        </div>

        <div className="dash-grid dash-grid-full">
          <ChainProofSection />
        </div>
      </main>

      <footer className="app-footer">
        <span>Provable autonomous negotiation · All payments verifiable on Base Sepolia</span>
      </footer>

      <style>{`
        .app-shell {
          max-width: 1200px;
          margin: 0 auto;
          padding: 24px 20px 40px;
        }
        .app-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding-bottom: 16px;
          border-bottom: 1px solid #1e293b;
          margin-bottom: 20px;
        }
        .header-left {
          display: flex;
          align-items: baseline;
          gap: 10px;
        }
        .header-logo { font-size: 22px; }
        .header-title {
          font-size: 18px;
          font-weight: 700;
          color: #f1f5f9;
        }
        .header-sub {
          font-size: 12px;
          color: #64748b;
        }
        .header-right {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .header-badge {
          font-size: 11px;
          background: rgba(59, 130, 246, 0.15);
          color: #60a5fa;
          padding: 3px 10px;
          border-radius: 20px;
          border: 1px solid rgba(59, 130, 246, 0.3);
        }
        .header-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #22c55e;
          box-shadow: 0 0 8px rgba(34, 197, 94, 0.5);
        }
        .app-main {
          display: flex;
          flex-direction: column;
          gap: 18px;
        }
        .dash-grid {
          display: grid;
          grid-template-columns: 1fr;
          gap: 18px;
        }
        .dash-grid.dash-grid-full {
          margin-top: 6px;
        }
        .panel {
          background: rgba(15, 23, 42, 0.4);
          border: 1px solid #1e293b;
          border-radius: 10px;
          padding: 14px 16px;
        }
        .panel-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 12px;
        }
        .panel-title {
          font-size: 14px;
          font-weight: 600;
          color: #e2e8f0;
          display: flex;
          align-items: center;
          gap: 7px;
        }
        .title-icon { font-size: 15px; }
        .empty-state {
          text-align: center;
          padding: 18px 10px;
          color: #64748b;
          font-size: 13px;
        }
        .empty-icon { font-size: 24px; margin-bottom: 4px; }
        .btn {
          border: none;
          border-radius: 6px;
          padding: 6px 14px;
          font-size: 12px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.15s;
          font-family: inherit;
        }
        .btn-primary {
          background: #3b82f6;
          color: white;
        }
        .btn-primary:hover:not(:disabled) {
          background: #2563eb;
        }
        .btn-ghost {
          background: transparent;
          color: #94a3b8;
          border: 1px solid #334155;
        }
        .btn-ghost:hover:not(:disabled) {
          background: rgba(51, 65, 85, 0.5);
          color: #e2e8f0;
        }
        .btn-disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .btn-sm {
          padding: 3px 9px;
          font-size: 11px;
        }
        .app-footer {
          margin-top: 24px;
          padding-top: 12px;
          border-top: 1px solid #1e293b;
          text-align: center;
          font-size: 11px;
          color: #475569;
        }
      `}</style>
    </div>
  )
}
