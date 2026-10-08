<script lang="ts">
	// The date navigation: [<] Today [>]. The arrows step a day back or forward (from the oldest
	// recorded day up to today); clicking the date opens a calendar next to it.
	// Flowbite's Popover places it on the requested side and flips it when there's no room.
	import Button from "flowbite-svelte/Button.svelte"; // per-component imports: only these get bundled
	import ButtonGroup from "flowbite-svelte/ButtonGroup.svelte";
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
	const oldest = $derived(days.length ? days[days.length - 1].date : null);
	// YYYY-MM-DD strings sort like the dates they stand for.
	const canGoBack = $derived(selected !== null && oldest !== null && selected > oldest);
	const canGoForward = $derived(selected !== null && selected < todayIso());

	function step(by: number) {
		if (!selected) return;
		const date = toDate(selected);
		date.setDate(date.getDate() + by);
		onselect(toIso(date));
	}
</script>

{#snippet chevron(d: string)}
	<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
		<path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" {d} />
	</svg>
{/snippet}

<!-- focus-within:ring-0: no frame left on a button after clicking or tapping it (keyboard focus
     still shows the browser's outline). -->
<ButtonGroup class="flex w-full">
	<Button class="px-2.5 focus-within:ring-0" aria-label="Previous day" disabled={!canGoBack} onclick={() => step(-1)}>
		{@render chevron("m15 19-7-7 7-7")}
	</Button>
	<Button {id} class="min-w-0 flex-1 px-2 focus-within:ring-0" aria-expanded={open} aria-label="{label}: pick a day">{label}</Button>
	<Button class="px-2.5 focus-within:ring-0" aria-label="Next day" disabled={!canGoForward} onclick={() => step(1)}>
		{@render chevron("m9 5 7 7-7 7")}
	</Button>
</ButtonGroup>

<Popover triggeredBy={`#${id}`} trigger="click" {placement} bind:isOpen={open} class="z-[1200]">
	<Datepicker
		inline
		{value}
		availableFrom={oldest ? toDate(oldest) : undefined}
		availableTo={new Date()}
		firstDayOfWeek={1}
		onselect={(picked) => {
			if (!(picked instanceof Date)) return;
			open = false;
			onselect(toIso(picked));
		}}
	/>
</Popover>
