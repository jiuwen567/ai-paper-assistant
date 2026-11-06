<script setup lang="ts">
import { ref, useId } from 'vue';
import { NButton, NCollapse, NCollapseItem } from 'naive-ui';
const props = defineProps<{ open?: boolean }>();
const expanded = ref<string[]>(props.open ? ['content'] : []);
const id = useId();
function toggle() { expanded.value = expanded.value.length ? [] : ['content']; }
</script>
<template>
  <NCollapse v-model:expanded-names="expanded" class="disclosure"><NCollapseItem name="content" display-directive="show"><template #header><NButton text :aria-expanded="expanded.length > 0" :aria-controls="id" @click.stop="toggle"><slot name="header" /></NButton></template><div :id="id"><slot /></div></NCollapseItem></NCollapse>
</template>
