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
	import Logo from "./Logo.svelte";
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
	let footerHeight = $state(0); // the mobile footer's; 0 on desktop

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

<!-- The date navigation and "Check now", side by side across the full width; the dates get
     whatever "Check now" doesn't need. -->
{#snippet controls(id: string, placement: "top" | "bottom")}
	<div class="grid gap-2 {status?.available ? 'grid-cols-[minmax(0,1fr)_auto]' : 'grid-cols-1'}">
		<DayPicker {id} {placement} {days} {selected} onselect={(date) => select(date).catch(showError)} />
		{#if status?.available}
			<!-- Flowbite's buttons use the darker primary-700; 500 is the brand green itself. -->
			<Button class="w-full bg-primary-500 hover:bg-primary-600" onclick={check} disabled={checking}>
				{checking ? "Checking…" : "Check now"}
			</Button>
		{/if}
	</div>
{/snippet}

{#snippet details()}
	<StatusLine {status} {message} />
	<DayTimeline events={day?.events ?? []} />
{/snippet}

<MapView
	{tiles}
	points={day?.points ?? []}
	zones={day?.zones ?? []}
	maxAccuracy={day?.max_accuracy_m ?? Infinity}
	{padding}
	focusLatest={day?.date === todayIso()}
	buttonsBottom={footerHeight}
/>

<!-- No overflow on the panel itself (only the timeline part scrolls), so the calendar popover isn't clipped. -->
<aside
	class="absolute top-[max(1rem,env(safe-area-inset-top))] left-[max(1rem,env(safe-area-inset-left))] z-[1100] hidden max-h-[calc(100%-2rem)] w-[22rem] flex-col gap-4 rounded-2xl bg-white/95 p-5 shadow-xl md:flex"
>
	<h1><Logo class="h-12 w-auto" /></h1>
	{@render controls("day-desktop", "bottom")}
	<div class="flex min-h-0 flex-col gap-3 overflow-y-auto">
		{@render details()}
	</div>
</aside>

<MobileFooter controls={mobileControls} {details} bind:height={footerHeight} />

{#snippet mobileControls()}
	{@render controls("day-mobile", "top")}
{/snippet}
