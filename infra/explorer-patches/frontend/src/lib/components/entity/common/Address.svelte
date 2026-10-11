<script lang="ts">
	import { onMount } from 'svelte';
	import ClipboardCopyBtn from '$lib/components/utilities/ClipboardCopyBtn.svelte';
	import { party } from '$lib/lastword';

	import ContractIcon from 'virtual:icons/hugeicons/file-01';
	import WalletIcon from 'virtual:icons/hugeicons/wallet-01';

	export let address;
	export let kind = 'address';
	export let href = '#';
	export let isLoading = true;

	let entity: any;
	$: known = party(address);
	onMount(async () => {
		if (href === '#') {
			const res = await fetch(`/api/entity/resolve/${address}`).then((res) => res.json());
			if(res.data) entity = res.data
			if(res.kind) kind = res.kind;
			href = `/${kind ?? 'address'}/${address}`;
			isLoading = false;
		}
	});
</script>

<div class="badge h-auto max-w-full bg-base-200 badge-lg">
	<a
		href={href.replace('undefined', 'address')}
		on:click={(e) => {
			e.preventDefault();
			window.location.href = href;
		}}
		class="flex flex-1 items-center gap-2 overflow-hidden"
	>
		{#if isLoading}
			<span class="loading loading-xs loading-dots"></span>
		{:else if kind === 'contract'}
			<ContractIcon />
		{:else}
			<WalletIcon />
		{/if}
		{#if known}
			<span class="ml-2 font-semibold">{known.name}</span>
			<span class="lw-tag lw-{known.kind}" class:lw-suspended={known.suspended}>{known.kind === 'supplier' ? (known.suspended ? 'suspended supplier' : 'supplier') : known.kind}</span>
			<span class="hidden truncate text-xs opacity-60 xl:inline">{address}</span>
		{:else}
			<span class="ml-2">{entity?.name?.length ? entity.name : address}</span>
		{/if}
	</a>
	<ClipboardCopyBtn value={address} />
</div>
