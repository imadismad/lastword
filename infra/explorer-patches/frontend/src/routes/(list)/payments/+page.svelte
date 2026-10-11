<script lang="ts">
	import PaymentRow from '$lib/components/lastword/PaymentRow.svelte';
	import Summary from '$lib/components/lastword/Summary.svelte';

	let { data } = $props();
	const FILTERS = [
		['all', 'All'],
		['paid', 'Paid'],
		['proposed', 'Awaiting badge'],
		['attested', 'Attested'],
		['expired', 'Expired'],
		['refused', 'Refused']
	];
</script>

<svelte:head><title>Payments · LASTWORD Explorer</title></svelte:head>

<section class="lw-page">
	<div class="head">
		<div>
			<h1>Supplier payments</h1>
			<p>
				Every payment request the AI agent made, and what the hardware badge and the contract did with it.
				Rebuilt live from the contract's on-chain events.
			</p>
		</div>
	</div>

	{#if data.summary}<Summary s={data.summary} />{/if}

	<div class="filters">
		{#each FILTERS as [k, label]}
			<a href="?status={k}" class:active={data.filter === k}>{label}</a>
		{/each}
	</div>

	<div class="flex flex-col gap-2">
		{#each data.payments as p (p.reqId)}
			<PaymentRow {p} />
		{:else}
			<div class="empty">{data.error ? `Chain unreachable: ${data.error}` : 'No payment in this category yet.'}</div>
		{/each}
	</div>
</section>

<style>
	.lw-page { display: flex; flex-direction: column; gap: 18px; }
	.head h1 { font-size: 28px; font-weight: 800; letter-spacing: -0.02em; }
	.head p { color: rgba(28, 27, 24, 0.6); max-width: 720px; margin-top: 4px; }
	.filters { display: flex; flex-wrap: wrap; gap: 6px; }
	.filters a {
		font-size: 13px; font-weight: 600; padding: 6px 14px; border-radius: 999px;
		background: #fff; border: 1px solid rgba(28, 27, 24, 0.1); color: rgba(28, 27, 24, 0.7);
	}
	.filters a.active { background: #1c1b18; border-color: #1c1b18; color: #fff; }
	.empty { padding: 40px; text-align: center; color: rgba(28, 27, 24, 0.5); background: #fff; border-radius: 12px; }
</style>
