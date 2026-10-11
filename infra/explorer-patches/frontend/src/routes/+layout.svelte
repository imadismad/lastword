<script lang="ts">
	import '../app.css';
	import Header from '$lib/components/layout/Header.svelte';
	import Footer from '$lib/components/layout/Footer.svelte';
	import PagePreloader from '$lib/components/PagePreloader.svelte';
	import BackToTop from '$lib/components/utilities/BackToTop.svelte';

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href="/favicon.svg" />
</svelte:head>

<div class="app-shell">
	<Header />
	<div class="main-content-wrapper">
		{@render children?.()}
	</div>
	<Footer />
</div>

<PagePreloader />
<BackToTop />

<style lang="postcss">
	@reference "$lib/../app.css";
	.app-shell {
		@apply flex min-h-screen w-full flex-col overflow-x-hidden;
		background: #f3f2ee;
	}
	.main-content-wrapper {
		@apply flex flex-1 flex-col gap-4 px-2 py-3 sm:py-5 sm:px-4;
		min-height: calc(100vh - 4rem);
		max-width: 1400px;
		margin: 0 auto;
		width: 100%;
	}
</style>
