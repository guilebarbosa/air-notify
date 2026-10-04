<script lang="ts">
	// An inline calendar for picking the day to show. Days run from the oldest recorded day
	// to today; a day without reports can still be picked (the map just shows the zones).
	import Datepicker from "flowbite-svelte/Datepicker.svelte"; // per-component import: only this gets bundled

	import type { Day } from "./lib/types";

	interface Props {
		days: Day[]; // recorded days with their report counts, newest first
		selected: string | null; // YYYY-MM-DD
		onselect: (date: string) => void;
	}

	let { days, selected, onselect }: Props = $props();

	// The API uses local YYYY-MM-DD strings; the date picker uses Date objects. Noon keeps a
	// date from slipping to the neighbouring day across time zones / DST changes.
	const toDate = (iso: string) => new Date(`${iso}T12:00`);
	const toIso = (d: Date) =>
		`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

	const value = $derived(selected ? toDate(selected) : undefined);
	const oldest = $derived(days.length ? toDate(days[days.length - 1].date) : undefined);
	const count = $derived(days.find((d) => d.date === selected)?.count ?? 0);
</script>

<div class="picker">
	<Datepicker
		inline
		{value}
		availableFrom={oldest}
		availableTo={new Date()}
		firstDayOfWeek={1}
		onselect={(picked) => {
			if (picked instanceof Date) onselect(toIso(picked));
		}}
	/>
</div>
{#if selected}
	<p>{count === 0 ? "No reports that day." : `${count} report${count === 1 ? "" : "s"} that day.`}</p>
{/if}

<style>
	.picker {
		margin: 0 0.75rem;
	}

	p {
		margin: 0.5rem 0.75rem;
		color: #666;
		font-size: 12px;
	}
</style>
