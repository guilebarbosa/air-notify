<script lang="ts">
	// The selected day's arrivals and departures, newest first; each dot has its zone's colour.
	import Timeline from "flowbite-svelte/Timeline.svelte";
	import TimelineItem from "flowbite-svelte/TimelineItem.svelte";

	import { zoneColor } from "./lib/colors";
	import { clock } from "./lib/format";
	import type { TimelineEvent, Zone } from "./lib/types";

	interface Props {
		events: TimelineEvent[];
		zones: Zone[];
	}

	let { events, zones }: Props = $props();

	const colorOf = (zone: string) => zoneColor(zones.findIndex((z) => z.name === zone)).name;
</script>

{#if events.length === 0}
	<p class="text-sm text-gray-500">No arrivals or departures this day.</p>
{:else}
	<Timeline order="vertical">
		{#each events as event, i (event.t + event.zone + event.transition)}
			<!-- `date` isn't a real date here; Flowbite then shows it as given ("15:20"). -->
			<TimelineItem
				title={event.label}
				date={clock(event.t)}
				color={colorOf(event.zone)}
				isLast={i === events.length - 1}
			>
				<span class="sr-only">{event.transition === "arrive" ? "Arrived" : "Left"}</span>
			</TimelineItem>
		{/each}
	</Timeline>
{/if}
