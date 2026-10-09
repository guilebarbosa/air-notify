<script lang="ts" module>
	/**
	 * The height of one event (a one-line title, its time, the gap below), in rem: the gap is
	 * pb-3.5 (0.875), the title text-lg (1.75), the time a text-sm block (1.25). The last event has
	 * no gap. MobileFooter sizes its list with these.
	 */
	export const EVENT_REM = 3.875;
	export const EVENT_GAP_REM = 0.875;
</script>

<script lang="ts">
	// The selected day's arrivals and departures, newest first, styled like the logo's two ends:
	// a brick dot = arrived, a tangerine ring = left.
	// Our own markup rather than Flowbite's Timeline, which can't fade a line between two colours.
	import { clock } from "./lib/format";
	import type { TimelineEvent } from "./lib/types";

	interface Props {
		events: TimelineEvent[];
	}

	let { events }: Props = $props();

	// Whole class names, so Tailwind finds them when it scans this file.
	const DOT: Record<TimelineEvent["transition"], string> = {
		arrive: "bg-brick-500",
		leave: "border-[3px] border-tangerine-300 bg-white",
	};
	const FROM: Record<TimelineEvent["transition"], string> = { arrive: "from-brick-500", leave: "from-tangerine-200" };
	const TO: Record<TimelineEvent["transition"], string> = { arrive: "to-brick-500", leave: "to-tangerine-200" };
</script>

{#if events.length === 0}
	<p class="text-sm text-gray-500">No arrivals or departures this day.</p>
{:else}
	<ol>
		{#each events as event, i (event.t + event.zone + event.transition)}
			{@const next = events[i + 1]}
			<li class="relative pb-3.5 pl-8 last:pb-0">
				<!-- Dot and line are centred on the middle of the title's first line (top-3.5: half its
				     1.75rem line height) and on the dot's middle (left-2: half its width). -->
				{#if next}
					<!-- The line runs from this dot's centre to the next one's (the item's full height
					     further down), fading from this event's colour to the next one's. -->
					<div
						class="absolute top-3.5 left-2 h-full w-[3px] -translate-x-1/2 bg-linear-to-b {FROM[event.transition]} {TO[next.transition]}"
						aria-hidden="true"
					></div>
				{/if}
				<!-- On top of the lines. -->
				<div
					class="absolute top-3.5 left-0 size-4 -translate-y-1/2 rounded-full {DOT[event.transition]}"
					aria-hidden="true"
				></div>
				<h3 class="text-lg font-semibold text-gray-900">{event.label}</h3>
				<time datetime={event.t} class="block text-sm text-gray-500">{clock(event.t)}</time>
			</li>
		{/each}
	</ol>
{/if}
