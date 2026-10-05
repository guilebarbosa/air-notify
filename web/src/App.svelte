<script lang="ts">
	// Layout: the map fills the window. On desktop a floating panel on the left holds the date
	// and "Check now" buttons and the day's timeline; on mobile a footer does (see MobileFooter).
	import Button from "flowbite-svelte/Button.svelte";
	import { onMount } from "svelte";

	import DayPicker from "./DayPicker.svelte";
	import DayTimeline from "./DayTimeline.svelte";
	import { checkNow, getDay, getDays, getMap, getStatus } from "./lib/api";
	import { todayIso } from "./lib/format";
	import type { Day, DayData, MapTiles, Status } from "./lib/types";
	import MapView, { type Padding } from "./MapView.svelte";
	import MobileFooter from "./MobileFooter.svelte";
	import StatusLine from "./StatusLine.svelte";

	let days = $state<Day[]>([]);
	let selected = $state<string | null>(null);
	let day = $state<DayData | null>(null);
	let status = $state<Status | null>(null);
	let message = $state<string | null>(null);
	let checking = $state(false);
	let tiles = $state<MapTiles | null>(null);
	let desktop = $state(true);

	// Keep the day's points clear of the floating panel (desktop) or the footer (mobile).
	const padding: Padding = $derived(
		desktop ? { topLeft: [400, 40], bottomRight: [40, 40] } : { topLeft: [30, 30], bottomRight: [30, 140] },
	);

	const showError = (error: unknown) => {
		console.error(error);
		message = `Error: ${error instanceof Error ? error.message : String(error)}`;
	};

	async function select(date: string) {
		selected = date;
		day = await getDay(date);
	}

	async function loadDays() {
		days = await getDays();
		// Keep the selected day if it's still recorded; otherwise show the newest.
		const keep = days.find((d) => d.date === selected)?.date ?? days[0]?.date;
		if (keep) await select(keep);
	}

	async function loadStatus() {
		status = await getStatus();
	}

	async function loadMap() {
		tiles = await getMap();
		if (tiles.warning) message = tiles.warning;
	}

	// "Check now": ask the daemon for a check, then jump to today with the fresh data.
	async function check() {
		checking = true;
		message = null;
		try {
			const result = await checkNow();
			days = await getDays();
			await Promise.all([select(todayIso()), loadStatus()]);
			if (result.status !== "ok") message = result.detail;
		} catch (error) {
			showError(error);
		} finally {
			checking = false;
		}
	}

	onMount(() => {
		const query = window.matchMedia("(min-width: 768px)"); // Tailwind's `md` breakpoint
		const update = () => (desktop = query.matches);
		update();
		query.addEventListener("change", update);
		Promise.all([loadMap(), loadStatus(), loadDays()]).catch(showError);
		return () => query.removeEventListener("change", update);
	});
</script>

<!-- The date and "Check now" buttons, side by side across the full width. -->
{#snippet controls(id: string, placement: "top" | "bottom")}
	<div class="grid gap-2 {status?.available ? 'grid-cols-2' : 'grid-cols-1'}">
		<DayPicker {id} {placement} {days} {selected} onselect={(date) => select(date).catch(showError)} />
		{#if status?.available}
			<Button class="w-full" onclick={check} disabled={checking}>{checking ? "Checking…" : "Check now"}</Button>
		{/if}
	</div>
{/snippet}

{#snippet details()}
	<StatusLine {status} {message} />
	<DayTimeline events={day?.events ?? []} zones={day?.zones ?? []} />
{/snippet}

<MapView {tiles} points={day?.points ?? []} zones={day?.zones ?? []} {padding} />

<!-- No overflow on the panel itself (only the timeline part scrolls), so the calendar popover isn't clipped. -->
<aside
	class="absolute top-4 left-4 z-[1100] hidden max-h-[calc(100%-2rem)] w-[22rem] flex-col gap-4 rounded-2xl bg-white/95 p-5 shadow-xl md:flex"
>
	<h1 class="text-5xl font-black">AirNotify</h1>
	{@render controls("day-desktop", "bottom")}
	<div class="flex min-h-0 flex-col gap-3 overflow-y-auto">
		{@render details()}
	</div>
</aside>

<MobileFooter controls={mobileControls} {details} />

{#snippet mobileControls()}
	{@render controls("day-mobile", "top")}
{/snippet}
