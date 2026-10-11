<script lang="ts">
	let { status }: { status: string } = $props();
	const LABEL: Record<string, string> = {
		paid: 'Paid',
		attested: 'Delivery attested',
		proposed: 'Awaiting badge',
		refused: 'Refused',
		cancelled: 'Cancelled',
		expired: 'Expired · no payment'
	};
</script>

<span class="lw-status lw-status-{status}">
	<span class="dot"></span>{LABEL[status] ?? status}
</span>

<style>
	.lw-status {
		display: inline-flex; align-items: center; gap: 6px; white-space: nowrap;
		font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 999px;
		background: rgba(28, 27, 24, 0.06); color: rgba(28, 27, 24, 0.65);
	}
	.dot { width: 6px; height: 6px; border-radius: 999px; background: currentColor; }
	.lw-status-paid { background: rgba(21, 128, 61, 0.1); color: #15803d; }
	.lw-status-proposed, .lw-status-attested { background: rgba(255, 90, 31, 0.12); color: #c2410c; }
	.lw-status-refused { background: rgba(190, 18, 60, 0.1); color: #be123c; }
</style>
