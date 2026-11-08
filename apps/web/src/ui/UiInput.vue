<script setup lang="ts" generic="T extends string | number">
import { useAttrs } from 'vue';
import { NInput } from 'naive-ui';
defineOptions({ inheritAttrs: false });
const props = defineProps<{ modelValue: T; type?: string; disabled?: boolean; readonly?: boolean; rows?: string | number; maxlength?: string | number }>();
const emit = defineEmits<{ 'update:modelValue': [value: T]; input: [value: string] }>();
const attrs = useAttrs();
// attrs 在渲染时读取，动态必填规则和可访问名称随业务状态更新。
function inputProps() {
  return props.type === 'number' || props.type === 'url' ? { ...attrs, type: props.type } : { ...attrs };
}
function update(value: string) {
  // 数字字段继续使用浏览器的 min/max/required 校验；保持原接口的数字值。
  emit('update:modelValue', (props.type === 'number' && value !== '' ? Number(value) : value) as T);
  emit('input', value);
}
</script>
<template>
  <NInput :value="String(modelValue ?? '')" :type="type === 'textarea' ? 'textarea' : type === 'password' ? 'password' : 'text'" :disabled="disabled" :readonly="readonly" :maxlength="maxlength === undefined ? undefined : Number(maxlength)" :input-props="inputProps()" :placeholder="typeof attrs.placeholder === 'string' ? attrs.placeholder : undefined" :autosize="type === 'textarea' ? { minRows: Number(rows || 3) } : undefined" :show-password-on="type === 'password' ? 'click' : undefined" @update:value="update" />
</template>
