<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import SourceContext from "./SourceContext.vue";
import BibliographyEditor from "./BibliographyEditor.vue";
import { anchorLabel, type Chunk, type SourceLocation as Location } from "./sources";
type Job = { id: string; status: string; generation: number; progress: number; retryable: boolean; error_message: string };
type Run = { id: string; number: number; parser_version: string; job: Job; published_at: string | null; warnings: string[]; coverage: string };
const props = defineProps<{ project: Project; version: { id: string; number: number; file_name: string } }>();
const emit = defineEmits<{ accessLost: [error: ApiError] }>();
const runs = ref<Page<Run> | null>(null);
const selected = ref<Run | null>(null);
const chunks = ref<Page<Chunk> | null>(null);
const location = ref<Location | null>(null);
const runPage = ref(1);
const chunkPage = ref(1);
const busy = ref(false);
const error = ref("");
const aiNotice = ref("");
let aiKey = crypto.randomUUID();
let key = crypto.randomUUID();
let mounted = true;
let timer: ReturnType<typeof setTimeout> | undefined;
const states: Record<string, string> = { queued: "等待解析", running: "解析中", succeeded: "解析成功", failed: "解析失败", cancelled: "已取消" };
const base = () => `projects/${props.project.id}/`;

async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return;
  busy.value = true; error.value = "";
  try { await action(); }
  catch (cause) {
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      runs.value = null; chunks.value = null; location.value = null; selected.value = null;
      emit("accessLost", cause);
    }
  } finally { busy.value = false; }
}
async function loadChunks(run: Run, target = 1) {
  const result = await request<Page<Chunk>>(`${base()}parses/${run.id}/chunks/?page=${target}`);
  if (mounted) { chunks.value = result; chunkPage.value = target; }
}
async function select(run: Run) {
  selected.value = run; chunks.value = null; location.value = null;
  if (run.published_at) await loadChunks(run);
}
async function load(target = runPage.value) {
  const result = await request<Page<Run>>(`${base()}files/${props.version.id}/parses/?page=${target}`);
  if (!mounted) return;
  runs.value = result; runPage.value = target;
  const refreshed = result.results.find(run => run.id === selected.value?.id);
  if (refreshed) {
    selected.value = refreshed;
    if (refreshed.published_at && !chunks.value) await loadChunks(refreshed);
  } else if (result.results[0]) await select(result.results[0]);
  else { selected.value = null; chunks.value = null; location.value = null; }
}
async function create() {
  const run = await request<Run>(`${base()}files/${props.version.id}/parses/`, "POST", { idempotency_key: key });
  key = crypto.randomUUID();
  await select(run); await load(1);
}
async function control(action: "cancel" | "retry") {
  const job = selected.value!.job;
  await request(`${base()}jobs/${job.id}/${action}/`, "POST", { generation: job.generation });
  await load();
}
async function createAI() {
  aiNotice.value = "";
  await request(`${base()}ai-tasks/`, "POST", {
    idempotency_key: aiKey, policy_version: props.project.policy.version, version_ids: [props.version.id],
  });
  aiKey = crypto.randomUUID();
  if (mounted) aiNotice.value = "摘记任务已提交，可在后台任务查看。";
}
async function locate(chunk: Chunk) {
  const result = await request<Location>(`${base()}chunks/${chunk.id}/`);
  if (mounted) location.value = result;
}
async function poll() {
  if (!mounted) return;
  // 终态停止自动请求；刷新和重新解析仍可手动触发。
  if (!runs.value || runs.value.results.some(run => ["queued", "running"].includes(run.job.status))) await perform(() => load());
  if (mounted) timer = setTimeout(poll, 2000);
}
onMounted(poll);
onUnmounted(() => { mounted = false; clearTimeout(timer); });
</script>

<template>
  <section class="source-reader" aria-label="原文定位" :aria-busy="busy">
    <h3>{{ version.file_name }} · v{{ version.number }}</h3>
    <BibliographyEditor :key="version.id" :project="project" :version-id="version.id" />
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="aiNotice" role="status">{{ aiNotice }}</p>
    <p v-if="busy" role="status">加载中…</p>
    <div class="actions">
      <button :disabled="busy" @click="perform(() => load())">刷新解析</button>
      <button v-if="project.role === 'author'" :disabled="busy" @click="perform(create)">{{ runs?.count ? '重新解析' : '解析材料' }}</button>
      <button v-if="project.role === 'author' && project.policy.allowed_actions.includes('reading')" :disabled="busy || !runs?.results.some(run => run.published_at)" @click="perform(createAI)">AI 摘记</button>
      <a :href="`/api/v1/${base()}files/${version.id}/`">下载原件 v{{ version.number }}</a>
    </div>
    <p v-if="runs?.count === 0">尚无解析记录。</p>
    <ul class="project-list"><li v-for="run in runs?.results" :key="run.id">
      <button :disabled="busy" :aria-pressed="selected?.id === run.id" @click="perform(() => select(run))">解析 #{{ run.number }} · {{ states[run.job.status] }}</button>
    </li></ul>
    <div v-if="runs && (runs.next || runs.previous)" class="actions">
      <button :disabled="busy || !runs.previous" @click="perform(() => load(runPage - 1))">较新解析</button>
      <button :disabled="busy || !runs.next" @click="perform(() => load(runPage + 1))">较旧解析</button>
    </div>
    <template v-if="selected">
      <p role="status">{{ states[selected.job.status] }} · {{ selected.job.progress }}%<span v-if="selected.coverage === 'partial'"> · 部分文字</span></p>
      <p v-if="selected.job.error_message" role="alert">{{ selected.job.error_message }}</p>
      <div v-if="project.role === 'author'" class="actions">
        <button v-if="['queued', 'running'].includes(selected.job.status)" :disabled="busy" @click="perform(() => control('cancel'))">取消解析</button>
        <button v-if="selected.job.status === 'failed' && selected.job.retryable && selected.job.generation < 3" :disabled="busy" @click="perform(() => control('retry'))">重试解析</button>
      </div>
      <p v-for="warning in selected.warnings" :key="warning">{{ warning }}</p>
      <details><summary>解析版本</summary>{{ selected.parser_version }}</details>
      <ol class="source-chunks"><li v-for="chunk in chunks?.results" :key="chunk.id">
        <button :disabled="busy" :aria-pressed="location?.chunk.id === chunk.id" @click="perform(() => locate(chunk))">
          {{ anchorLabel(chunk.anchor) }}<span v-if="chunk.heading_level"> · {{ chunk.heading_level }} 级标题</span>
          <span class="chunk-excerpt">{{ chunk.text.slice(0, 160) }}</span>
        </button>
      </li></ol>
      <div v-if="chunks && (chunks.previous || chunks.next)" class="actions">
        <button :disabled="busy || !chunks.previous" @click="perform(() => loadChunks(selected!, chunkPage - 1))">上一页片段</button>
        <button :disabled="busy || !chunks.next" @click="perform(() => loadChunks(selected!, chunkPage + 1))">下一页片段</button>
      </div>
    </template>
    <SourceContext v-if="location" :key="location.chunk.id" :project="project" :location="location" />
  </section>
</template>
