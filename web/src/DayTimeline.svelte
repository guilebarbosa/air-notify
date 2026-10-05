<script lang="ts">
	// The selected day's arrivals and departures, newest first: green dot = arrived, red = left.
	import Timeline from "flowbite-svelte/Timeline.svelte";
	import TimelineItem from "flowbite-svelte/TimelineItem.svelte";

	import { clock } from "./lib/format";
	import type { TimelineEvent } from "./lib/types";

	interface Props {
		events: TimelineEvent[];
	}

	let { events }: Props = $props();
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
				color={event.transition === "arrive" ? "green" : "red"}
				isLast={i === events.length - 1}
			>
				<span class="sr-only">{event.transition === "arrive" ? "Arrived" : "Left"}</span>
			</TimelineItem>
		{/each}
	</Timeline>
{/if}
