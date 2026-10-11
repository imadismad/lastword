<script lang="ts">
	import { PUBLIC_RPC_URL } from '$env/static/public';
	import Searchbar from '$lib/components/layout/Searchbar.svelte';
	import CheckIcon from 'virtual:icons/hugeicons/checkmark-square-01';
	import CopyIcon from 'virtual:icons/hugeicons/copy-01';
	import { page } from '$app/state';

	let isCopied = false;

	const copyRpc = async () => {
		await navigator.clipboard.writeText(PUBLIC_RPC_URL);
		isCopied = true;
		setTimeout(() => {
			isCopied = false;
		}, 1200);
	};
</script>

<div class="header-nav">
	<div class="container mx-auto flex items-center gap-2">
		<a href="/" class="logo-link">
			<img src="/lastword.svg" alt="LASTWORD" height="34" width="34" />
			<span class="logo-text">LASTWORD <span class="gradient-text hidden xl:inline">Explorer</span></span>
		</a>
		<nav class="main-nav">
			<a href="/payments" class:active={page.url.pathname.startsWith('/payment')}>Payments</a>
			<a href="/txs" class:active={page.url.pathname.startsWith('/tx')}>Transactions</a>
			<a href="/blocks" class:active={page.url.pathname.startsWith('/block')}>Blocks</a>
		</nav>
		<div class="header-actions ml-auto">
			<Searchbar class="min-w-1/3 flex-1" />
			<button class="rpc-btn" on:click={copyRpc} title="Copy RPC URL">
				{#if isCopied}
					<CheckIcon class="text-lg" />
					<span>Copied</span>
				{:else}
					<CopyIcon class="text-lg" />
					<span>Copy RPC</span>
				{/if}
			</button>
		</div>
	</div>
</div>

<style lang="postcss">
	@reference "$lib/../app.css";
	.header-nav {
		@apply sticky top-0 z-40 h-[4rem];
		background: rgba(243, 242, 238, 0.8);
		backdrop-filter: blur(20px);
		-webkit-backdrop-filter: blur(20px);
		border-bottom: 1px solid rgba(28, 27, 24, 0.09);
		display: flex;
		align-items: center;
	}
	.logo-link {
		@apply flex items-center gap-3 rounded-xl p-2 pr-4 pl-3 transition-all duration-200;
		&:hover {
			background: rgba(28, 27, 24, 0.06);
		}
	}
	.logo-text {
		@apply text-lg font-semibold tracking-tight whitespace-nowrap;
	}
	.main-nav {
		@apply ml-4 hidden items-center gap-1 lg:flex;
		a {
			@apply rounded-full px-3 py-1.5 text-sm font-medium transition-colors duration-150;
			color: rgba(28, 27, 24, 0.62);
			&:hover { color: #1c1b18; background: rgba(28, 27, 24, 0.05); }
			&.active { color: #ff5a1f; background: rgba(255, 90, 31, 0.1); }
		}
	}
	.header-actions {
		@apply flex items-center gap-2;
		width: min(100%, 44rem);
		max-width: 44rem;
		flex-wrap: wrap;
	}
	.header-actions > :global(.searchbar-wrapper) {
		flex: 1 1 70%;
		min-width: 0;
	}
	.validators-link {
		@apply inline-flex items-center rounded-full px-3 py-2 text-sm font-medium transition-all duration-200;
		background: rgba(255, 255, 255, 0.92);
		border: 1px solid rgba(28, 27, 24, 0.09);
		color: rgba(28, 27, 24, 0.82);
		white-space: nowrap;
		&:hover {
			border-color: rgba(255, 90, 31, 0.24);
			background: rgba(255, 90, 31, 0.08);
			color: #1c1b18;
		}
	}
	.rpc-btn {
		@apply inline-flex items-center gap-2 rounded-full px-3 py-2 text-sm font-medium transition-all duration-200;
		background: rgba(255, 255, 255, 0.92);
		border: 1px solid rgba(28, 27, 24, 0.09);
		color: rgba(28, 27, 24, 0.82);
		white-space: nowrap;
		min-width: 0;
		justify-content: center;
		&:hover {
			border-color: rgba(255, 90, 31, 0.24);
			background: rgba(255, 90, 31, 0.08);
			color: #1c1b18;
		}
	}
	@media (max-width: 768px) {
		.header-actions {
			width: 100%;
			max-width: 100%;
			gap: 0.5rem;
		}
		.header-actions > :global(.searchbar-wrapper) {
			flex: 1 1 100%;
		}
		.validators-link {
			order: 2;
			flex: 1 1 auto;
			justify-content: center;
		}
		.rpc-btn {
			order: 3;
			flex: 1 1 auto;
			min-width: 120px;
			justify-content: center;
		}
		.rpc-btn span {
			display: none;
		}
	}
</style>
