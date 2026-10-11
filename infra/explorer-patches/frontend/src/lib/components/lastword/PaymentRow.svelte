<script lang="ts">
	import moment from 'moment';
	import Status from './Status.svelte';
	import { money, short, duration } from '$lib/lastword';
	import type { Payment } from '$lib/server/lastword';

	let { p }: { p: Payment } = $props();
</script>

<a href="/payment/{p.reqId}" class="lw-row">
	<div class="min-w-0">
		<div class="flex items-center gap-2">
			<span class="supplier">{p.supplier ?? 'Unknown beneficiary'}</span>
			{#if p.reasons.length}<span class="lw-tag">{p.reasons.join(' · ')}</span>{/if}
		</div>
		<div class="meta">
			req #{p.reqId} · {short(p.beneficiary, 6, 4)} ·
			{p.proposed ? moment(p.proposed.ts * 1000).fromNow() : ''}
		</div>
	</div>
	<div class="amount">{money(p.amount)}</div>
	<div class="steps" title="proposed → attested → paid">
		<span class:on={!!p.proposed}></span><span class:on={!!p.attested}></span><span class:on={!!p.approved}></span>
	</div>
	<div class="hidden w-24 text-right text-xs opacity-60 sm:block">{p.status === 'paid' ? duration(p.durationMs) : ''}</div>
	<Status status={p.status} />
</a>

<style>
	.lw-row {
		display: grid; grid-template-columns: minmax(0, 1fr) 130px 66px 76px 150px; align-items: center; gap: 18px;
		padding: 12px 16px; border-radius: 12px; background: #fff; border: 1px solid rgba(28, 27, 24, 0.08);
		transition: border-color .15s, box-shadow .15s;
	}
	.lw-row:hover { border-color: rgba(255, 90, 31, 0.45); box-shadow: 0 6px 18px -10px rgba(255, 90, 31, 0.45); }
	.supplier { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.meta { font-size: 12px; color: rgba(28, 27, 24, 0.55); margin-top: 2px; font-family: ui-monospace, 'Cascadia Code', monospace; }
	.amount { font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; text-align: right; }
	.lw-row > :global(.lw-status) { justify-self: end; }
	.steps { display: flex; gap: 4px; }
	.steps span { width: 18px; height: 6px; border-radius: 999px; background: rgba(28, 27, 24, 0.1); }
	.steps span.on { background: #ff5a1f; }
	@media (max-width: 640px) { .lw-row { grid-template-columns: minmax(0, 1fr) auto; } .steps { display: none; } }
</style>
