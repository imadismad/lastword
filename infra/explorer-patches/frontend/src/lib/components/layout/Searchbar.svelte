<script lang="ts">
	import SearchIcon from 'virtual:icons/hugeicons/search-02';
	import {goto} from "$app/navigation";
	import {ethers} from "ethers";

	let className = '';
	export { className as class };

	let query = ''

	const redirect = () => {
		if(ethers.isAddress(query)) {
			goto(`/address/${query}`)
		} else if(String(query).startsWith('0x')) {
			goto(`/tx/${query}`)
		} else if(!isNaN(Number(query))) {
			goto(`/block/${query}`)
		}
	}

	const onKeypress = (e: any) => {
		if(e.key === 'Enter') {
			redirect()
		}
	}
</script>

<div class="searchbar-wrapper {className}">
	<input
		type="search"
		placeholder="Search by address, tx hash, block, token, ..."
		on:keypress={onKeypress}
		bind:value={query}
	/>
	<button on:click={redirect}>
		<SearchIcon />
	</button>
</div>

<style lang="postcss">
	@reference "$lib/../app.css";
	.searchbar-wrapper {
		@apply flex items-center px-4 pl-6;
		@apply !rounded-full;
		background: rgba(255, 255, 255, 0.92);
		border: 1px solid rgba(28, 27, 24, 0.09);
		transition: all 0.2s ease;
		height: 2.75rem;
		&:hover {
			border-color: rgba(28, 27, 24, 0.16);
		}
		&:focus-within {
			border-color: rgba(255, 90, 31, 0.4);
			box-shadow: 0 0 0 3px rgba(255, 90, 31, 0.08);
			background: rgba(255, 255, 255, 0.92);
		}
		input {
			@apply w-full bg-transparent border-0 outline-0;
			color: var(--color-base-content);
			&::placeholder {
				color: rgba(28, 27, 24, 0.37);
			}
		}
		button {
			@apply cursor-pointer;
			color: rgba(28, 27, 24, 0.5);
			transition: color 0.2s;
			&:hover {
				color: #ff5a1f;
			}
		}
	}
</style>
