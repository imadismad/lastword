import { useEffect, useState } from 'react'
import { AlertTriangle, FileText, ScanSearch, Send } from 'lucide-react'
import { api, post, short, usdc } from '../lib/api'

type Sample = { id: string; title: string; text: string }
export type Evaluation = {
  reader: string; quote_hash: string; schema_ok: boolean; extracted: Record<string, any>
  verdict: 'REJECT' | 'ASK_DELIVERY' | 'ASK_BADGE'; score: number; reasons: Record<string, string>
  explanation?: string; proposal: Record<string, any> | null; ms: number
}

const CRITERIA: Record<string, string> = {
  C1: 'supplier whitelisted', C2: 'address age', C3: 'per-tx cap', C4: 'budget', C5: 'frequency',
  C6: 'not a duplicate', C7: 'quote coherence', C8: 'not expired', C9: 'token allowed',
  C10: 'delivery', C11: 'sender', C12: 'no hidden instruction', C13: 'no anomaly', C14: 'provenance',
}

const VERDICT_STYLE: Record<string, string> = {
  ASK_BADGE: 'text-ok border-ok/40 bg-ok/10',
  ASK_DELIVERY: 'text-wait border-wait/40 bg-wait/10',
  REJECT: 'text-bad border-bad/40 bg-bad/10',
}

export function Quote({ busy, onPay }: { busy: boolean; onPay: (p: Record<string, any>) => Promise<void> }) {
  const [samples, setSamples] = useState<Sample[]>([])
  const [text, setText] = useState('')
  const [ev, setEv] = useState<Evaluation | null>(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => { api<Sample[]>('/api/samples').then(setSamples).catch(() => {}) }, [])

  const pick = (s: Sample) => {
    // a run tag keeps each demo quote unique (the contract refuses a reused quote hash, C6)
    setText(s.text.replace(/(ref:\s*\S+)/i, `$1-${Math.random().toString(36).slice(2, 6).toUpperCase()}`))
    setEv(null); setErr('')
  }
  const analyze = async () => {
    setLoading(true); setErr('')
    try { setEv(await post<Evaluation>('/api/evaluate', { text })) }
    catch (e: any) { setErr(e.message) }
    finally { setLoading(false) }
  }
  const send = async () => {
    if (!ev?.proposal) return
    setErr('')
    try { await onPay(ev.proposal) } catch (e: any) { setErr(e.message) }
  }

  return (
    <section className="panel flex flex-col p-5">
      <div className="flex items-center justify-between">
        <div className="label flex items-center gap-2"><FileText size={14} /> 1 · Incoming supplier quote</div>
        <div className="text-[11px] text-ink-400">untrusted input</div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {samples.map(s => (
          <button key={s.id} onClick={() => pick(s)}
            className={`rounded-full border px-2.5 py-1 text-xs transition hover:border-brand hover:text-brand ${/Legit/.test(s.title) ? 'border-ink-600 text-ink-300' : 'border-bad/30 text-bad/90'}`}>
            {s.title}
          </button>
        ))}
      </div>
      <textarea value={text} onChange={e => { setText(e.target.value); setEv(null) }}
        placeholder="Paste a quote, or pick a sample above…"
        className="mono mt-3 h-40 w-full resize-none rounded-xl border border-ink-700 bg-ink-950/60 p-3 text-xs leading-relaxed text-ink-100 outline-none focus:border-brand" />
      <button onClick={analyze} disabled={!text.trim() || loading}
        className="mt-3 flex items-center justify-center gap-2 rounded-xl border border-ink-100 bg-ink-100 px-4 py-2.5 text-sm font-semibold text-ink-950 transition hover:bg-ink-300 disabled:opacity-40">
        <ScanSearch size={16} /> {loading ? 'Reading…' : 'Read with the isolated agent'}
      </button>

      {ev && (
        <div className="mt-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className={`rounded-lg border px-3 py-1 text-lg font-bold tracking-wide ${VERDICT_STYLE[ev.verdict]}`}>{ev.verdict}</span>
            <span className="text-xs text-ink-400">{ev.reader} · {ev.ms} ms</span>
          </div>
          <div>
            <div className="flex justify-between text-[11px] text-ink-400"><span>risk score</span><span className="mono">{Math.round(ev.score * 100)} / 100</span></div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-800">
              <div className={`h-full rounded-full ${ev.score >= 0.6 ? 'bg-bad' : ev.score >= 0.25 ? 'bg-wait' : 'bg-ok'}`} style={{ width: `${Math.max(3, Math.min(100, ev.score * 100))}%` }} />
            </div>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
            <dt className="text-ink-400">supplier</dt><dd>{ev.extracted.supplier_name ?? '—'}</dd>
            <dt className="text-ink-400">pay to</dt><dd className="mono">{short(ev.extracted.beneficiary, 10, 8) || '—'}</dd>
            <dt className="text-ink-400">amount</dt><dd className="mono">{ev.extracted.amount?.toLocaleString?.('en-US') ?? '—'} <span className="text-ink-400">units ({usdc(ev.extracted.amount)})</span></dd>
            <dt className="text-ink-400">quote hash</dt><dd className="mono text-ink-300">{short(ev.quote_hash, 10, 6)}</dd>
          </dl>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(ev.reasons).map(([c, r]) => (
              <span key={c} title={CRITERIA[c] || c}
                className={`mono rounded-md border px-1.5 py-0.5 text-[10px] ${r === 'pass' ? 'border-ok/30 text-ok' : r === 'fail' ? 'border-bad/40 bg-bad/10 text-bad' : 'border-ink-700 text-ink-400'}`}>
                {c} {CRITERIA[c] ? '· ' + CRITERIA[c] : ''}
              </span>
            ))}
          </div>
          {ev.extracted.risk_signals?.hidden_instruction_text && (
            <div className="rounded-lg border border-bad/30 bg-bad/5 p-2.5 text-xs">
              <div className="flex items-center gap-1.5 font-semibold text-bad"><AlertTriangle size={13} /> Hidden instruction found — flagged, never executed</div>
              <div className="mono mt-1 line-clamp-2 text-ink-300">“{ev.extracted.risk_signals.hidden_instruction_text}”</div>
            </div>
          )}
          {ev.explanation && <p className="text-xs leading-relaxed text-ink-300">{ev.explanation}</p>}
          {ev.proposal ? (
            <button onClick={send} disabled={busy}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 py-3 text-sm font-bold text-white shadow-lg shadow-brand/30 transition hover:brightness-110 disabled:opacity-40">
              <Send size={16} /> {busy ? 'A payment is in flight…' : 'Send to the badge over LoRa'}
            </button>
          ) : (
            <div className="rounded-xl border border-bad/30 bg-bad/5 px-3 py-2.5 text-xs text-bad">
              Nothing leaves the Dell: the agent can only stop or escalate, never pay.
            </div>
          )}
        </div>
      )}
      {err && <div className="mt-3 rounded-lg border border-bad/30 bg-bad/5 px-3 py-2 text-xs text-bad">{err}</div>}
    </section>
  )
}
