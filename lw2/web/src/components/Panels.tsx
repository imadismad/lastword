import { useState } from 'react'
import { BookLock, Bug, RadioTower, Repeat2, ShieldAlert, Zap } from 'lucide-react'
import type { Ev } from '../lib/api'
import { post, short } from '../lib/api'
import { usePoll } from '../lib/live'

const SHOWN = /^(radio\.(tx|rx|reply|timeout|ignored)|station\.(rx|tx)|badge\.|attack\.|agent\.verdict|pay\.done)/

function describe(e: Ev): { who: string; tone: string; text: string } {
  const rf = (x: Ev) => [x.rssi != null && `${x.rssi} dBm`, x.snr != null && `snr ${x.snr}`, x.hops != null && `${x.hops} hop`].filter(Boolean).join(' · ')
  switch (e.type) {
    case 'radio.tx': return { who: 'gateway', tone: 'text-air', text: `→ ${e.cmd} ${e.size} B on air (${e.airtime_ms} ms airtime)${e.label ? ' · ' + e.label : ''}` }
    case 'radio.rx': return { who: 'gateway', tone: 'text-violet', text: `← ${e.cmd} ${e.size} B from ${e.from} · ${rf(e)}` }
    case 'radio.reply': return { who: 'gateway', tone: 'text-ok', text: `${e.cmd} accepted as the answer · round trip ${e.rtt_ms} ms` }
    case 'radio.timeout': return { who: 'gateway', tone: 'text-bad', text: `no answer to ${e.cmd} after ${e.waited_s} s` }
    case 'radio.ignored': return { who: 'gateway', tone: 'text-wait', text: `ignored ${e.from ?? ''}: ${e.reason}${e.text ? ` — “${e.text}”` : ''}` }
    case 'station.rx': return { who: 'station', tone: 'text-air', text: `← ${e.cmd} ${e.size} B from ${e.src} · ${rf(e)}` }
    case 'station.tx': return { who: 'station', tone: 'text-violet', text: `→ ${e.cmd} ${e.size} B broadcast (${e.airtime_ms} ms airtime)` }
    case 'badge.awaiting_human': return { who: 'badge', tone: 'text-wait', text: `REQUEST on screen — waiting for the human (${e.timeout_s} s)` }
    case 'badge.answered': return { who: 'badge', tone: 'text-ok', text: `${e.to} → ${e.cmd} (${e.size} B) in ${(e.badge_ms / 1000).toFixed(1)} s` }
    case 'badge.online': return { who: 'badge', tone: 'text-ok', text: `online · stock ${e.stock}… · daf ${e.daf}…` }
    case 'badge.provisioned': return { who: 'badge', tone: 'text-ok', text: `provisioned over LoRa · keys match contract: ${e.keys_match_contract}` }
    case 'badge.provisioning': return { who: 'badge', tone: 'text-ink-300', text: 'provisioning over LoRa (HELLO + PROVISION)…' }
    case 'badge.provision_failed': return { who: 'badge', tone: 'text-bad', text: `provisioning failed: ${e.detail}` }
    case 'badge.error': return { who: 'badge', tone: 'text-bad', text: `${e.cmd}: ${e.detail}` }
    case 'attack.start': return { who: 'attack', tone: 'text-bad', text: `${e.kind}: injecting a ${e.size} B frame on air` }
    case 'attack.result': return { who: 'attack', tone: e.blocked ? 'text-ok' : 'text-bad', text: `${e.kind}: ${e.blocked ? 'BLOCKED by ' + e.by : 'NOT blocked'} — ${e.detail}` }
    case 'agent.verdict': return { who: 'agent', tone: 'text-ink-300', text: `verdict ${e.verdict} · ${e.supplier ?? '?'}` }
    case 'pay.done': return { who: 'contract', tone: e.status === 'paid' ? 'text-ok' : 'text-bad', text: e.status === 'paid' ? `PAID · ${(e.total_ms / 1000).toFixed(1)} s end to end` : `no payment · ${e.detail}` }
    default: return { who: e.type.split('.')[0], tone: 'text-ink-400', text: e.type }
  }
}

export function RadioLog({ events }: { events: Ev[] }) {
  const rows = events.filter(e => SHOWN.test(e.type)).slice(-80).reverse()
  return (
    <section className="panel flex min-h-0 flex-col p-5">
      <div className="label flex items-center gap-2"><RadioTower size={14} /> Live radio & badge log</div>
      <div className="mt-3 min-h-0 flex-1 overflow-y-auto pr-1">
        <table className="w-full text-xs">
          <tbody>
            {rows.map(e => {
              const d = describe(e)
              return (
                <tr key={e.id} className="border-b border-ink-800/80 align-top">
                  <td className="mono w-16 py-1.5 pr-2 text-ink-400">{new Date(e.ts * 1000).toLocaleTimeString('en-GB')}</td>
                  <td className="w-16 py-1.5 pr-2"><span className="rounded bg-ink-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-300">{d.who}</span></td>
                  <td className={`mono py-1.5 ${d.tone}`}>{d.text}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {rows.length === 0 && <div className="py-8 text-center text-xs text-ink-400">waiting for traffic…</div>}
      </div>
    </section>
  )
}

export function AttackLab() {
  const [res, setRes] = useState<Record<string, any>>({})
  const [busy, setBusy] = useState('')
  const run = async (kind: string) => {
    setBusy(kind)
    try { setRes(r => ({ ...r, [kind]: undefined })); const x = await post(`/api/attack/${kind}`); setRes(r => ({ ...r, [kind]: x })) }
    catch (e: any) { setRes(r => ({ ...r, [kind]: { error: e.message } })) }
    finally { setBusy('') }
  }
  const cards = [
    { kind: 'replay', icon: <Repeat2 size={16} />, title: 'Replay the last frame', text: 'Re-broadcast the last REQUEST exactly as captured on air.' },
    { kind: 'tamper', icon: <Bug size={16} />, title: 'Flip one bit in transit', text: 'Same frame, one bit changed inside the sealed ciphertext.' },
  ]
  return (
    <section className="panel p-5">
      <div className="label flex items-center gap-2"><ShieldAlert size={14} /> Attack lab · played live on the radio</div>
      <div className="mt-3 grid grid-cols-2 gap-3">
        {cards.map(c => {
          const r = res[c.kind]
          return (
            <div key={c.kind} className="rounded-xl border border-ink-700 bg-ink-850/60 p-3">
              <div className="flex items-center gap-2 text-sm font-semibold">{c.icon}{c.title}</div>
              <div className="mt-1 text-[11px] text-ink-400">{c.text}</div>
              <button onClick={() => run(c.kind)} disabled={!!busy}
                className="mt-2 flex items-center gap-1.5 rounded-lg border border-bad/40 px-2.5 py-1 text-xs text-bad transition hover:bg-bad/10 disabled:opacity-40">
                <Zap size={12} /> {busy === c.kind ? 'on air…' : 'Launch'}
              </button>
              {r && (
                <div className={`mono mt-2 text-[11px] ${r.error ? 'text-wait' : r.blocked ? 'text-ok' : 'text-bad'}`}>
                  {r.error ?? (r.blocked ? `BLOCKED by ${r.by} — ${r.detail}` : `NOT BLOCKED — ${r.detail}`)}
                </div>
              )}
            </div>
          )
        })}
      </div>
      <div className="mt-3 text-[11px] leading-relaxed text-ink-400">
        Also covered: hidden prompt injection & swapped payout address (pick the samples), and the
        <span className="text-ink-300"> STOCK-as-DAF</span> signature swap, checked by the contract on every payment.
        Text sent on the channel by any other node is logged as ignored and never reaches the agent.
      </div>
    </section>
  )
}

export function JournalPanel() {
  const j = usePoll<any>('/api/journal?n=8', 4000)
  return (
    <section className="panel p-5">
      <div className="flex items-center justify-between">
        <div className="label flex items-center gap-2"><BookLock size={14} /> Hash-chained evidence journal</div>
        {j && <span className={`text-[11px] font-semibold ${j.verified ? 'text-ok' : 'text-bad'}`}>{j.verified ? `✓ chain verified · ${j.count} entries` : `✗ broken at ${j.broken_at}`}</span>}
      </div>
      {j?.merkle_root && <div className="mono mt-2 text-[11px] text-ink-400">merkle root {short(j.merkle_root, 14, 10)}</div>}
      <ul className="mt-2 space-y-1">
        {(j?.tail ?? []).map((e: any) => (
          <li key={e.hash ?? e.seq} className="flex items-center justify-between gap-2 rounded-md bg-ink-850 px-2.5 py-1 text-[11px]">
            <span className="font-semibold text-ink-300">{e.type}</span>
            <span className="text-ink-400">{e.actor} · req {e.reqId}</span>
            <span className="mono text-ink-400">{short(e.hash, 6, 4)}</span>
          </li>
        ))}
        {j && j.count === 0 && <li className="text-xs text-ink-400">empty — every decision, refusals included, lands here</li>}
      </ul>
    </section>
  )
}
