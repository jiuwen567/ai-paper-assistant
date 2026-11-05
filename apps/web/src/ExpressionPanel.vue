<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import type { Manuscript } from "./manuscript";
import { decisionLabels, type Suggestion } from "./expression";
import { scopeLabels } from "./sources";
import ExpressionSuggestion from "./ExpressionSuggestion.vue";
const props = defineProps<{ project: Project }>();
const emit = defineEmits<{ accessLost: [error: ApiError] }>();
type Source = { id: string; title: string; number: number; source_scope: string };
type Task = { id: string; status: string; generation: number; retryable: boolean; error_message: string; output: { summary?: string; suggestion_ids?: string[] } | null };
const manuscript = ref<Manuscript | null>(null), blockId = ref(""), sources = ref<Page<Source> | null>(null);
const sourcePage = ref(1), selectedSources = ref<Source[]>([]), question = ref(""), task = ref<Task | null>(null);
const suggestions = ref<Page<Suggestion> | null>(null), page = ref(1), state = ref("");
const busy = ref(false), error = ref("");
const canCreate = computed(() => props.project.role === "author" && props.project.policy.allowed_actions.includes("expression"));
const taskLabels: Record<string, string> = { queued: "等待执行", running: "执行中", succeeded: "成功", failed: "失败", cancelled: "已取消" };
const base = () => `projects/${props.project.id}/`;
let mounted = true, key = crypto.randomUUID(), timer: ReturnType<typeof setTimeout> | undefined;
watch([blockId, selectedSources, question], () => { key = crypto.randomUUID(); }, { deep: true });
async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return;
  busy.value = true; error.value = "";
  try { await action(); }
  catch (cause) {
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      suggestions.value = null; manuscript.value = null; sources.value = null; task.value = null; selectedSources.value = [];
      emit("accessLost", cause);
    }
  } finally { if (mounted) busy.value = false; }
}
async function loadManuscript() {
  const result = await request<Manuscript>(base() + "manuscript/");
  if (mounted) { manuscript.value = result; if (!result.blocks.some(block => block.id === blockId.value)) blockId.value = ""; }
}
async function loadSources(number = sourcePage.value) {
  const result = await request<Page<Source>>(`${base()}reading/sources/?page=${number}`);
  if (mounted) { sources.value = result; sourcePage.value = number; }
}
async function loadSuggestions(number = page.value) {
  const result = await request<Page<Suggestion>>(`${base()}suggestions/?page=${number}&state=${state.value}`);
  if (mounted) { suggestions.value = result; page.value = number; }
}
async function refresh() { await Promise.all([loadManuscript(), loadSources(), loadSuggestions()]); }
function toggleSource(source: Source) { selectedSources.value = selectedSources.value.some(item => item.id === source.id) ? selectedSources.value.filter(item => item.id !== source.id) : [...selectedSources.value, source]; }
async function create() {
  const result = await request<Task>(base() + "expressions/tasks/", "POST", {
    idempotency_key: key, manuscript_version: manuscript.value!.version, policy_version: props.project.policy.version,
    block_ids: [blockId.value], version_ids: selectedSources.value.map(item => item.id), ...(question.value.trim() ? { question: question.value } : {}),
  });
  if (mounted) { task.value = result; key = crypto.randomUUID(); if (result.status === "succeeded") await loadSuggestions(1); }
}
async function saved(result: Suggestion) {
  if (suggestions.value) suggestions.value.results = suggestions.value.results.map(item => item.id === result.id ? result : item);
  await perform(loadManuscript);
}
async function control(action: "cancel" | "retry") {
  const result = await request<Task>(`${base()}jobs/${task.value!.id}/${action}/`, "POST", { generation: task.value!.generation });
  if (mounted) task.value = result;
}
async function poll() {
  if (!mounted) return;
  if (task.value && ["queued", "running"].includes(task.value.status)) await perform(async () => {
    const result = await request<Task>(`${base()}jobs/${task.value!.id}/`);
    if (!mounted) return;
    task.value = result;
    if (result.status === "succeeded") await loadSuggestions(1);
  });
  if (mounted) timer = setTimeout(poll, 2000);
}
onMounted(async () => { await perform(refresh); void poll(); });
onUnmounted(() => { mounted = false; clearTimeout(timer); });
</script>
<template>
  <section aria-label="表达建议" :aria-busy="busy">
    <h2>表达建议</h2>
    <p v-if="error" role="alert" class="error">{{ error }}</p><p v-if="busy" role="status">处理中…</p>
    <button :disabled="busy" @click="perform(refresh)">刷新表达区</button>
    <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(create)"><fieldset :disabled="busy">
      <label>已保存原稿 v{{ manuscript?.version ?? 0 }}<select v-model="blockId" aria-label="建议原稿块"><option value="">选择原稿块</option><option v-for="(block, index) in manuscript?.blocks" :key="block.id" :value="block.id">块 {{ index + 1 }}：{{ block.text.slice(0, 80) || '空正文' }}</option></select></label>
      <details><summary>选择表达依据（{{ selectedSources.length }}/5）</summary><p v-if="!sources?.count">暂无已解析资料，只能检查原稿表达。</p><label v-for="source in sources?.results" :key="source.id" class="check-label"><input type="checkbox" :checked="selectedSources.some(item => item.id === source.id)" :disabled="selectedSources.length >= 5 && !selectedSources.some(item => item.id === source.id)" @change="toggleSource(source)" />{{ source.title }} · v{{ source.number }} · {{ scopeLabels[source.source_scope] }}</label><div v-if="sources && (sources.next || sources.previous)" class="actions"><button type="button" :disabled="!sources.previous" @click="perform(() => loadSources(sourcePage - 1))">上一页表达依据</button><button type="button" :disabled="!sources.next" @click="perform(() => loadSources(sourcePage + 1))">下一页表达依据</button></div></details>
      <div class="actions"><button v-for="source in selectedSources" :key="source.id" type="button" @click="toggleSource(source)">移除表达依据 {{ source.title }}</button></div>
      <label>表达重点<textarea v-model="question" maxlength="500" rows="2" /></label><button type="submit" :disabled="!canCreate || !blockId">生成表达建议</button><p v-if="!canCreate">当前规则未允许表达建议。</p>
    </fieldset></form>
    <div v-if="task" role="status">{{ taskLabels[task.status] }}<p v-if="task.error_message">{{ task.error_message }}</p><p v-if="task.output?.summary">模型说明：{{ task.output.summary }}</p><button v-if="['queued','running'].includes(task.status)" :disabled="busy" @click="perform(() => control('cancel'))">取消表达任务</button><button v-if="task.status === 'failed' && task.retryable" :disabled="busy" @click="perform(() => control('retry'))">重试表达任务</button></div>
    <form class="actions" @submit.prevent="perform(() => loadSuggestions(1))"><label>建议状态<select v-model="state" :disabled="busy"><option value="">全部建议</option><option value="pending">待审阅</option><option v-for="(label, value) in decisionLabels" :key="value" :value="value">{{ label }}</option></select></label><button :disabled="busy" type="submit">筛选建议</button></form>
    <p v-if="suggestions?.count === 0">暂无符合条件的建议。</p>
    <ExpressionSuggestion v-for="suggestion in suggestions?.results" :key="suggestion.id" :project="project" :suggestion="suggestion" @saved="saved" @access-lost="cause => perform(async () => { throw cause; })" />
    <div v-if="suggestions && (suggestions.next || suggestions.previous)" class="actions"><button :disabled="busy || !suggestions.previous" @click="perform(() => loadSuggestions(page - 1))">上一页建议</button><button :disabled="busy || !suggestions.next" @click="perform(() => loadSuggestions(page + 1))">下一页建议</button></div>
  </section>
</template>
