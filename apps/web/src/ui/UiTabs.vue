<script setup lang="ts">
import { nextTick, ref } from 'vue';
import { NTabs, NTab } from 'naive-ui';
const props = defineProps<{ modelValue: string; options: { value: string; label: string }[] }>();
const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const root = ref<HTMLElement | null>(null);
async function keyboard(event: KeyboardEvent, index: number) {
  let target: number;
  if (event.key === 'ArrowRight') target = (index + 1) % props.options.length;
  else if (event.key === 'ArrowLeft') target = (index + props.options.length - 1) % props.options.length;
  else if (event.key === 'Home') target = 0;
  else if (event.key === 'End') target = props.options.length - 1;
  else if (event.key === 'Enter' || event.key === ' ') target = index;
  else return;
  event.preventDefault(); emit('update:modelValue', props.options[target]!.value);
  await nextTick(); root.value?.querySelectorAll<HTMLElement>('[role="tab"]')[target]?.focus();
}
</script>
<template><div ref="root"><NTabs :value="modelValue" type="line" role="tablist" @update:value="emit('update:modelValue', $event)"><NTab v-for="(option, index) in options" :key="option.value" :name="option.value" role="tab" :aria-selected="modelValue === option.value" :tabindex="modelValue === option.value ? 0 : -1" @keydown="keyboard($event, index)">{{ option.label }}</NTab></NTabs></div></template>
