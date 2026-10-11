<script lang="ts">
	import moment from 'moment';
	import Status from '$lib/components/lastword/Status.svelte';
	import Timeline from '$lib/components/lastword/Timeline.svelte';
	import Address from '$lib/components/entity/common/Address.svelte';
	import { money, duration, party } from '$lib/lastword';

	let { data } = $props();
	const p = $derived(data.p);
	const who = $derived(party(p.beneficiary));
</script>

<svelte:head><title>Payment #{p.reqId} · {p.supplier ?? 'unknown'} · LASTWORD Explorer</title></svelte:head>

<a href="/payments" class="back">← All payments</a>

<section class="hero">
	<div class="min-w-0">
		<div class="eyebrow">Payment request #{p.reqId}</div>
		<h1>{p.supplier ?? 'Unknown beneficiary'}</h1>
		<div class="sub">{who?.detail ?? 'not in the supplier directory'}</div>
	</div>
	<div class="right">
		<div class="amount">{money(p.amount)}</div>
		<Status status={p.status} />
	</div>
</section>

<div class="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
	<section class="panel">
		<h2>Audit trail</h2>
		<p class="lead">
			Three different keys, three on-chain steps. The AI agent can only do the first one; only the hardware badge's
			signatures move funds.
		</p>
		<Timeline {p} />
		{#if p.status === 'paid'}
			<div class="ok">
				Paid {duration(p.durationMs)} after the proposal ·
				{#if p.transfer}{money(p.transfer.value)} moved from the treasury vault to {p.supplier ?? 'the supplier'}{/if}
			</div>
		{:else if p.status === 'expired'}
			<div class="bad">The deadline passed before the badge approved it: the contract will never pay this request (criterion C8).</div>
		{/if}
	</section>

	<div class="flex flex-col gap-4">
		<section class="panel">
			<h2>What the badge displayed and signed</h2>
			<dl>
				<dt>Beneficiary</dt><dd><Address address={p.beneficiary} /></dd>
				<dt>Amount</dt><dd class="mono">{money(p.amount)} <span class="opacity-50">({Number(p.amount).toLocaleString('en-US')} units)</span></dd>
				<dt>Deadline</dt><dd>{moment.utc(p.deadline * 1000).format('MMM D YYYY, HH:mm:ss [UTC]')}</dd>
				<dt>Agent flags</dt><dd>{p.reasons.length ? p.reasons.join(', ') : 'none'}</dd>
				<dt>Policy version</dt><dd>v{p.policy}</dd>
			</dl>
		</section>
		<section class="panel">
			<h2>Verify it yourself</h2>
			<dl>
				<dt>Intent digest</dt><dd class="mono break-all">{p.digest}</dd>
				<dt>Quote hash</dt><dd class="mono break-all">{p.quoteHash}</dd>
				{#if p.transfer}
					<dt>Funds moved</dt>
					<dd><Address address={p.transfer.from} /> → <Address address={p.transfer.to} /></dd>
				{/if}
			</dl>
			<p class="note">
				digest = SHA-256("LASTWORD-v1" ‖ chainId ‖ contract ‖ intent). The contract recomputes it from the parameters it
				executes. The badge signatures in the trail are checked against the STOCK and DAF P-256 keys registered on-chain.
			</p>
		</section>
	</div>
</div>

<style>
	.back { font-size: 13px; color: rgba(28, 27, 24, 0.6); }
	.back:hover { color: #ff5a1f; }
	.hero {
		display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 16px;
		background: #fff; border: 1px solid rgba(28, 27, 24, 0.08); border-radius: 18px; padding: 22px 24px;
		border-left: 6px solid #ff5a1f;
	}
	.eyebrow { font-size: 12px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: #c2410c; }
	h1 { font-size: 30px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.15; margin-top: 2px; }
	.sub { color: rgba(28, 27, 24, 0.55); font-size: 14px; }
	.right { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }
	.amount { font-size: 32px; font-weight: 800; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
	.panel { background: #fff; border: 1px solid rgba(28, 27, 24, 0.08); border-radius: 18px; padding: 20px; }
	h2 { font-size: 13px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; color: rgba(28, 27, 24, 0.55); margin-bottom: 10px; }
	.lead { font-size: 14px; color: rgba(28, 27, 24, 0.7); margin-bottom: 14px; }
	dl { display: grid; grid-template-columns: auto 1fr; gap: 8px 16px; font-size: 14px; align-items: center; }
	dt { color: rgba(28, 27, 24, 0.55); white-space: nowrap; }
	.mono { font-family: ui-monospace, 'Cascadia Code', monospace; font-size: 12.5px; }
	.note { margin-top: 12px; font-size: 12px; color: rgba(28, 27, 24, 0.55); line-height: 1.5; }
	.ok, .bad { margin-top: 6px; border-radius: 12px; padding: 12px 14px; font-weight: 600; font-size: 14px; }
	.ok { background: rgba(21, 128, 61, 0.08); color: #15803d; }
	.bad { background: rgba(190, 18, 60, 0.07); color: #be123c; }
</style>
