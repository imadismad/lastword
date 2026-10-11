<script lang="ts">
	import ChevronUpIcon from 'virtual:icons/hugeicons/arrow-up-01';

	let scrollY = 0;

	const scrollToTop = () => {
		window.scrollTo({
			top: 0,
			behavior: 'smooth'
		});
	};
</script>

<svelte:window on:scroll={() => (scrollY = window.scrollY)} />

<button
	class="back-to-top"
	class:hidden={scrollY <= 1}
	on:click={scrollToTop}
>
	<ChevronUpIcon class="text-2xl" />
</button>

<style>
	.back-to-top {
		position: fixed;
		right: 1rem;
		bottom: 1rem;
		display: flex;
		cursor: pointer;
		align-items: center;
		justify-content: center;
		border-radius: 1rem;
		padding: 0.5rem;
		background: rgba(255, 255, 255, 0.92);
		backdrop-filter: blur(8px);
		border: 1px solid rgba(28, 27, 24, 0.09);
		transition: all 0.2s ease;
		color: rgba(28, 27, 24, 0.75);
	}
	.back-to-top:hover {
		background: rgba(255, 90, 31, 0.15);
		border-color: rgba(255, 90, 31, 0.3);
		color: #ff5a1f;
	}
</style>
