import { CheckCircle2, CircleDashed, ExternalLink, Loader2, ShieldX, XCircle } from 'lucide-react'
import type { Live, Step } from '../lib/live'
import { secs, short, usdc } from '../lib/api'

const STEPS: { key: string; title: string; who: string; what: string }[] = [
  { key: 'propose', title: 'Propose on-chain', who: 'agent key', what: 'contract runs C1 C3 C6 C8 C9 and stores the intent digest' },
  { key: 'stock', title: 'STOCK request over LoRa', who: 'gateway → badge', what: 'sealed frame (AES-256-GCM + gateway P-256 sig); badge shows the delivery to attest' },
  { key: 'attest', title: 'Delivery attested', who: 'bridge submits', what: 'contract verifies the STOCK P-256 signature (TROPIC01)' },
  { key: 'rolecheck', title: 'Role separation check', who: 'contract', what: 'the STOCK signature replayed as a DAF approval must be rejected' },
  { key: 'daf', title: 'DAF request over LoRa', who: 'gateway → badge', what: 'badge shows beneficiary + amount; the human approves with the PIN' },
  { key: 'approve', title: 'Approve & pay', who: 'contract', what: 'P-256 signature on the recomputed digest → stablecoin transfer' },
]

export function Pipeline({ live, explorer }: { live: Live; explorer?: string }) {
  const p = live.payment
  const status = p?.status
  return (
    <section className="panel flex flex-col p-5">
      <div className="flex items-center justify-between">
        <div className="label">2 · Approval pipeline</div>
        {p && <div className="mono text-[11px] text-ink-400">reqId {p.reqId}</div>}
      </div>

      {!p && (
        <div className="mt-6 flex flex-1 flex-col items-center justify-center gap-2 py-10 text-center text-sm text-ink-400">
          <CircleDashed size={28} className="text-ink-600" />
          Read a quote, then send it: every step below runs for real —<br />LoRa frames, the human on the badge, and the contract on the L1.
        </div>
      )}

      {p && (
        <>
          <div className="mt-3 flex items-center justify-between rounded-xl bg-ink-850 px-3 py-2 text-xs">
            <span className="text-ink-300">{p.supplier ?? 'supplier'}</span>
            <span className="mono">{short(p.beneficiary, 8, 6)}</span>
            <span className="mono font-semibold">{usdc(p.amount)}</span>
          </div>
          <ol className="relative mt-4 space-y-1">
            {STEPS.map((s, i) => (
              <StepRow key={s.key} i={i} def={s} st={p.steps[s.key]} explorer={explorer} last={i === STEPS.length - 1} />
            ))}
          </ol>
          {status === 'paid' && (
            <div className="mt-4 rounded-xl border border-ok/40 bg-ok/10 p-4 text-center">
              <div className="text-xl font-bold text-ok">PAID on the L1</div>
              <div className="mt-1 text-xs text-ink-300">
                end to end {secs(p.totalMs)} · the agent proposed, the badge had the last word
              </div>
            </div>
          )}
          {(status === 'refused' || status === 'error') && (
            <div className="mt-4 rounded-xl border border-bad/40 bg-bad/10 p-4 text-center">
              <div className="text-lg font-bold text-bad">No payment</div>
              <div className="mt-1 text-xs text-ink-300">{p.detail}</div>
            </div>
          )}
        </>
      )}
    </section>
  )
}

function StepRow({ i, def, st, explorer, last }: { i: number; def: (typeof STEPS)[number]; st?: Step; explorer?: string; last: boolean }) {
  const state = st?.state ?? 'idle'
  const icon = state === 'done' ? <CheckCircle2 size={18} className="text-ok" />
    : state === 'active' ? <Loader2 size={18} className="animate-spin text-brand" />
    : state === 'error' ? (def.key === 'rolecheck' ? <ShieldX size={18} className="text-bad" /> : <XCircle size={18} className="text-bad" />)
    : <span className="mono flex h-[18px] w-[18px] items-center justify-center rounded-full border border-ink-600 text-[10px] text-ink-400">{i + 1}</span>
  return (
    <li className="relative flex gap-3 pb-3">
      {!last && <span className={`absolute left-[8.5px] top-6 h-[calc(100%-18px)] w-px ${state === 'done' ? 'bg-ok/40' : 'bg-ink-700'}`} />}
      <span className="relative z-10 mt-0.5 bg-ink-900">{icon}</span>
      <div className={`min-w-0 flex-1 rounded-lg px-2 py-1 ${state === 'active' ? 'bg-brand/5' : ''}`}>
        <div className="flex items-baseline justify-between gap-2">
          <span className={`text-sm font-semibold ${state === 'idle' ? 'text-ink-400' : ''}`}>{def.title}</span>
          <span className="mono shrink-0 text-[11px] text-ink-400">{st?.ms != null ? secs(st.ms) : def.who}</span>
        </div>
        <div className="text-[11px] leading-snug text-ink-400">{st?.detail ?? def.what}</div>
        {st?.tx && (
          <a href={`${explorer ?? ''}/tx/${st.tx}`} target="_blank" rel="noreferrer"
            className="mono mt-0.5 inline-flex items-center gap-1 text-[11px] text-brand hover:underline">
            {short(st.tx, 10, 6)} <ExternalLink size={11} />
          </a>
        )}
      </div>
    </li>
  )
}
