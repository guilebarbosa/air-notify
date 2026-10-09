<script lang="ts">
	// Mobile: the footer under the map card, with the day's latest events (the status line in the
	// bottom-right corner, level with the newest event's time), and the date and "Check now"
	// buttons at the bottom, where they stay put while stepping through days
	// (the map card above takes up the difference). The events run oldest to newest, so the latest
	// sits just above the buttons. Older ones beyond two fade out at the top under a chevron ("Show
	// more"), which lets the list grow to eight; beyond that it scrolls up.
	import type { Snippet } from "svelte";

	import DayTimeline, { EVENT_GAP_REM, EVENT_REM } from "./DayTimeline.svelte";
	import type { TimelineEvent } from "./lib/types";

	interface Props {
		controls: Snippet; // the date + "Check now" buttons
		status: Snippet; // last check and latest report (icons and times)
		message: string | null; // a check result or error: shown on its own line instead of `status`
		events: TimelineEvent[]; // newest first
	}

	let { controls, status, message, events }: Props = $props();

	const COLLAPSED = 2; // events shown in full before the fade
	const EXPANDED = 8; // events shown before the list scrolls
	const PEEK_REM = 3; // how much of the next (older) event shows under the fade

	let expanded = $state(false);
	let list: HTMLDivElement; // the events, cut off at `maxHeight`
	let width = $state(0);
	let overflows = $state(false); // more events than fit
	// The newest event, at the bottom, has no gap below it.
	const maxHeight = $derived(
		`${(expanded ? EXPANDED : COLLAPSED) * EVENT_REM - EVENT_GAP_REM + (expanded ? 0 : PEEK_REM)}rem`,
	);
	const oldestFirst = $derived([...events].reverse());

	// Measured rather than counted, since a long title can wrap to two lines. Again when the
	// events, the state or the width change.
	$effect(() => {
		void [events, maxHeight, width];
		overflows = list.scrollHeight > list.clientHeight + 1;
	});
</script>

<!-- A thin, wide chevron: up to show the older events, down to fold them away again. -->
{#snippet chevron(label: string, direction: "up" | "down", onclick: () => void)}
	<button type="button" class="px-4 py-1.5 text-gray-400 hover:text-gray-700" aria-label={label} title={label} {onclick}>
		<svg class="h-3 w-9" viewBox="0 0 36 12" fill="none" aria-hidden="true">
			<path
				stroke="currentColor"
				stroke-width="1.5"
				stroke-linecap="round"
				stroke-linejoin="round"
				d={direction === "up" ? "M2 10 18 2l16 8" : "M2 2l16 8 16-8"}
			/>
		</svg>
	</button>
{/snippet}

<footer
	class="flex shrink-0 flex-col gap-3 ps-[max(1rem,env(safe-area-inset-left))] pe-[max(1rem,env(safe-area-inset-right))] pt-3 pb-[max(1rem,env(safe-area-inset-bottom))] md:hidden"
>
	<div class="flex flex-col gap-3">
		{#if expanded}
			<div class="flex justify-center">
				{@render chevron("Show less", "down", () => (expanded = false))}
			</div>
		{/if}
		<div class="relative">
			<!-- flex-col-reverse: the list sits at the bottom, so it's the older events at the top that
			     get cut off, and an expanded list starts scrolled to the newest. -->
			<div
				bind:this={list}
				bind:clientWidth={width}
				class="flex flex-col-reverse {expanded ? 'overflow-y-auto' : 'overflow-hidden'}"
				style:max-height={maxHeight}
			>
				<div class="shrink-0"><DayTimeline events={oldestFirst} /></div>
			</div>
			{#if overflows && !expanded}
				<!-- The fade over the older events, with the button on it. -->
				<div
					class="pointer-events-none absolute inset-x-0 top-0 flex h-16 items-start justify-center bg-linear-to-b from-white from-35% to-transparent"
				>
					<span class="pointer-events-auto">{@render chevron("Show more", "up", () => (expanded = true))}</span>
				</div>
			{/if}
			{#if !message}
				<!-- Bottom right, on the line of the newest event's time (same line height). -->
				<div class="absolute right-0 bottom-0">{@render status()}</div>
			{/if}
		</div>
		{#if message}
			<p class="text-xs text-gray-500">{message}</p>
		{/if}
	</div>
	{@render controls()}
</footer>
