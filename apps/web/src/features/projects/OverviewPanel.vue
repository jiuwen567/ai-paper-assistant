<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { ArrowRight, RefreshCw, FilePenLine, Files, Quote, ListTodo } from '@lucide/vue';
import { ApiError, request } from "@/api/client";
import { type Page } from "@/api/types";
import { type Project } from "@/features/projects/types";
import type { Manuscript } from '@/features/manuscripts/types';
import type { FeedbackTask } from '@/features/feedback/types';
import { characterCount } from "@/features/manuscripts/tools";
const props = defineProps<{ project: Project }>();
const emit = defineEmits<{ navigate: [workspace: string, tab?: string]; accessLost: [error: ApiError] }>();
const manuscript = ref<Manuscript | null>(null), materialCount = ref<number | null>(null), evidenceCount = ref<number | null>(null);
const todo = ref<Page<FeedbackTask> | null>(null), doing = ref<Page<FeedbackTask> | null>(null);
const busy = ref(false), errors = ref<string[]>([]), updated = ref('');
let mounted = true;
const pending = computed(() => todo.value && doing.value ? todo.value.count + doing.value.count : null);
const metrics = computed(() => [
  { label: '原稿字数', value: manuscript.value ? characterCount(manuscript.value.blocks.map(b => b.text).join('')) : null, icon: FilePenLine, target: 'writing' },
  { label: '材料', value: materialCount.value, icon: Files, target: 'materials' },
  { label: '证据卡', value: evidenceCount.value, icon: Quote, target: 'materials', tab: 'library' },
  { label: '待处理修改', value: pending.value, icon: ListTodo, target: 'feedback' },
]);
const steps = computed(() => [
  { title: '整理研究材料', detail: materialCount.value === null ? '材料状态未读取' : materialCount.value ? `${materialCount.value} 份材料，继续整理与阅读` : '上传文献、研究笔记或实验记录', target: 'materials' },
  { title: '组织作者原稿', detail: manuscript.value ? `已保存 v${manuscript.value.version} · ${manuscript.value.blocks.filter(b => b.heading_level).length} 个标题` : '原稿状态未读取', target: 'writing' },
  { title: '核对引用与论证', detail: '选择已保存的原稿，逐项判断审阅建议', target: 'review' },
  { title: '准备交付', detail: '核对使用说明，预览固定版本 Word', target: 'delivery' },
]);
async function load() {
  if (busy.value) return;
  busy.value = true; errors.value = []; updated.value = '';
  manuscript.value = null; materialCount.value = null; evidenceCount.value = null; todo.value = null; doing.value = null;
  const base = `projects/${props.project.id}/`;
  const paths = ['manuscript/', 'materials/', 'evidence/', 'feedback-tasks/?status=todo', 'feedback-tasks/?status=doing'];
  const results = await Promise.allSettled(paths.map(path => request<unknown>(base + path)));
  if (!mounted) return;
  const denied = results.find(result => result.status === 'rejected' && result.reason instanceof ApiError && [401, 403, 404].includes(result.reason.status));
  if (denied?.status === 'rejected') { busy.value = false; emit('accessLost', denied.reason); return; }
  const names = ['原稿', '材料', '证据卡', '待处理修改', '处理中修改'];
  results.forEach((result, i) => {
    if (result.status === 'rejected') { errors.value.push(`${names[i]}：${result.reason instanceof Error ? result.reason.message : '读取失败'}`); return; }
    if (i === 0) manuscript.value = result.value as Manuscript;
    if (i === 1) materialCount.value = (result.value as Page<unknown>).count;
    if (i === 2) evidenceCount.value = (result.value as Page<unknown>).count;
    if (i === 3) todo.value = result.value as Page<FeedbackTask>;
    if (i === 4) doing.value = result.value as Page<FeedbackTask>;
  });
  busy.value = false; updated.value = new Date().toLocaleTimeString('zh-CN');
}
onMounted(load); onUnmounted(() => { mounted = false; });
</script>
<template>
  <section class="overview" aria-label="项目总览" :aria-busy="busy">
    <div class="section-heading"><div><h2>{{ project.name }}</h2><p class="notice">{{ project.paper_type || '论文项目' }}<span v-if="updated"> · {{ updated }} 读取已保存数据</span></p></div><NButton @click="load" :loading="busy"><RefreshCw :size="16" />刷新总览</NButton></div>
    <NAlert v-for="error in errors" :key="error" type="error" role="alert">{{ error }}</NAlert>
    <p v-if="busy" role="status">读取项目进度…</p>
    <div class="overview-metrics"><NButton v-for="metric in metrics" :key="metric.label" class="metric-link" @click="emit('navigate', metric.target, metric.tab)"><component :is="metric.icon" :size="20" /><span><strong>{{ metric.value ?? '—' }}</strong><small>{{ metric.label }}</small></span><ArrowRight :size="16" /></NButton></div>
    <div class="overview-columns">
      <section class="overview-surface"><h3>研究与写作</h3><ol class="workflow-list"><li v-for="(step, index) in steps" :key="step.title"><span class="step-number">{{ index + 1 }}</span><div><h4>{{ step.title }}</h4><p>{{ step.detail }}</p></div><NButton text :aria-label="`进入${step.title}`" @click="emit('navigate', step.target)"><ArrowRight :size="18" /></NButton></li></ol></section>
      <section class="overview-surface"><div class="section-heading"><h3>接下来处理</h3><NButton text @click="emit('navigate', 'feedback')">全部修改</NButton></div><p v-if="pending === 0" class="notice">暂无待处理修改，可在导师反馈中录入意见。</p><p v-else-if="pending === null" class="notice">{{ busy ? '正在读取修改待办…' : '修改待办未完整读取，请重试。' }}</p><ul class="overview-tasks"><li v-for="task in [...(doing?.results ?? []), ...(todo?.results ?? [])].slice(0, 5)" :key="task.id"><NButton text @click="emit('navigate', 'feedback')">{{ task.current.title }}</NButton><NTag size="small" :bordered="false">{{ task.current.status === 'doing' ? '处理中' : '待处理' }}</NTag><p v-if="task.current.location?.stale">关联位置需重新核对</p></li></ul></section>
      <section class="overview-surface"><h3>研究问题</h3><p class="preserve-lines">{{ manuscript?.research.question || (manuscript ? '尚未填写研究问题。' : '研究说明未读取。') }}</p><NButton @click="emit('navigate', 'writing')">打开研究说明与原稿</NButton></section>
      <section class="overview-surface"><h3>项目要求</h3><p class="preserve-lines">{{ project.requirements || '尚未填写写作要求。' }}</p><div class="actions"><NTag :type="project.policy.verified ? 'success' : 'warning'" :bordered="false">{{ project.policy.verified ? '辅助规则已核对' : '辅助规则待核对' }}</NTag><NButton text @click="emit('navigate', 'settings')">查看项目设置</NButton></div></section>
    </div>
  </section>
</template>
