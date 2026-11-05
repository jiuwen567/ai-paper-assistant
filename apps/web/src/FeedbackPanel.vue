<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import { progressLabels, type Feedback, type FeedbackCandidate, type FeedbackTask } from "./feedback";
import type { Manuscript } from "./manuscript";
import { anchorLabel, type Anchor, type SourceLocation } from "./sources";
import { statusLabels } from "./disclosure";
import FeedbackCandidateCard from "./FeedbackCandidateCard.vue";
import FeedbackTaskCard from "./FeedbackTaskCard.vue";
import SourceContext from "./SourceContext.vue";
const props = defineProps<{ project: Project }>();
const emit = defineEmits<{ accessLost: [error: ApiError]; dirtyChange: [value: boolean] }>();
type Evidence = { id: string; chunk: string; quote: string; anchor: Anchor; source: { file_name: string; access_state: string } };
type Job = { id: string; status: string; generation: number; retryable: boolean; error_message: string; output: { summary: string } | null };
const records = ref<Page<Feedback> | null>(null), tasks = ref<Page<FeedbackTask> | null>(null), candidates = ref<Page<FeedbackCandidate> | null>(null), evidence = ref<Page<Evidence> | null>(null);
const selected = ref<Feedback | null>(null), manuscript = ref<Manuscript | null>(null), sourceContext = ref<SourceLocation | null>(null), job = ref<Job | null>(null);
const recordPage = ref(1), taskPage = ref(1), candidatePage = ref(1), evidencePage = ref(1), filter = ref("");
const text = ref(""), sourceLabel = ref(""), source = ref<Evidence | null>(null), blockId = ref(""), title = ref(""), instruction = ref("");
const busy = ref(false), error = ref(""), dirtyTasks = ref(new Set<string>()), dirtyCandidates = ref(new Set<string>());
const dirty = computed(() => props.project.role === "author" && (!!text.value || !!sourceLabel.value || !!title.value || !!instruction.value || !!dirtyTasks.value.size || !!dirtyCandidates.value.size));
const chosenLocation = computed(() => ({ manuscript_version: blockId.value ? manuscript.value?.version ?? null : null, block_id: blockId.value || null }));
const base = () => `projects/${props.project.id}/`;
let mounted = true, recordKey = crypto.randomUUID(), taskKey = crypto.randomUUID(), splitKey = crypto.randomUUID(), timer: ReturnType<typeof setTimeout> | undefined;
watch([text, sourceLabel, source, chosenLocation], () => { recordKey = crypto.randomUUID(); }, { deep: true });
watch([title, instruction, chosenLocation, selected], () => { taskKey = crypto.randomUUID(); splitKey = crypto.randomUUID(); });
watch(dirty, value => emit("dirtyChange", value));
function taskDirty(id: string, value: boolean) { const next = new Set(dirtyTasks.value); if (value) next.add(id); else next.delete(id); dirtyTasks.value = next; }
function candidateDirty(id: string, value: boolean) { const next = new Set(dirtyCandidates.value); if (value) next.add(id); else next.delete(id); dirtyCandidates.value = next; }
function accessLost(cause: ApiError) { records.value = null; tasks.value = null; candidates.value = null; selected.value = null; evidence.value = null; manuscript.value = null; sourceContext.value = null; text.value = ""; sourceLabel.value = ""; source.value = null; title.value = ""; instruction.value = ""; emit("accessLost", cause); }
async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return; busy.value = true; error.value = "";
  try { await action(); } catch (cause) { if (!mounted) return; error.value = cause instanceof Error ? cause.message : "请求失败，请重试。"; if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) accessLost(cause); }
  finally { if (mounted) busy.value = false; }
}
async function loadRecords(number = recordPage.value) { const value = await request<Page<Feedback>>(`${base()}feedback/?page=${number}`); if (mounted) { records.value = value; recordPage.value = number; } }
async function loadTasks(number = taskPage.value) {
  if (dirtyTasks.value.size && !window.confirm("刷新待办列表可能移除当前卡片，确认放弃未保存修改？")) return;
  const value = await request<Page<FeedbackTask>>(`${base()}feedback-tasks/?page=${number}&status=${filter.value}`); if (mounted) { tasks.value = value; taskPage.value = number; }
}
async function loadCandidates(number = 1) { if (!selected.value) return; if (number !== candidatePage.value && dirtyCandidates.value.size && !window.confirm("切换候选页将丢弃未保存的候选编辑，是否继续？")) return; const value = await request<Page<FeedbackCandidate>>(`${base()}feedback/${selected.value.id}/candidates/?page=${number}`); if (mounted) { candidates.value = value; candidatePage.value = number; } }
async function loadEvidence(number = evidencePage.value) { const value = await request<Page<Evidence>>(`${base()}evidence/?page=${number}`); if (mounted) { evidence.value = value; evidencePage.value = number; } }
async function refresh() {
  const value = await request<Manuscript>(base() + "manuscript/"); if (!mounted) return;
  if (manuscript.value && value.version !== manuscript.value.version) blockId.value = "";
  manuscript.value = value; await Promise.all([loadRecords(), loadTasks(), loadEvidence()]);
  if (selected.value) { const item = await request<Feedback>(`${base()}feedback/${selected.value.id}/`); if (mounted) { selected.value = item; await loadCandidates(candidatePage.value); } }
}
async function open(item: Feedback) {
  if ((title.value || instruction.value || dirtyCandidates.value.size) && !window.confirm("切换意见将清除未保存的候选和待办草稿，是否继续？")) return;
  selected.value = item; title.value = ""; instruction.value = ""; sourceContext.value = null; candidates.value = null; job.value = null;
  blockId.value = item.location && !item.location.stale && manuscript.value?.version === item.location.manuscript_version ? item.location.block_id : "";
  await loadCandidates();
}
async function createFeedback() {
  const value = await request<Feedback>(base() + "feedback/", "POST", { request_key: recordKey, text: text.value, source_label: sourceLabel.value, source_chunk_id: source.value?.chunk ?? null, ...chosenLocation.value });
  if (mounted) { text.value = ""; sourceLabel.value = ""; source.value = null; await loadRecords(1); await open(value); }
}
async function split() { const value = await request<Job>(`${base()}feedback/${selected.value!.id}/split/`, "POST", { idempotency_key: splitKey, policy_version: props.project.policy.version, ...chosenLocation.value }); if (mounted) { job.value = value; splitKey = crypto.randomUUID(); } }
async function createTask() { await request(`${base()}feedback/${selected.value!.id}/tasks/`, "POST", { request_key: taskKey, title: title.value, instruction: instruction.value, ...chosenLocation.value }); if (mounted) { title.value = ""; instruction.value = ""; await loadTasks(1); } }
async function control(action: string) { const value = await request<Job>(`${base()}jobs/${job.value!.id}/${action}/`, "POST", { generation: job.value!.generation }); if (mounted) job.value = value; }
async function locate() { const value = await request<SourceLocation>(`${base()}chunks/${selected.value!.source_chunk_id}/`); if (mounted) sourceContext.value = value; }
async function candidateSaved() { await perform(async () => { await loadCandidates(candidatePage.value); await loadTasks(1); }); }
function taskSaved(value: FeedbackTask) { if (tasks.value) tasks.value.results = tasks.value.results.map(item => item.id === value.id ? value : item); }
async function poll() { if (!mounted) return; if (job.value && ['queued','running'].includes(job.value.status)) await perform(async () => { const value = await request<Job>(`${base()}jobs/${job.value!.id}/`); if (mounted) { job.value = value; if (value.status === 'succeeded') await loadCandidates(); } }); if (mounted) timer = setTimeout(poll, 2000); }
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value) { event.preventDefault(); event.returnValue = ""; } }
onMounted(async () => { window.addEventListener("beforeunload", beforeUnload); await perform(refresh); void poll(); });
onUnmounted(() => { mounted = false; clearTimeout(timer); window.removeEventListener("beforeunload", beforeUnload); emit("dirtyChange", false); });
</script>
<template>
  <section aria-label="导师反馈与修改待办" :aria-busy="busy"><h2>导师反馈与修改待办</h2>
    <p v-if="error" role="alert" class="error">{{ error }}</p><p v-if="busy" role="status">处理中…</p><button :disabled="busy" @click="perform(refresh)">刷新反馈区</button>
    <label>关联稿件 v{{ manuscript?.version ?? 0 }}<select v-model="blockId" aria-label="反馈关联正文" :disabled="busy || project.role !== 'author'"><option value="">暂不关联正文</option><option v-for="(block, index) in manuscript?.blocks" :key="block.id" :value="block.id">块 {{ index + 1 }}：{{ block.text.slice(0, 60) }}</option></select></label>
    <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(createFeedback)"><fieldset :disabled="busy"><h3>录入意见（作者转录）</h3>
      <label>原始意见<textarea v-model="text" rows="3" maxlength="5000" required /></label><label>意见来源<input v-model="sourceLabel" maxlength="500" required /></label>
      <details><summary>关联已保存的来源片段</summary><p v-if="!evidence?.count">暂无证据卡，可在资料区保存来源片段。</p><button v-for="item in evidence?.results" :key="item.id" type="button" :disabled="item.source.access_state !== 'active'" @click="source = item">{{ item.source.file_name }} · {{ anchorLabel(item.anchor) }}：{{ item.quote.slice(0, 70) }}</button><button type="button" :disabled="!evidence?.previous" @click="perform(() => loadEvidence(evidencePage - 1))">上一页反馈来源</button><button type="button" :disabled="!evidence?.next" @click="perform(() => loadEvidence(evidencePage + 1))">下一页反馈来源</button></details>
      <p v-if="source">{{ source.source.file_name }} · {{ anchorLabel(source.anchor) }}<button type="button" @click="source = null">取消来源片段</button></p><button type="submit">保存原始意见</button>
    </fieldset></form>
    <p v-if="records?.count === 0">暂无导师意见。</p><button v-for="item in records?.results" :key="item.id" :disabled="busy" @click="perform(() => open(item))">{{ item.text.slice(0, 80) }}</button>
    <div v-if="records && (records.next || records.previous)" class="actions"><button :disabled="busy || !records.previous" @click="perform(() => loadRecords(recordPage - 1))">上一页意见</button><button :disabled="busy || !records.next" @click="perform(() => loadRecords(recordPage + 1))">下一页意见</button></div>
    <section v-if="selected" aria-label="所选原始反馈"><h3>原始意见（作者转录）</h3><blockquote>{{ selected.text }}</blockquote><p>{{ selected.source_label }}</p><p v-if="selected.location">原稿 v{{ selected.location.manuscript_version }} · 块 {{ selected.location.position }}{{ selected.location.stale ? ' · 位置已失效，请重新关联' : '' }}</p><button v-if="selected.source_chunk_id" :disabled="busy" @click="perform(locate)">回查意见来源</button><SourceContext v-if="sourceContext" :project="project" :location="sourceContext" />
      <button v-if="project.role === 'author'" :disabled="busy || !project.policy.allowed_actions.includes('feedback')" @click="perform(split)">AI 拆分候选任务</button>
      <div v-if="job" role="status">{{ statusLabels[job.status] }}<p>{{ job.error_message || job.output?.summary }}</p><button v-if="['queued','running'].includes(job.status)" :disabled="busy" @click="perform(() => control('cancel'))">取消拆分</button><button v-if="job.status === 'failed' && job.retryable" :disabled="busy" @click="perform(() => control('retry'))">重试拆分</button></div>
      <p v-if="candidates?.count === 0">暂无候选任务。</p><FeedbackCandidateCard v-for="candidate in candidates?.results" :key="candidate.id" :project="project" :candidate="candidate" :location="chosenLocation" @saved="candidateSaved" @dirty-change="candidateDirty" @access-lost="accessLost" />
      <div v-if="candidates && (candidates.next || candidates.previous)"><button :disabled="busy || !candidates.previous" @click="perform(() => loadCandidates(candidatePage - 1))">上一页候选</button><button :disabled="busy || !candidates.next" @click="perform(() => loadCandidates(candidatePage + 1))">下一页候选</button></div>
      <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(createTask)"><fieldset :disabled="busy"><h4>作者登记待办</h4><label>新待办标题<input v-model="title" maxlength="200" required /></label><label>新待办要求<textarea v-model="instruction" maxlength="2000" rows="2" required /></label><button type="submit">登记修改待办</button></fieldset></form>
    </section>
    <h3>修改待办</h3><form class="actions" @submit.prevent="perform(() => loadTasks(1))"><label>待办状态<select v-model="filter"><option value="">全部</option><option v-for="(label, value) in progressLabels" :key="value" :value="value">{{ label }}</option></select></label><button :disabled="busy">筛选待办</button></form><p v-if="tasks?.count === 0">暂无符合条件的待办。</p>
    <FeedbackTaskCard v-for="task in tasks?.results" :key="task.id" :project="project" :task="task" @saved="taskSaved" @dirty-change="taskDirty" @access-lost="accessLost" />
    <div v-if="tasks && (tasks.next || tasks.previous)"><button :disabled="busy || !tasks.previous" @click="perform(() => loadTasks(taskPage - 1))">上一页待办</button><button :disabled="busy || !tasks.next" @click="perform(() => loadTasks(taskPage + 1))">下一页待办</button></div>
  </section>
</template>
