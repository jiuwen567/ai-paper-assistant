<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import { scopeLabels, type SourceLocation } from "./sources";
import { readingFields, type ReadingField, type ReadingRecord } from "./reading";
import SourceContext from "./SourceContext.vue";
const props = defineProps<{ project: Project }>();
const emit = defineEmits<{ accessLost: [error: ApiError] }>();
type Source = { id: string; title: string; file_name: string; number: number; source_scope: string };
type Task = { id: string; status: string; generation: number; retryable: boolean; error_message: string; output: { reading_id?: string } | null };
const sources = ref<Page<Source> | null>(null), records = ref<Page<ReadingRecord> | null>(null);
const sourcePage = ref(1), recordPage = ref(1);
const selectedSources = ref<Source[]>([]), question = ref("");
const selected = ref<ReadingRecord | null>(null), location = ref<SourceLocation | null>(null);
const task = ref<Task | null>(null), drafts = ref<Record<string, string>>({}), note = ref(""), verified = ref(false);
const busy = ref(false), error = ref(""), message = ref("");
const purpose = computed(() => selectedSources.value.length > 1 ? "comparison" : "reading");
const canCreate = computed(() => props.project.role === "author" && props.project.policy.allowed_actions.includes(purpose.value));
const states: Record<string, string> = { queued: "等待执行", running: "执行中", succeeded: "成功", failed: "失败", cancelled: "已取消" };
const base = () => `projects/${props.project.id}/`;
const fieldKey = (id: string, field: ReadingField) => `${id}:${field}`;
let mounted = true, key = crypto.randomUUID();
let timer: ReturnType<typeof setTimeout> | undefined;
watch([selectedSources, question], () => { key = crypto.randomUUID(); }, { deep: true });
async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return;
  busy.value = true; error.value = ""; message.value = "";
  try { await action(); }
  catch (cause) {
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      sources.value = null; records.value = null; selected.value = null; location.value = null; task.value = null;
      selectedSources.value = []; drafts.value = {}; note.value = "";
      emit("accessLost", cause);
    }
  } finally { busy.value = false; }
}
async function loadSources(page = sourcePage.value) {
  const data = await request<Page<Source>>(`${base()}reading/sources/?page=${page}`);
  if (mounted) { sources.value = data; sourcePage.value = page; }
}
async function loadRecords(page = recordPage.value) {
  const data = await request<Page<ReadingRecord>>(`${base()}reading/?page=${page}`);
  if (mounted) { records.value = data; recordPage.value = page; }
}
function toggle(source: Source) {
  selectedSources.value = selectedSources.value.some(item => item.id === source.id) ? selectedSources.value.filter(item => item.id !== source.id) : [...selectedSources.value, source];
}
function hydrate(record: ReadingRecord) {
  selected.value = record; location.value = null;
  drafts.value = Object.fromEntries((record.author_revision?.edits ?? []).map(edit => [fieldKey(edit.version_id, edit.field), edit.text]));
  note.value = record.author_revision?.note ?? "";
  verified.value = !record.sources_changed && !!record.author_revision?.verified;
}
async function open(id: string) {
  const record = await request<ReadingRecord>(`${base()}reading/${id}/`);
  if (mounted) {
    hydrate(record);
    if (records.value) records.value.results = records.value.results.map(item => item.id === id ? record : item);
  }
}
async function create() {
  const result = await request<Task>(`${base()}reading/tasks/`, "POST", {
    idempotency_key: key, policy_version: props.project.policy.version, purpose: purpose.value,
    version_ids: selectedSources.value.map(item => item.id), ...(question.value.trim() ? { question: question.value } : {}),
  });
  key = crypto.randomUUID();
  if (mounted) task.value = result;
}
async function control(action: "cancel" | "retry") {
  const result = await request<Task>(`${base()}jobs/${task.value!.id}/${action}/`, "POST", { generation: task.value!.generation });
  if (mounted) task.value = result;
}
async function locate(id: string) {
  const result = await request<SourceLocation>(`${base()}chunks/${id}/`);
  if (mounted) location.value = result;
}
async function save() {
  const edits = selected.value!.model_output.documents.flatMap(document => (Object.keys(readingFields) as ReadingField[]).flatMap(field => {
    const text = drafts.value[fieldKey(document.version_id, field)]?.trim();
    return text ? [{ version_id: document.version_id, field, text }] : [];
  }));
  const result = await request<ReadingRecord>(`${base()}reading/${selected.value!.id}/`, "PATCH", { version: selected.value!.revision, edits, note: note.value, verified: verified.value });
  if (mounted) hydrate(result);
  await loadRecords(); message.value = "作者修订已保存。";
}
async function poll() {
  if (!mounted) return;
  if (task.value && ["queued", "running"].includes(task.value.status)) await perform(async () => {
    const result = await request<Task>(`${base()}jobs/${task.value!.id}/`);
    if (!mounted) return;
    task.value = result;
    if (result.status === "succeeded" && result.output?.reading_id) { await loadRecords(1); await open(result.output.reading_id); }
  });
  if (mounted) timer = setTimeout(poll, 2000);
}
onMounted(async () => { await perform(async () => { await loadSources(); await loadRecords(); }); void poll(); });
onUnmounted(() => { mounted = false; clearTimeout(timer); });
</script>

<template>
  <section aria-label="阅读摘记与比较" :aria-busy="busy">
    <h2>阅读摘记与比较</h2>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="busy" role="status">处理中…</p>
    <div class="actions"><button :disabled="busy" @click="perform(async () => { await loadSources(); await loadRecords(); })">刷新阅读区</button></div>
    <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(create)">
      <fieldset :disabled="busy">
        <details><summary>选择已解析资料（{{ selectedSources.length }}/5）</summary>
          <p v-if="sources?.count === 0">暂无可阅读的已解析资料。</p>
          <label v-for="source in sources?.results" :key="source.id" class="check-label">
            <input type="checkbox" :checked="selectedSources.some(item => item.id === source.id)" :disabled="selectedSources.length >= 5 && !selectedSources.some(item => item.id === source.id)" @change="toggle(source)" />
            {{ source.title }} · v{{ source.number }} · {{ scopeLabels[source.source_scope] }}
          </label>
          <div v-if="sources && (sources.previous || sources.next)" class="actions">
            <button type="button" :disabled="!sources.previous" @click="perform(() => loadSources(sourcePage - 1))">上一页资料</button>
            <button type="button" :disabled="!sources.next" @click="perform(() => loadSources(sourcePage + 1))">下一页资料</button>
          </div>
        </details>
        <div v-if="selectedSources.length" class="actions"><button v-for="source in selectedSources" :key="source.id" type="button" @click="toggle(source)">移除 {{ source.title }} v{{ source.number }}</button></div>
        <label>阅读问题<textarea v-model="question" maxlength="500" rows="2" /></label>
        <button type="submit" :disabled="!canCreate || !selectedSources.length">{{ purpose === 'comparison' ? '开始比较' : '开始阅读' }}</button>
        <p v-if="!canCreate">当前规则未允许{{ purpose === 'comparison' ? '文献比较' : '文献阅读' }}。</p>
      </fieldset>
    </form>
    <div v-if="task" role="status">
      {{ states[task.status] }}<p v-if="task.error_message">{{ task.error_message }}</p>
      <button v-if="['queued', 'running'].includes(task.status)" :disabled="busy" @click="perform(() => control('cancel'))">取消阅读任务</button>
      <button v-if="task.status === 'failed' && task.retryable" :disabled="busy" @click="perform(() => control('retry'))">重试阅读任务</button>
    </div>
    <p v-if="records?.count === 0">暂无阅读结果。</p>
    <ul class="project-list"><li v-for="record in records?.results" :key="record.id">
      <button :disabled="busy" :aria-pressed="selected?.id === record.id" @click="perform(() => open(record.id))">
        {{ record.model_output.documents.map(document => document.title).join(' / ') }} · {{ record.purpose === 'comparison' ? '比较' : '阅读' }} · {{ record.sources_changed ? '来源已变化' : record.author_revision?.verified ? '作者已核对' : '待核对' }}
      </button>
    </li></ul>
    <div v-if="records && (records.previous || records.next)" class="actions">
      <button :disabled="busy || !records.previous" @click="perform(() => loadRecords(recordPage - 1))">上一页阅读结果</button>
      <button :disabled="busy || !records.next" @click="perform(() => loadRecords(recordPage + 1))">下一页阅读结果</button>
    </div>
    <article v-if="selected" aria-label="阅读结果">
      <h3>{{ selected.purpose === 'comparison' ? '文献比较' : '阅读摘记' }}</h3>
      <p>{{ selected.question }}</p>
      <p v-if="selected.sources_changed" role="status">来源已变化，需重新阅读并核对。</p>
      <button :disabled="busy" @click="perform(() => open(selected!.id))">重新加载结果</button>
      <div class="reading-table-wrap" tabindex="0" aria-label="按资料比较提取结果">
        <table class="reading-table"><thead><tr><th scope="col">项目</th><th v-for="document in selected.model_output.documents" :key="document.version_id" scope="col">{{ document.title }} · v{{ document.source_number }}<br />{{ scopeLabels[document.source_scope] }}</th></tr></thead>
          <tbody><tr v-for="(label, field) in readingFields" :key="field"><th scope="row">{{ label }}</th>
            <td v-for="document in selected.model_output.documents" :key="document.version_id">
              <p>{{ drafts[fieldKey(document.version_id, field)] || document.fields[field].text }}</p>
              <p v-if="drafts[fieldKey(document.version_id, field)]">作者修订</p>
              <details v-if="document.fields[field].citations.length"><summary>原文依据</summary>
                <div v-for="(citation, index) in document.fields[field].citations" :key="index"><blockquote>{{ citation.quote }}</blockquote><button :disabled="busy" @click="perform(() => locate(citation.chunk_id))">回查原文 {{ index + 1 }}</button></div>
              </details>
              <details v-if="project.role === 'author'"><summary>修订此项</summary>
                <p>模型提取：{{ document.fields[field].text }}</p>
                <label>{{ document.title }} · {{ label }} · 作者修订<textarea v-model="drafts[fieldKey(document.version_id, field)]" :disabled="busy" maxlength="2000" rows="3" @input="verified = false" /></label>
              </details>
            </td>
          </tr></tbody>
        </table>
      </div>
      <div v-if="selected.model_output.comparison">
        <p>{{ { comparable: '条件可比（待核对）', not_comparable: '条件不可比', uncertain: '可比性不确定' }[selected.model_output.comparison.status] }}</p>
        <p>{{ selected.model_output.comparison.reason }}</p>
        <details v-if="selected.model_output.comparison.citations.length"><summary>比较依据</summary><div v-for="(citation, index) in selected.model_output.comparison.citations" :key="index"><blockquote>{{ citation.quote }}</blockquote><button :disabled="busy" @click="perform(() => locate(citation.chunk_id))">回查比较依据 {{ index + 1 }}</button></div></details>
      </div>
      <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(save)"><fieldset :disabled="busy">
        <label>作者理解<textarea v-model="note" maxlength="5000" rows="3" @input="verified = false" /></label>
        <label class="check-label"><input v-model="verified" type="checkbox" :disabled="selected.sources_changed" />已逐项核对原文</label>
        <button type="submit">保存作者修订与核对状态</button>
      </fieldset></form>
      <p v-else-if="selected.author_revision?.note">作者理解：{{ selected.author_revision.note }}</p>
      <SourceContext v-if="location" :key="location.chunk.id" :project="project" :location="location" />
    </article>
  </section>
</template>

<style scoped>
.reading-table-wrap { overflow-x: auto; margin-block: 1rem; }
.reading-table { border-collapse: collapse; width: 100%; }
.reading-table th, .reading-table td { vertical-align: top; text-align: left; padding: .65rem; border-bottom: 1px solid #d9e2d2; }
.reading-table td, .reading-table th:not(:first-child) { min-width: 14rem; max-width: 24rem; }
.reading-table th:first-child { min-width: 5rem; }
.reading-table textarea { width: 100%; box-sizing: border-box; }
blockquote { margin: .5rem 0; padding-left: .5rem; border-left: 3px solid #a6b99b; white-space: pre-wrap; }
</style>
