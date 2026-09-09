import { createEventDispatcher } from 'svelte';

let expanded = false;
const dispatch = createEventDispatcher();

function toggleExpand() {
    expanded = !expanded;
    dispatch('expand', { expanded });
}
