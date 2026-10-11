<script lang="ts">
	import { afterNavigate, beforeNavigate } from '$app/navigation';
	import { fade } from 'svelte/transition';

	export let visible = false;

	let progression = 0;
	let it: any;
	beforeNavigate(() => {
		progression = 0;
		visible = true;
		setTimeout(() => {
			it = setInterval(() => {
				progression += 1;
			}, 20);
		}, 100);
	});

	afterNavigate(() => {
		visible = false;
		progression = 100;
		setTimeout(() => {
			progression = 0;
			clearInterval(it);
		}, 100);
	});
</script>

{#if visible}
	<div
		class="fixed top-0 left-0 z-[60] h-[3px] max-w-full"
		out:fade
		style="width:{progression}%; background: linear-gradient(90deg, #ff5a1f, #ff8a4c);"
	></div>
{/if}
