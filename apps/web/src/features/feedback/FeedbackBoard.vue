<script setup lang="ts">
import { computed, ref } from 'vue';
import { progressLabels, type FeedbackTask } from '@/features/feedback/types';
const props = defineProps<{ tasks: FeedbackTask[]; busy: boolean }>();
const emit = defineEmits<{ select: [id: string] }>();
const query = ref('');
const filtered = computed(() => props.tasks.filter(task => `${task.current.title} ${task.current.instruction} ${task.current.note}`.toLowerCase().includes(query.value.trim().toLowerCase())));
</script>
<template>
  <section class="feedback-board" aria-label="本页修改看板">
    <label>查找本页待办<UiInput v-model="query" aria-label="查找本页待办" placeholder="标题、要求或处理说明" /></label>
    <div class="board-columns"><section v-for="(label, state) in progressLabels" :key="state" class="board-column"><h4>{{ label }} <NTag size="small" :bordered="false">{{ filtered.filter(task => task.current.status === state).length }}</NTag></h4>
      <article v-for="task in filtered.filter(task => task.current.status === state)" :key="task.id" class="board-task"><NButton text :disabled="busy" @click="emit('select', task.id)">{{ task.current.title }}</NButton><p>{{ task.current.instruction }}</p><small>处理 v{{ task.current.number }} · {{ task.current.location ? `原稿块 ${task.current.location.position}` : '未关联正文' }}</small><p v-if="task.current.location?.stale" class="field-error">关联位置已失效</p><p v-if="state === 'completed'" class="notice">{{ task.current.mentor_reports.length ? `已登记 ${task.current.mentor_reports.length} 条导师回复（作者转录）` : '作者完成不代表导师确认' }}</p></article>
      <p v-if="!filtered.some(task => task.current.status === state)" class="notice">暂无待办</p>
    </section></div>
  </section>
</template>
