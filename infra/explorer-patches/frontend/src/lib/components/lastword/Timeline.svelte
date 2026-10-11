<script lang="ts">
	import moment from 'moment';
	import { ACTIONS, short, duration } from '$lib/lastword';
	import type { Payment, Step } from '$lib/server/lastword';

	let { p, current = '' }: { p: Payment; current?: string } = $props();

	const steps: { key: 'proposed' | 'attested' | 'approved'; fn: string }[] = [
		{ key: 'proposed', fn: 'propose' },
		{ key: 'attested', fn: 'attestDelivery' },
		{ key: 'approved', fn: 'approve' }
	];
	const gap = (a?: Step, b?: Step) => (a && b ? duration((b.ts - a.ts) * 1000) : null);
</script>

<ol class="lw-timeline">
	{#each steps as s, i}
		{@const st = p[s.key]}
		{@const a = ACTIONS[s.fn]}
		<li class:done={!!st} class:here={st && st.tx === current}>
			<div class="marker">{st ? '✓' : i + 1}</div>
			<div class="body">
				<div class="flex flex-wrap items-baseline justify-between gap-2">
					<span class="title">{a.title}</span>
					{#if st}
						<span class="when">{moment.utc(st.ts * 1000).format('MMM D, HH:mm:ss [UTC]')}{#if i > 0 && gap(p[steps[i - 1].key], st)} · +{gap(p[steps[i - 1].key], st)}{/if}</span>
					{:else}
						<span class="when">{p.status === 'expired' ? 'never happened (expired)' : 'pending'}</span>
					{/if}
				</div>
				<div class="who">{a.who}</div>
				<p class="meaning">{a.meaning}</p>
				{#if st}
					<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
						<a class="tx" href="/tx/{st.tx}">tx {short(st.tx, 10, 8)}</a>
						<span class="opacity-60">block #{st.block}</span>
						{#if st.signature}
							<span class="sig" title="P-256 signature produced inside the TROPIC01 (low-s normalised)">
								badge sig r {short(st.signature.r, 6, 4)} · s {short(st.signature.s, 6, 4)}
							</span>
						{/if}
					</div>
				{/if}
			</div>
		</li>
	{/each}
</ol>

<style>
	.lw-timeline { display: flex; flex-direction: column; gap: 0; }
	li { display: grid; grid-template-columns: 32px 1fr; gap: 14px; position: relative; padding-bottom: 18px; }
	li:not(:last-child)::before {
		content: ''; position: absolute; left: 15px; top: 32px; bottom: 0; width: 2px; background: rgba(28, 27, 24, 0.1);
	}
	li.done:not(:last-child)::before { background: rgba(255, 90, 31, 0.5); }
	.marker {
		width: 32px; height: 32px; border-radius: 999px; display: grid; place-items: center; font-weight: 700; font-size: 13px;
		background: #fff; border: 2px solid rgba(28, 27, 24, 0.15); color: rgba(28, 27, 24, 0.45);
	}
	li.done .marker { background: #ff5a1f; border-color: #ff5a1f; color: #fff; }
	li.here .body { background: rgba(255, 90, 31, 0.06); border-color: rgba(255, 90, 31, 0.35); }
	.body { border: 1px solid rgba(28, 27, 24, 0.08); background: #fff; border-radius: 12px; padding: 10px 14px; }
	.title { font-weight: 700; }
	.when { font-size: 12px; color: rgba(28, 27, 24, 0.55); font-variant-numeric: tabular-nums; }
	.who { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #c2410c; margin-top: 2px; }
	.meaning { font-size: 13px; color: rgba(28, 27, 24, 0.7); margin: 4px 0 6px; line-height: 1.45; }
	.tx { color: #ff5a1f; font-family: ui-monospace, 'Cascadia Code', monospace; }
	.tx:hover { text-decoration: underline; }
	.sig { font-family: ui-monospace, 'Cascadia Code', monospace; color: rgba(28, 27, 24, 0.6); }
</style>
