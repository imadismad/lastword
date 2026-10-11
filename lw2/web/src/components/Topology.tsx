import { useEffect, useState } from 'react'
import { Cpu, KeyRound, Laptop, Radio, ShieldCheck, Usb } from 'lucide-react'
import type { Live } from '../lib/live'
import { secs } from '../lib/api'

type State = {
  devices?: { gateway: string; station: string; badge: string }
  radio?: { up: boolean; port: string; node: string; preset: string; stats: { tx: number; rx: number; ignored: number; airtime_ms: number } }
  station?: { node: string; nugget: string; badge: string; hardware: boolean; busy: string | null; age_s: number } | null
  badge?: { provisioned: boolean; keys_match_contract: boolean | null; pubkeys?: { stock: string; daf: string } }
}

export function Topology({ live, st }: { live: Live; st: State | null }) {
  const stationUp = !!st?.station && st.station.age_s < 12
  const g = live.link.gateway
  const sLink = live.link.station
  return (
    <section className="panel p-5">
      <div className="flex items-center justify-between">
        <div className="label">Hardware path · real LoRa</div>
        <div className="mono text-xs text-ink-400">
          EU_868 · {st?.radio?.preset ?? '—'} · PRIVATE_APP 256 · AES-256-GCM end to end
        </div>
      </div>

      <div className="mt-4 grid grid-cols-[1fr_1.5fr_1fr] items-stretch gap-4">
        {/* Gateway side */}
        <Node
          ok={!!st?.radio?.up}
          icon={<Laptop size={18} />}
          title="Gateway · Dell"
          lines={[
            ['agent + bridge', 'hub process'],
            ['nugget-1', `${st?.radio?.node ?? '—'} · ${st?.radio?.port ?? '—'}`],
          ]}
          foot="holds the gateway key · no approval power"
        />

        {/* Air link */}
        <div className="relative flex flex-col justify-center rounded-xl border border-ink-700 bg-ink-850/60 px-4 py-3">
          <div className="flex items-center justify-between text-xs text-ink-400">
            <span className="flex items-center gap-1.5"><Radio size={14} className="text-air" /> 868 MHz LoRa</span>
            <span className="mono">{live.link.gateway.hops == null ? 'direct link' : live.link.gateway.hops === 0 ? 'direct · 0 hop' : `${live.link.gateway.hops} hop(s)`}</span>
          </div>
          <div className="relative my-3 h-10">
            <div className="absolute inset-x-[4%] top-1/2 h-px -translate-y-1/2 bg-gradient-to-r from-air/10 via-air/60 to-air/10" />
            <div className="absolute inset-x-[4%] top-1/2 h-px -translate-y-1/2 border-t border-dashed border-air/30" />
            {live.packets.map(p => (
              <div
                key={p.key}
                className={`absolute top-1/2 -translate-y-1/2 ${p.dir === 'out' ? 'packet-r' : 'packet-l'}`}
                style={{ ['--dur' as any]: `${p.dur}s` }}
              >
                <div className={`mono whitespace-nowrap rounded-md px-2 py-0.5 text-[10px] font-semibold shadow-lg ${p.dir === 'out' ? 'bg-air text-ink-950 shadow-air/40' : 'bg-violet text-ink-950 shadow-violet/40'}`}>
                  {p.label} · {p.size}B
                </div>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-4 gap-2 text-center">
            <Metric k="RSSI" v={g.rssi != null ? `${g.rssi} dBm` : '—'} />
            <Metric k="SNR" v={g.snr != null ? `${g.snr} dB` : '—'} />
            <Metric k="Round trip" v={g.rtt ? secs(g.rtt) : '—'} />
            <Metric k="Airtime" v={st?.radio ? secs(st.radio.stats.airtime_ms) : '—'} />
          </div>
          <div className="mt-2 text-center text-[11px] text-ink-400">
            station hears gateway at {sLink.rssi != null ? `${sLink.rssi} dBm / ${sLink.snr} dB` : '—'} · frames ignored: {st?.radio?.stats.ignored ?? 0}
          </div>
        </div>

        {/* Badge side */}
        <Node
          ok={stationUp}
          icon={<KeyRound size={18} />}
          title="Badge station"
          lines={[
            ['nugget-3', `${st?.station?.node ?? '—'} · ${st?.station?.nugget ?? '—'}`],
            ['badge', st?.station ? (st.station.hardware ? `TROPIC01 · ${st.station.badge}` : st.station.badge) : '—'],
          ]}
          foot="no key · moves sealed bytes only"
          warn={st?.station && !st.station.hardware ? 'software badge (fallback)' : undefined}
        />
      </div>

      <div className="mt-4 grid grid-cols-[1fr_1.5fr_1fr] gap-4">
        <Trust ok icon={<Cpu size={14} />} text="AI zone: reads & proposes, never touches the radio" />
        <Trust ok={!!live.provisioned || !!st?.badge?.provisioned} icon={<Usb size={14} />}
          text={st?.badge?.provisioned || live.provisioned ? 'badge provisioned over LoRa (frame key, chain, contract, gateway pubkey)' : 'provisioning the badge over LoRa…'} />
        <Trust ok={st?.badge?.keys_match_contract === true} icon={<ShieldCheck size={14} />}
          text={st?.badge?.keys_match_contract ? 'badge keys = keys registered in the contract' : 'badge keys not yet checked against the contract'} />
      </div>

      <EPaper live={live} />
    </section>
  )
}

function Node({ ok, icon, title, lines, foot, warn }: { ok: boolean; icon: React.ReactNode; title: string; lines: [string, string][]; foot: string; warn?: string }) {
  return (
    <div className="relative rounded-xl border border-ink-700 bg-ink-850/60 p-4">
      <div className="flex items-center gap-2">
        <span className="relative flex h-2.5 w-2.5">
          {ok && <span className="ring absolute inline-flex h-full w-full rounded-full bg-ok" />}
          <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${ok ? 'bg-ok' : 'bg-bad'}`} />
        </span>
        <span className="text-ink-300">{icon}</span>
        <span className="font-semibold">{title}</span>
      </div>
      <dl className="mt-3 space-y-1.5 text-xs">
        {lines.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2">
            <dt className="text-ink-400">{k}</dt>
            <dd className="mono truncate text-ink-100">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-3 text-[11px] text-ink-400">{foot}</div>
      {warn && <div className="mt-1 text-[11px] font-semibold text-wait">{warn}</div>}
    </div>
  )
}

const Metric = ({ k, v }: { k: string; v: string }) => (
  <div className="rounded-lg bg-ink-900/70 px-2 py-1.5">
    <div className="text-[10px] uppercase tracking-wider text-ink-400">{k}</div>
    <div className="mono text-sm text-ink-100">{v}</div>
  </div>
)

const Trust = ({ ok, icon, text }: { ok: boolean; icon: React.ReactNode; text: string }) => (
  <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${ok ? 'border-ok/25 bg-ok/5 text-ok' : 'border-ink-700 text-ink-400'}`}>
    {icon}<span>{text}</span>
  </div>
)

/** A mirror of what the human sees on the badge's e-paper during an approval. */
function EPaper({ live }: { live: Live }) {
  const [now, setNow] = useState(Date.now() / 1000)
  useEffect(() => { const h = setInterval(() => setNow(Date.now() / 1000), 250); return () => clearInterval(h) }, [])
  const a = live.awaiting
  if (!a) return null
  const left = Math.max(0, Math.ceil(a.timeout - (now - a.since)))
  const role = live.payment?.steps.daf?.state === 'active' ? 'DAF' : 'STOCK'
  const pct = left / a.timeout
  return (
    <div className="mt-4 flex items-center gap-5 rounded-xl border border-wait/40 bg-wait/5 p-4">
      <svg width="64" height="64" viewBox="0 0 64 64" className="shrink-0">
        <circle cx="32" cy="32" r="27" fill="none" stroke="#2a3a5a" strokeWidth="6" />
        <circle cx="32" cy="32" r="27" fill="none" stroke="var(--color-wait)" strokeWidth="6" strokeLinecap="round"
          strokeDasharray={`${2 * Math.PI * 27 * pct} 999`} transform="rotate(-90 32 32)" />
        <text x="32" y="37" textAnchor="middle" className="mono" fill="#e6ebf5" fontSize="15" fontWeight="700">{left}</text>
      </svg>
      <div>
        <div className="label text-wait">Human on the badge · role {role}</div>
        <div className="mt-1 text-lg font-semibold">Read the e-paper, then press <Key>Y</Key> → PIN → <Key>Y</Key></div>
        <div className="text-xs text-ink-400">The PIN comes from the physical keypad, never from the network. The badge signs inside the TROPIC01.</div>
      </div>
    </div>
  )
}

const Key = ({ children }: { children: React.ReactNode }) => (
  <span className="mono mx-0.5 inline-block rounded-md border border-ink-600 bg-ink-800 px-1.5 text-sm">{children}</span>
)
