<script setup lang="ts">
import type { DiffPart } from "@/features/expressions/types";
defineProps<{ parts: DiffPart[] }>();
</script>
<template><p class="text-changes" aria-label="文字差异"><template v-for="(part, index) in parts" :key="index"><span v-if="part.kind === 'equal'">{{ part.before }}</span><template v-else><del v-if="part.before">{{ part.before }}</del><ins v-if="part.after">{{ part.after }}</ins></template></template></p></template>
<style scoped>
.text-changes { white-space: pre-wrap; overflow-wrap: anywhere; }
del { background: #fbe7e4; color: #7c2920; }
ins { background: #dff1d9; color: #24532a; text-decoration: underline; }
</style>
