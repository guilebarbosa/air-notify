<script lang="ts">
	// Mobile: a footer over the map with the date and "Check now" buttons. The chevron slides it
	// up to show the day's timeline.
	import type { Snippet } from "svelte";

	import Logo from "./Logo.svelte";

	interface Props {
		controls: Snippet; // the date + "Check now" buttons
		details: Snippet; // status line + timeline, shown when expanded
		height?: number; // bindable: the footer's current height in pixels (0 on desktop, where it's hidden)
	}

	let { controls, details, height = $bindable(0) }: Props = $props();

	let expanded = $state(false);
</script>

<footer
	bind:clientHeight={height}
	class="fixed inset-x-0 bottom-0 z-[1100] rounded-t-2xl bg-white px-4 pt-3 pb-4 shadow-[0_-4px_16px_rgba(0,0,0,0.15)] md:hidden"
>
	<div class="mb-3 flex items-center">
		<Logo class="h-7 w-auto" />
		<button
			type="button"
			class="ms-auto rounded-lg p-2 text-gray-700 hover:bg-gray-100"
			aria-label={expanded ? "Hide the timeline" : "Show the timeline"}
			aria-expanded={expanded}
			onclick={() => (expanded = !expanded)}
		>
			<svg class="h-5 w-5 transition-transform {expanded ? 'rotate-180' : ''}" viewBox="0 0 24 24" fill="none" aria-hidden="true">
				<path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m5 15 7-7 7 7" />
			</svg>
		</button>
	</div>
	{@render controls()}
	{#if expanded}
		<!-- Only this part scrolls, so the calendar popover above the buttons isn't clipped. -->
		<div class="mt-4 flex max-h-[50vh] flex-col gap-3 overflow-y-auto">
			{@render details()}
		</div>
	{/if}
</footer>
