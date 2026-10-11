<script lang="ts">
	import { money, duration } from '$lib/lastword';

	let { s }: { s: { total: number; paid: number; pending: number; volume: string; suppliers: number; medianMs: number | null } } = $props();
	const cards = $derived([
		{ k: 'Payments executed', v: String(s.paid), sub: `of ${s.total} requests` },
		{ k: 'Volume paid', v: money(s.volume), sub: `to ${s.suppliers} supplier${s.suppliers === 1 ? '' : 's'}` },
		{ k: 'Awaiting the badge', v: String(s.pending), sub: 'proposed, not yet approved' },
		{ k: 'Median end to end', v: duration(s.medianMs), sub: 'propose → paid, human PIN included' }
	]);
</script>

<div class="lw-summary">
	{#each cards as c}
		<div class="card">
			<div class="k">{c.k}</div>
			<div class="v">{c.v}</div>
			<div class="sub">{c.sub}</div>
		</div>
	{/each}
</div>

<style>
	.lw-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
	.card { background: #fff; border: 1px solid rgba(28, 27, 24, 0.08); border-radius: 14px; padding: 14px 16px; }
	.card:first-child { background: #1c1b18; color: #fff; border-color: #1c1b18; }
	.card:first-child .k, .card:first-child .sub { color: rgba(255, 255, 255, 0.6); }
	.card:first-child .v { color: #ff5a1f; }
	.k { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: rgba(28, 27, 24, 0.5); }
	.v { font-size: 26px; font-weight: 800; margin-top: 4px; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
	.sub { font-size: 12px; color: rgba(28, 27, 24, 0.55); }
</style>
