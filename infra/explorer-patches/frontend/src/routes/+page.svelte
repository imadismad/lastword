<script lang="ts">
	import BlocksNumberStat from '$lib/components/home/BlocksNumberStat.svelte';
	import TxsNumberStat from '$lib/components/home/TxsNumberStat.svelte';
	import GasPriceStat from '$lib/components/home/GasPriceStat.svelte';
	import ChainIdStat from '$lib/components/home/ChainIdStat.svelte';
	import LatestTxsChart from '$lib/components/home/LatestTxsChart.svelte';
	import LatestBlocksList from '$lib/components/home/LatestBlocksList.svelte';
	import LatestTxsList from '$lib/components/home/LatestTxsList.svelte';
	import InfoIcon from 'virtual:icons/hugeicons/information-square'
	import {isFullyIndexed} from "$lib/utils";
	import Summary from '$lib/components/lastword/Summary.svelte';
	import PaymentRow from '$lib/components/lastword/PaymentRow.svelte';

	export let data;
</script>

<svelte:head>
	<title>LASTWORD Explorer</title>
	<meta name="description" content="LASTWORD Explorer - every supplier payment traced on-chain, from the AI agent's proposal to the hardware badge's approval." />
</svelte:head>

<section class="lw-hero">
	<div class="lw-hero-text">
		<div class="lw-eyebrow">Traceability</div>
		<h1>Every supplier payment, end to end.</h1>
		<p>
			The AI agent proposes. The TROPIC01 badge attests and approves over LoRa, behind a PIN. The contract pays only
			what was proven. Each step is an on-chain transaction you can open and verify.
		</p>
	</div>
	{#if data.lastword}<Summary s={data.lastword} />{/if}
	{#if data.lastword?.latest?.length}
		<div class="lw-latest">
			<div class="lw-latest-head">
				<span>Latest payments</span>
				<a href="/payments" class="btn btn-primary btn-sm ml-auto">All payments</a>
			</div>
			<div class="flex flex-col gap-2">
				{#each data.lastword.latest as p (p.reqId)}<PaymentRow {p} />{/each}
			</div>
		</div>
	{/if}
</section>

{#if isFullyIndexed()}
	<div class="container mx-4 grid grid-cols-1 md:grid-cols-6 xl:grid-cols-12">
		<div class="col-span-4 flex w-full flex-col gap-2 rounded-xl bg-base-200">
			<GasPriceStat />
			<ChainIdStat />
		</div>
		<div class="col-span-4 flex w-full flex-col gap-2">
			<BlocksNumberStat />
			<TxsNumberStat txsCount={data.txsCount} />
		</div>
		<div class="col-span-4">
			<LatestTxsChart />
		</div>
	</div>
{:else}
	<div class="container mx-4 grid grid-cols-1 md:grid-cols-3">
		<GasPriceStat />
		<ChainIdStat />
		<BlocksNumberStat />
	</div>
	<div class="container flex items-center mx-4 !px-4">
		<InfoIcon class="text-xl min-w-10" />
		<span>This explorer is not fully indexed, which means the following lists may be outdated. However, you can always explore live data by searching for a transaction hash, address, etc.</span>
	</div>
{/if}

<div class="container grid flex-1 grid-cols-1 sm:grid-cols-2">
	<div class="list-col">
		<div class="title">
			<span>Latest Transactions</span>
			<a href="/txs" class="btn ml-auto">View All</a>
		</div>
		<LatestTxsList latestTxs={data.latestTxs} />
	</div>
	<div class="list-col">
		<div class="title">
			<span>Latest Blocks</span>
			<a href="/blocks" class="btn ml-auto">View All</a>
		</div>
		<LatestBlocksList latestBlocks={data.latestBlocks} />
	</div>
</div>

<style lang="postcss">
	@reference "$lib/../app.css";
	.lw-hero { display: flex; flex-direction: column; gap: 16px; }
	.lw-hero-text h1 { font-size: 34px; font-weight: 800; letter-spacing: -0.03em; line-height: 1.1; }
	.lw-hero-text p { color: rgba(28, 27, 24, 0.65); max-width: 760px; margin-top: 8px; font-size: 15px; line-height: 1.5; }
	.lw-eyebrow { font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: #ff5a1f; }
	.lw-latest-head { display: flex; align-items: center; margin-bottom: 8px; font-size: 18px; font-weight: 700; }
	.container {
		@apply gap-2 p-2;
		@apply mx-auto rounded-2xl;
		background: rgba(255, 255, 255, 0.92);
		border: 1px solid rgba(28, 27, 24, 0.06);
	}
	.list-col {
		@apply flex h-full w-full flex-col gap-2;
		> .title {
			@apply flex items-center gap-2 p-4 pl-6;
			@apply rounded-xl text-xl font-semibold tracking-tight;
			background: rgba(255, 255, 255, 0.92);
			border: 1px solid rgba(28, 27, 24, 0.06);
			span {
				background: linear-gradient(135deg, #1c1b18 0%, rgba(28, 27, 24, 0.75) 100%);
				-webkit-background-clip: text;
				-webkit-text-fill-color: transparent;
				background-clip: text;
			}
		}
	}
</style>
