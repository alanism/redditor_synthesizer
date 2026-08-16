<script lang="ts">
	import { svgPresets, type SvgPresetName } from "./svgPresets";

	interface Props {
		name: SvgPresetName,
		x?: number;
		y?: number;
		size: number;
		color?: string;
	}
	const {
		name,
		x,
		y,
		size,
		color = "currentColor",
	}: Props = $props();

	const preset = $derived(svgPresets[name]);
</script>

{#if preset}
	<svg
		x={x}
		y={y}
		width={size}
		height={size}
		viewBox={preset.viewBox}
		xmlns="http://www.w3.org/2000/svg"
		style="color: {color};"
	>
		<!-- eslint-disable-next-line svelte/no-at-html-tags -- preset.innerHtml comes from the hardcoded local preset map, not user input -->
	{@html preset.innerHtml}
	</svg>
{:else}
	?
{/if}
