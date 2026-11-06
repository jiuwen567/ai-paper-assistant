<script setup lang="ts" generic="T extends boolean | string[]">
import { computed } from 'vue';
import { NCheckbox } from 'naive-ui';
const props = defineProps<{ modelValue?: T; checked?: boolean; value?: string; disabled?: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [checked: boolean] }>();
const checkedValue = computed(() => Array.isArray(props.modelValue) ? props.modelValue.includes(props.value!) : Boolean(props.modelValue ?? props.checked ?? false));
function update(checked: boolean) {
  const value = Array.isArray(props.modelValue) ? (checked ? [...new Set([...props.modelValue, props.value!])] : props.modelValue.filter(item => item !== props.value)) : checked;
  emit('update:modelValue', value as T); emit('change', checked);
}
</script>
<template><NCheckbox :checked="checkedValue" :disabled="disabled" :aria-disabled="disabled" @update:checked="update"><slot /></NCheckbox></template>
