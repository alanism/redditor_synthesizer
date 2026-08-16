<script lang="ts">
	import "$lib/default.scss";
	import TextField from "./TextField.svelte";

	interface Props {
		label: string;
		onChange: (date: Date|null) => void;
		allowNow: boolean;
		date: Date|null;
	}

	let {
		label,
		onChange,
		allowNow,
		date
	}: Props = $props();


	function getError(text: string): string|null {
		let newDate: Date|null = new Date(text);
		if (allowNow && text.toLowerCase() == "now")
			return null;
		if (newDate.toString() === "Invalid Date")
			return "Invalid date";
		return null;
	}
	
	function getDateValue(text: string): Date|null {
		let newDate: Date|null = new Date(text);
		if (allowNow && text.toLowerCase() == "now") {
			newDate = null;
		}
		else if (newDate.toString() === "Invalid Date") {
			newDate = null;
		}
		else {
			newDate = newDate;
		}
		return newDate;
	}
</script>

<!-- <span>{label}</span>
<input
	class="date text-field"
	class:error={!isValid}
	value={date?.toISOString().slice(0, 10) ?? "now"}
	on:change={onDateChange}
/> -->
<TextField
	text={date?.toISOString().slice(0, 10) ?? "now"}
	label={label}
	onChange={(text) => onChange(getDateValue(text))}
	getError={getError}
/>
