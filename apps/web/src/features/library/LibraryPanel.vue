<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { ApiError, request } from "@/api/client";
import { type Page } from "@/api/types";
import { type Project } from "@/features/projects/types";
import { anchorLabel, scopeLabels, type Anchor, type SourceLocation } from "@/features/materials/types";
import SourceContext from "@/features/materials/SourceContext.vue";
type Evidence = { id: string; chunk: string; quote: string; anchor: Anchor; bibliography: { title: string; source_scope: string }; source: { file_name: string; number: number; access_state: string }; note: { text: string; tags: string[] }; revision: number };
type Result = { chunk_id: string; text: string; anchor: Anchor; source_number: number; file_name: string; source_scope: string; coverage: string; score: number | null };
type Job = { id: string; status: string; generation: number; retryable: boolean; error_message: string; progress: number };
type Index = { id: string; model_name: string; dimension: number; job: Job };
const props = defineProps<{ project: Project }>();
const emit = defineEmits<{ accessLost: [error: ApiError] }>();
const cards = ref<Page<Evidence> | null>(null);
const page = ref(1);
const query = ref("");
const tag = ref("");
const mode = ref("keyword");
const results = ref<{ results: Result[]; has_more: boolean } | null>(null);
const selected = ref<Evidence | null>(null);
const note = ref("");
const tags = ref("");
const location = ref<SourceLocation | null>(null);
const indexes = ref<Page<Index> | null>(null);
const busy = ref(false);
const error = ref("");
const message = ref("");
let key = crypto.randomUUID();
let mounted = true;
let timer: ReturnType<typeof setTimeout> | undefined;
const base = () => `projects/${props.project.id}/`;
const states: Record<string, string> = { queued: "等待执行", running: "构建中", succeeded: "成功", failed: "失败", cancelled: "已取消" };
async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return;
  busy.value = true; error.value = ""; message.value = "";
  try { await action(); }
  catch (cause) {
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      cards.value = null; results.value = null; selected.value = null; location.value = null;
      emit("accessLost", cause);
    }
  } finally { busy.value = false; }
}
async function loadCards(target = 1) {
  const params = new URLSearchParams({ q: query.value, tag: tag.value, page: String(target) });
  const result = await request<Page<Evidence>>(`${base()}evidence/?${params}`);
  if (mounted) { cards.value = result; page.value = target; }
}
async function search() {
  results.value = null; location.value = null;
  results.value = await request(`${base()}search/?${new URLSearchParams({ q: query.value, mode: mode.value })}`);
  await loadCards();
}
async function loadIndexes() {
  const result = await request<Page<Index>>(`${base()}indexes/`);
  if (mounted) indexes.value = result;
}
async function createIndex() {
  await request(`${base()}indexes/`, "POST", { idempotency_key: key, policy_version: props.project.policy.version });
  key = crypto.randomUUID(); await loadIndexes();
}
async function retry(index: Index) {
  await request(`${base()}jobs/${index.job.id}/retry/`, "POST", { generation: index.job.generation });
  await loadIndexes();
}
async function open(card: Evidence) {
  selected.value = await request<Evidence>(`${base()}evidence/${card.id}/`);
  note.value = selected.value.note.text; tags.value = selected.value.note.tags.join(", ");
  location.value = null;
}
async function locate(chunkId: string) { location.value = await request(`${base()}chunks/${chunkId}/`); }
async function save() {
  selected.value = await request(`${base()}evidence/${selected.value!.id}/`, "PATCH", { version: selected.value!.revision, note: note.value, tags: tags.value.split(/[,，]/).map(v => v.trim()).filter(Boolean) });
  await loadCards(page.value); message.value = "笔记已保存。";
}
async function poll() {
  if (!mounted) return;
  if (indexes.value?.results.some(index => ["queued", "running"].includes(index.job.status))) await perform(loadIndexes);
  if (mounted) timer = setTimeout(poll, 3000);
}
onMounted(async () => { await perform(async () => { await loadCards(); await loadIndexes(); }); void poll(); });
onUnmounted(() => { mounted = false; clearTimeout(timer); });
</script>

<template>
  <section aria-label="阅读与证据" :aria-busy="busy">
    <h2>阅读与证据</h2>
    <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="busy" role="status">处理中…</p>
    <form class="editor" @submit.prevent="perform(search)"><fieldset :disabled="busy">
      <label>项目内检索<UiInput v-model="query" maxlength="200" required :disabled="(busy)" :aria-label="'项目内检索'" /></label>
      <label>检索方式<UiSelect v-model="mode" :disabled="(busy)" :options="[({ value: 'keyword', label: '关键词' }), ({ value: 'semantic', label: '语义检索' })]" :aria-label="'检索方式'" /></label>
      <NButton attr-type="submit" :disabled="(busy)" type="primary">检索材料</NButton>
    </fieldset></form>
    <p v-if="mode === 'semantic'">语义检索会将检索词发送至配置的嵌入服务。</p>
    <UiDisclosure><template #header>检索索引</template>
      <p>重建时将有效资料片段发送至配置的嵌入服务。</p>
      <NButton v-if="project.role === 'author'" @click="perform(createIndex)" :disabled="(busy)">重建检索索引</NButton>
      <NButton @click="perform(loadIndexes)" :disabled="(busy)">刷新索引</NButton>
      <p v-if="indexes?.count === 0">尚无索引。</p>
      <ul><li v-for="index in indexes?.results" :key="index.id">
        {{ index.model_name }} · {{ index.dimension }} 维 · {{ states[index.job.status] }} · {{ index.job.progress }}%
        <p v-if="index.job.error_message">{{ index.job.error_message }}</p>
        <NButton v-if="project.role === 'author' && index.job.status === 'failed' && index.job.retryable && index.job.generation < 3" @click="perform(() => retry(index))" :disabled="(busy)">重试索引</NButton>
      </li></ul>
    </UiDisclosure>
    <div v-if="results" aria-label="检索结果">
      <p v-if="results.results.length === 0">没有匹配的有效资料。</p>
      <p v-if="results.has_more">显示前 20 项，可缩小检索范围。</p>
      <ul class="project-list"><li v-for="(result, i) in results.results" :key="`${result.chunk_id}-${i}`">
        <NButton @click="perform(() => locate(result.chunk_id))" :disabled="(busy)">{{ result.file_name }} · v{{ result.source_number }} · {{ anchorLabel(result.anchor) }}</NButton>
        <p>{{ scopeLabels[result.source_scope] }}<span v-if="result.coverage === 'partial'"> · 部分文字</span></p>
        <pre class="source-text">{{ result.text }}</pre>
      </li></ul>
    </div>
    <h3>证据卡</h3>
    <div class="actions"><label>筛选标签<UiInput v-model="tag" maxlength="30" :aria-label="'筛选标签'" /></label><NButton @click="perform(() => loadCards())" :disabled="(busy)">刷新证据卡</NButton></div>
    <p v-if="cards?.count === 0">暂无匹配的证据卡。</p>
    <ul class="project-list"><li v-for="card in cards?.results" :key="card.id">
      <NButton @click="perform(() => open(card))" :disabled="(busy)">{{ card.bibliography.title }} · v{{ card.source.number }} · {{ anchorLabel(card.anchor) }}</NButton>
      <p>{{ scopeLabels[card.bibliography.source_scope] }}<span v-if="card.source.access_state === 'withdrawn'"> · 材料已撤回</span></p>
      <p>{{ card.note.tags.join('、') }}</p>
    </li></ul>
    <div v-if="cards && (cards.next || cards.previous)" class="actions">
      <NButton @click="perform(() => loadCards(page - 1))" :disabled="(busy || !cards.previous)">上一页证据</NButton>
      <NButton @click="perform(() => loadCards(page + 1))" :disabled="(busy || !cards.next)">下一页证据</NButton>
    </div>
    <article v-if="selected" aria-label="证据详情">
      <h4>{{ selected.bibliography.title }} · {{ scopeLabels[selected.bibliography.source_scope] }}</h4>
      <h5>原文摘录</h5><pre class="source-text">{{ selected.quote }}</pre>
      <NButton @click="perform(() => locate(selected!.chunk))" :disabled="(busy)">回查原文</NButton>
      <form class="editor" @submit.prevent="perform(save)"><fieldset :disabled="busy || project.role !== 'author' || selected.source.access_state !== 'active'">
        <label>证据笔记<UiInput v-model="note" maxlength="10000" rows="3" :disabled="(busy || project.role !== 'author' || selected.source.access_state !== 'active')" type="textarea" :aria-label="'证据笔记'" /></label>
        <label>证据标签（逗号分隔）<UiInput v-model="tags" maxlength="360" :disabled="(busy || project.role !== 'author' || selected.source.access_state !== 'active')" :aria-label="'证据标签（逗号分隔）'" /></label>
        <NButton v-if="project.role === 'author' && selected.source.access_state === 'active'" attr-type="submit" :disabled="(busy || project.role !== 'author' || selected.source.access_state !== 'active')" type="primary">保存证据笔记</NButton>
      </fieldset></form>
      <NButton @click="perform(() => open(selected!))" :disabled="(busy)">重新加载证据</NButton>
    </article>
    <SourceContext v-if="location" :key="location.chunk.id" :project="project" :location="location" />
  </section>
</template>
