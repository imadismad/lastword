<script lang="ts">
	import Status from './Status.svelte';
	import Timeline from './Timeline.svelte';
	import { ACTIONS, money, party, short } from '$lib/lastword';
	import type { Call } from '$lib/lastword';
	import type { Payment } from '$lib/server/lastword';

	let { call, payment, hash }: { call: Call; payment: Payment | null; hash: string } = $props();
	const action = $derived(ACTIONS[call.fn] ?? { title: call.fn, who: '', meaning: '' });
	const it = $derived(call.intent);
	const who = $derived(party(it?.beneficiary));
</script>

<section class="lw-tx">
	<div class="top">
		<div class="min-w-0">
			<div class="eyebrow">LASTWORD · {action.step ? `step ${action.step} of 3` : 'governance'}</div>
			<h2>{action.title}</h2>
			<p>{action.meaning}</p>
		</div>
		{#if payment}<Status status={payment.status} />{/if}
	</div>

	{#if it}
		<div class="facts">
			<div><span>Supplier</span><b>{who?.name ?? 'Unknown beneficiary'}</b></div>
			<div><span>Amount</span><b>{money(it.amount)}</b></div>
			<div><span>Signed by</span><b>{it.role === 'STOCK' ? 'Badge · STOCK role' : it.role === 'DAF' && call.fn !== 'propose' ? 'Badge · DAF role' : 'AI agent (proposal)'}</b></div>
			<div><span>Request</span><b><a href="/payment/{it.reqId}">#{it.reqId}</a></b></div>
			<div><span>Pay to</span><b class="mono">{short(it.beneficiary, 8, 6)}</b></div>
			<div><span>Flags</span><b>{it.reasons.length ? it.reasons.join(', ') : 'none'}</b></div>
		</div>
		{#if call.signature}
			<div class="sig">
				TROPIC01 P-256 signature · r {short(call.signature.r, 10, 8)} · s {short(call.signature.s, 10, 8)}
			</div>
		{/if}
	{/if}

	{#if payment}
		<details open>
			<summary>Where this transaction sits in payment #{payment.reqId}</summary>
			<div class="mt-3"><Timeline p={payment} current={hash} /></div>
		</details>
	{/if}
</section>

<style>
	.lw-tx {
		background: #fff; border: 1px solid rgba(28, 27, 24, 0.08); border-left: 6px solid #ff5a1f;
		border-radius: 18px; padding: 20px 22px; display: flex; flex-direction: column; gap: 14px;
	}
	.top { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
	.eyebrow { font-size: 12px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: #c2410c; }
	h2 { font-size: 24px; font-weight: 800; letter-spacing: -0.02em; margin-top: 2px; }
	p { color: rgba(28, 27, 24, 0.7); font-size: 14px; max-width: 760px; margin-top: 4px; line-height: 1.45; }
	.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 8px; }
	.facts div { background: #f8f7f3; border-radius: 10px; padding: 8px 12px; display: flex; flex-direction: column; gap: 2px; }
	.facts span { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: rgba(28, 27, 24, 0.5); }
	.facts b { font-weight: 700; }
	.facts a { color: #ff5a1f; }
	.mono, .sig { font-family: ui-monospace, 'Cascadia Code', monospace; }
	.sig { font-size: 12px; color: rgba(28, 27, 24, 0.6); }
	summary { cursor: pointer; font-weight: 700; font-size: 14px; }
</style>
