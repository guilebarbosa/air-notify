<script lang="ts">
	import { dayLabel } from "./lib/format";
	import type { Day } from "./lib/types";

	interface Props {
		days: Day[];
		selected: string | null;
		onselect: (date: string) => void;
	}

	let { days, selected, onselect }: Props = $props();
</script>

{#if days.length === 0}
	<p>No locations recorded yet.</p>
{:else}
	<ul>
		{#each days as day (day.date)}
			<li>
				<button aria-current={day.date === selected ? "true" : undefined} onclick={() => onselect(day.date)}>
					<span>{dayLabel(day.date)}</span>
					<span class="count">{day.count}</span>
				</button>
			</li>
		{/each}
	</ul>
{/if}

<style>
	p {
		margin: 0.75rem;
		color: #666;
	}

	ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	button {
		display: flex;
		justify-content: space-between;
		width: 100%;
		padding: 0.5rem 0.75rem;
		border: 0;
		background: none;
		font: inherit;
		text-align: left;
		cursor: pointer;
	}

	button:hover,
	button[aria-current="true"] {
		background: #e8f0fe;
	}

	.count {
		color: #888;
	}
</style>
