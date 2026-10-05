<script lang="ts">
	// The date button: shows "Today" or the picked day; clicking it opens a calendar next to it.
	// Flowbite's Popover places it on the requested side and flips it when there's no room.
	import Button from "flowbite-svelte/Button.svelte"; // per-component imports: only these get bundled
	import Datepicker from "flowbite-svelte/Datepicker.svelte";
	import Popover from "flowbite-svelte/Popover.svelte";

	import { dateLabel, toDate, todayIso, toIso } from "./lib/format";
	import type { Day } from "./lib/types";

	interface Props {
		id: string; // unique per instance (desktop panel / mobile footer): the popover is tied to it
		placement: "top" | "bottom"; // where the calendar opens: above the footer, below the panel buttons
		days: Day[]; // recorded days, newest first
		selected: string | null; // YYYY-MM-DD
		onselect: (date: string) => void;
	}

	let { id, placement, days, selected, onselect }: Props = $props();

	let open = $state(false);
	const label = $derived(!selected || selected === todayIso() ? "Today" : dateLabel(selected));
	const value = $derived(selected ? toDate(selected) : undefined);
	// Selectable: the oldest recorded day up to today (days without reports just show the zones).
	const oldest = $derived(days.length ? toDate(days[days.length - 1].date) : undefined);
</script>

<Button {id} color="alternative" class="w-full justify-between" aria-expanded={open}>
	{label}
	<svg class="ms-2 h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
		<path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m19 9-7 7-7-7" />
	</svg>
</Button>

<Popover triggeredBy={`#${id}`} trigger="click" {placement} bind:isOpen={open} class="z-[1200]">
	<Datepicker
		inline
		{value}
		availableFrom={oldest}
		availableTo={new Date()}
		firstDayOfWeek={1}
		onselect={(picked) => {
			if (!(picked instanceof Date)) return;
			open = false;
			onselect(toIso(picked));
		}}
	/>
</Popover>
