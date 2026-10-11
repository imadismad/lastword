import { Blocks, Wifi, WifiOff } from 'lucide-react'
import { useLive, usePoll } from './lib/live'
import { post } from './lib/api'
import { Topology } from './components/Topology'
import { Quote } from './components/Quote'
import { Pipeline } from './components/Pipeline'
import { AttackLab, JournalPanel, RadioLog } from './components/Panels'

export default function App() {
  const live = useLive()
  const st = usePoll<any>('/api/state', 3000)
  const running = live.payment?.status === 'running'

  return (
    <div className="mx-auto flex min-h-full max-w-[1500px] flex-col gap-4 p-5">
      <header className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-3">
          <img src="/favicon.svg" alt="" className="h-9 w-9" />
          <div>
            <div className="text-xl font-extrabold tracking-tight">LASTWORD</div>
            <div className="text-xs text-ink-400">The agent proposes. The badge has the last word.</div>
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs">
          <Pill ok={live.connected} icon={live.connected ? <Wifi size={13} /> : <WifiOff size={13} />}
            text={live.connected ? 'live stream' : 'reconnecting…'} />
          <Pill ok={!!st?.chain?.up} icon={<Blocks size={13} />}
            text={st?.chain?.up ? `Avalanche L1 · chain ${st.chain.chain_id} · block ${st.chain.block}` : 'L1 unreachable (tunnel?)'} />
          <Pill ok={!!st?.badge?.provisioned} text={st?.badge?.provisioned ? 'badge ready' : 'badge provisioning…'} />
          {st?.badge?.provisioned && (
            <button onClick={() => post('/api/provision').catch(() => {})} disabled={running}
              className="rounded-full border border-ink-700 px-3 py-1 text-ink-300 transition hover:border-air hover:text-air disabled:opacity-40">
              re-provision
            </button>
          )}
        </div>
      </header>

      {st?.boot_error && (
        <div className="rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-bad">Hub: {st.boot_error}</div>
      )}

      <Topology live={live} st={st} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1.1fr_1.2fr]">
        <Quote busy={running} onPay={async p => { await post('/api/pay', { proposal: p }) }} />
        <Pipeline live={live} explorer={st?.chain?.explorer} />
        <div className="flex min-h-[520px] flex-col gap-4">
          <RadioLog events={live.events} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <AttackLab />
        <JournalPanel />
      </div>

      <footer className="pb-2 text-center text-[11px] text-ink-400">
        LASTWORD 2.0 · Dell gateway (nugget-1) ⇄ LoRa 868 MHz ⇄ badge station (nugget-3 + TROPIC01 badge) ·
        the contract trusts only the badge signature
      </footer>
    </div>
  )
}

function Pill({ ok, text, icon }: { ok: boolean; text: string; icon?: React.ReactNode }) {
  return (
    <span className={`flex items-center gap-1.5 rounded-full border px-3 py-1 ${ok ? 'border-ok/30 bg-ok/5 text-ok' : 'border-ink-700 text-ink-400'}`}>
      {icon ?? <span className={`h-1.5 w-1.5 rounded-full ${ok ? 'bg-ok' : 'bg-ink-400'}`} />}
      {text}
    </span>
  )
}
