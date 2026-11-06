<script setup lang="ts" generic="T extends string | number">
import { h, ref, useAttrs, useId } from 'vue';
import { NSelect, type SelectOption, type SelectInst } from 'naive-ui';
defineOptions({ inheritAttrs: false });
const props = defineProps<{ modelValue: T; options: SelectOption[]; disabled?: boolean; required?: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T] }>();
const attrs = useAttrs();
const shown = ref(false);
const invalid = ref(false);
const menuId = useId();
function validate() { invalid.value = true; select.value?.focus(); }
const select = ref<SelectInst | null>(null);
function renderLabel(option: SelectOption) { return h('span', { 'data-option-value': String(option.value) }, String(option.label)); }
function update(value: T) { invalid.value = false; emit('update:modelValue', value); emit('change', value); }
</script>
<template>
  <div class="select-field">
    <NSelect ref="select" role="combobox" :aria-controls="menuId" :menu-props="{ id: menuId }" :aria-required="required" :aria-invalid="invalid" :status="invalid ? 'error' : undefined" v-model:show="shown" :aria-expanded="shown" :aria-disabled="disabled" v-bind="attrs" :value="modelValue" :options="options" :render-label="renderLabel" :disabled="disabled" :consistent-menu-width="false" @update:value="update" />
    <input v-if="required" class="validation-input" tabindex="-1" aria-hidden="true" :value="modelValue" :required="required" :disabled="disabled" @invalid.prevent="validate" />
    <span v-if="invalid" class="field-error" role="alert">请选择一项。</span>
  </div>
</template>
