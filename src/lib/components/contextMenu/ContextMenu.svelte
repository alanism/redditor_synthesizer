<script lang="ts">
	import { createEventDispatcher, onMount } from "svelte";
	import type { ContextMenuItem } from "./contextMenuTypes";

	interface Props {
		items: ContextMenuItem[];
		x: number;
		y: number;
		visible?: boolean;
	}

	let {
		items,
		x,
		y,
		visible = true
	}: Props = $props();

	const dispatch = createEventDispatcher();

	let menuElement: HTMLDivElement|undefined = $state();
	let adjustedX = $state(0);
	let adjustedY = $state(0);


	onMount(() => {
		adjustedX = x;
		adjustedY = y;
		updatePosition();
	});

	function updatePosition() {
		if (!menuElement) return;

		adjustedX = x;
		adjustedY = y;

		// Adjust position to keep menu within viewport
		const rect = menuElement.getBoundingClientRect();
		const viewportWidth = window.innerWidth;
		const viewportHeight = window.innerHeight;

		// Adjust horizontal position
		if (x + rect.width > viewportWidth) {
			adjustedX = Math.max(0, viewportWidth - rect.width);
		}

		// Adjust vertical position
		if (y + rect.height > viewportHeight) {
			adjustedY = Math.max(0, viewportHeight - rect.height);
		}
	}

	function handleItemClick(item: ContextMenuItem) {
		if (!item.disabled) {
			item.onClick();
			dispatch('close');
		}
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			dispatch('close');
		}
	}
	$effect(() => {
		updatePosition();
	});
</script>

<svelte:window onkeydown={handleKeydown} />

{#if visible && items.length > 0}
	<div
		bind:this={menuElement}
		class="context-menu"
		style="left: {adjustedX}px; top: {adjustedY}px;"
	>
		{#each items as item, i (i)}
			{#if item.separator}
				<div class="separator"></div>
			{:else}
				<button
					class="menu-item"
					class:disabled={item.disabled}
					onclick={() => handleItemClick(item)}
					disabled={item.disabled}
				>
					{item.label}
				</button>
			{/if}
		{/each}
	</div>
{/if}

<style lang="scss">
	.context-menu {
		position: fixed;
		background: var(--bg-el1-color);
		border: 1px solid var(--border-color);
		border-radius: 0.5rem;
		box-shadow: 0 4px 12px var(--shadow-color);
		padding: 0.25rem 0;
		min-width: 10rem;
		max-width: 100vw;
	}

	.menu-item {
		display: block;
		width: 100%;
		padding: 0.5rem 1rem;
		text-align: left;
		font-size: 0.9rem;
		font-weight: 400;
		white-space: nowrap;
		cursor: pointer;
		transition: background-color 0.15s ease;

		&:hover:not(.disabled) {
			background: var(--switcher-bg-hover);
		}

		&:active:not(.disabled) {
			background: var(--switcher-bg-active);
		}

		&.disabled {
			opacity: 0.5;
			cursor: default;
		}
	}

	.separator {
		height: 1px;
		background: var(--border-color);
		margin: 0.25rem 0;
	}
</style>
