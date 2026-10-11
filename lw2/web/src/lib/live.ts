import { useEffect, useReducer, useRef } from 'react'
import { api, type Ev } from './api'

export type StepState = 'idle' | 'active' | 'done' | 'error'
export type Step = { state: StepState; ms?: number; tx?: string; detail?: string }
export type Payment = {
  reqId: number
  supplier?: string
  beneficiary?: string
  amount?: number
  steps: Record<string, Step>
  status?: 'running' | 'paid' | 'refused' | 'error'
  totalMs?: number
  detail?: string
}
export type Packet = { key: number; dir: 'out' | 'in'; label: string; size: number; dur: number }
export type Link = { rssi?: number; snr?: number; hops?: number | null; rtt?: number; at?: number }

export type Live = {
  connected: boolean
  events: Ev[]
  payment: Payment | null
  packets: Packet[]
  link: { gateway: Link; station: Link }
  awaiting: { since: number; timeout: number } | null
  badgeBusy: string | null
  provisioned: boolean
  airtimeMs: number
}

const initial: Live = {
  connected: false, events: [], payment: null, packets: [],
  link: { gateway: {}, station: {} }, awaiting: null, badgeBusy: null,
  provisioned: false, airtimeMs: 0,
}

type Action = { t: 'ev'; e: Ev } | { t: 'conn'; v: boolean } | { t: 'drop'; key: number }

function reduce(s: Live, a: Action): Live {
  if (a.t === 'conn') return { ...s, connected: a.v }
  if (a.t === 'drop') return { ...s, packets: s.packets.filter(p => p.key !== a.key) }
  const e = a.e
  const n: Live = { ...s, events: [...s.events.slice(-399), e] }
  switch (e.type) {
    case 'radio.tx':
      if (e.hist) break  // history replayed on connect: no animation
      n.packets = [...s.packets, { key: e.id, dir: 'out', label: e.cmd, size: e.size, dur: flight(e.airtime_ms) }]
      n.airtimeMs = s.airtimeMs + (e.airtime_ms || 0)
      break
    case 'station.tx':
      if (e.hist) break
      n.packets = [...s.packets, { key: e.id, dir: 'in', label: e.cmd, size: e.size, dur: flight(e.airtime_ms) }]
      n.airtimeMs = s.airtimeMs + (e.airtime_ms || 0)
      break
    case 'radio.rx':
    case 'radio.reply':
      n.link = { ...s.link, gateway: { rssi: e.rssi, snr: e.snr, hops: e.hops, rtt: e.rtt_ms ?? s.link.gateway.rtt, at: e.ts } }
      break
    case 'station.rx':
      n.link = { ...s.link, station: { rssi: e.rssi, snr: e.snr, hops: e.hops, at: e.ts } }
      n.badgeBusy = e.cmd
      break
    case 'badge.awaiting_human':
      if (Date.now() / 1000 - e.ts > e.timeout_s) break  // stale, replayed from history
      n.awaiting = { since: e.ts, timeout: e.timeout_s }
      break
    case 'badge.answered':
    case 'badge.error':
      n.awaiting = null
      n.badgeBusy = null
      break
    case 'badge.provisioned':
      n.provisioned = true
      break
    case 'pay.start':
      n.payment = { reqId: e.reqId, supplier: e.supplier, beneficiary: e.beneficiary, amount: e.amount, steps: {}, status: 'running' }
      break
    case 'pay.step':
      if (s.payment && s.payment.reqId === e.reqId) {
        const prev = s.payment.steps[e.step] || { state: 'idle' }
        n.payment = {
          ...s.payment,
          steps: { ...s.payment.steps, [e.step]: { ...prev, state: e.state, ms: e.ms ?? prev.ms, tx: e.tx ?? prev.tx, detail: e.detail ?? prev.detail } },
        }
        if (e.state !== 'active' && (e.step === 'stock' || e.step === 'daf')) n.awaiting = null
      }
      break
    case 'pay.done':
      if (s.payment && s.payment.reqId === e.reqId)
        n.payment = { ...s.payment, status: e.status, totalMs: e.total_ms, detail: e.detail }
      n.awaiting = null
      break
  }
  return n
}

// a frame takes its airtime on the air; keep the animation readable but proportional
const flight = (ms?: number) => Math.min(Math.max((ms || 800) / 1000, 0.9), 2.4)

export function useLive(): Live {
  const [s, dispatch] = useReducer(reduce, initial)
  const seen = useRef(new Set<number>())

  useEffect(() => {
    let ws: WebSocket | null = null
    let stop = false
    const open = () => {
      ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`)
      ws.onopen = () => dispatch({ t: 'conn', v: true })
      ws.onclose = () => { dispatch({ t: 'conn', v: false }); if (!stop) setTimeout(open, 1500) }
      ws.onmessage = m => {
        const msg = JSON.parse(m.data)
        const list: Ev[] = msg.type === 'hello' ? msg.recent : [msg]
        for (const e of list) {
          if (seen.current.has(e.id)) continue
          seen.current.add(e.id)
          // replayed history must not re-launch packet animations
          dispatch({ t: 'ev', e: msg.type === 'hello' ? { ...e, hist: true } : e })
          if (msg.type !== 'hello' && /\.tx$/.test(e.type)) {
            const key = e.id
            setTimeout(() => dispatch({ t: 'drop', key }), 2600)
          }
        }
      }
    }
    open()
    return () => { stop = true; ws?.close() }
  }, [])

  return s
}

export function usePoll<T>(path: string, ms: number): T | null {
  const [v, set] = useReducer((_: T | null, x: T | null) => x, null)
  useEffect(() => {
    let on = true
    const tick = () => api<T>(path).then(x => on && set(x)).catch(() => {})
    tick()
    const h = setInterval(tick, ms)
    return () => { on = false; clearInterval(h) }
  }, [path, ms])
  return v
}
