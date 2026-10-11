<script lang="ts">
	import Pagination from '$lib/components/data/Pagination.svelte';
	import { formatAddress, formatCdkAmount } from '$lib/utils';

	export let rewards: any = {};
	export let totalPages: number = 1;

	$: rows = Array.isArray(rewards?.rows) ? rewards.rows : [];
	$: summary = rewards?.summary ?? {};
</script>

<div class="flex flex-col gap-4">
	<div class="stats-wrapper">
		<div class="stat-card">
			<div class="stat-label">Blocks Produced</div>
			<div class="stat-value">{summary?.blocksProduced ?? 0}</div>
		</div>
		<div class="stat-card">
			<div class="stat-label">Total Rewards (CDK)</div>
			<div class="stat-value">{formatCdkAmount(summary?.totalRewardCDK ?? 0, { maxDecimals: 0 })}</div>
		</div>
	</div>

	<div class="card bg-base-100 border border-base-300 overflow-hidden">
		<div class="overflow-x-auto">
			<table class="table table-zebra">
				<thead>
					<tr>
						<th>Block</th>
						<th>Time</th>
						<th>Tx Count</th>
						<th>Gas Used</th>
						<th>Reward (CDK)</th>
						<th>Validator</th>
					</tr>
				</thead>
				<tbody>
					{#if rows.length}
						{#each rows as row}
							<tr>
								<td><a href="/block/{row.blockNumber}" class="link">#{row.blockNumber}</a></td>
								<td>{new Date((row.timestamp ?? 0) * 1000).toLocaleString()}</td>
								<td>{row.txCount ?? 0}</td>
								<td>{row.gasUsed ?? 0}</td>
								<td>{formatCdkAmount(row.rewardCDK ?? 0, { maxDecimals: 3 })}</td>
								<td><a href="/address/{row.miner}" class="link">{formatAddress(row.miner ?? '', 8)}</a></td>
							</tr>
						{/each}
					{:else}
						<tr>
							<td colspan="6" class="text-center py-10 text-base-content/70">No validator rewards indexed for this address.</td>
						</tr>
					{/if}
				</tbody>
			</table>
		</div>
	</div>

	{#if totalPages > 1}
		<Pagination class="mx-auto" total={totalPages} hash="#validator-rewards" />
	{/if}
</div>

<style lang="postcss">
	.stats-wrapper {
		display: grid;
		grid-template-columns: 1fr;
		gap: 0.75rem;
	}
	.stat-card {
		border-radius: 0.75rem;
		border: 1px solid rgba(28, 27, 24, 0.16);
		background: var(--color-base-100);
		padding: 1rem;
	}
	.stat-label {
		font-size: 0.875rem;
		opacity: 0.7;
	}
	.stat-value {
		font-size: 1.25rem;
		font-weight: 600;
	}
	@media (min-width: 768px) {
		.stats-wrapper {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
</style>
