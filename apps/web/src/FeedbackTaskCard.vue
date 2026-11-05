<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import { mentorLabels, progressLabels, type Feedback, type FeedbackLocation, type FeedbackTask, type TaskProgress } from "./feedback";
import type { Manuscript } from "./manuscript";
const props = defineProps<{ project: Project; task: FeedbackTask }>();
const emit = defineEmits<{ saved: [task: FeedbackTask]; accessLost: [error: ApiError]; dirtyChange: [id: string, dirty: boolean] }>();
const current = ref(props.task), manuscript = ref<Manuscript | null>(null), feedback = ref<Feedback | null>(null), history = ref<Page<TaskProgress> | null>(null), historyPage = ref(1);
const title = ref(""), instruction = ref(""), status = ref<TaskProgress['status']>("todo"), note = ref(""), result = ref<TaskProgress['result_kind']>("pending"), linked = ref<FeedbackLocation | null>(null), chosen = ref("");
const version = ref(1), baseline = ref(""), busy = ref(false), error = ref(""), message = ref("");
const mentorStatus = ref<"confirmed" | "changes_requested">("confirmed"), mentorText = ref(""), mentorSource = ref("");
const mentorVersion = ref(props.task.current.number);
const payload = () => ({ title: title.value, instruction: instruction.value, status: status.value, note: note.value, result_kind: status.value === 'completed' ? result.value : 'pending', manuscript_version: linked.value?.manuscript_version ?? null, block_id: linked.value?.block_id ?? null });
const dirty = computed(() => props.project.role === "author" && baseline.value !== "" && JSON.stringify(payload()) !== baseline.value);
const versionChanged = computed(() => version.value !== current.value.current.number);
const anyDirty = computed(() => dirty.value || !!mentorText.value || !!mentorSource.value);
let mounted = true, key = crypto.randomUUID(), mentorKey = crypto.randomUUID();
const base = () => `projects/${props.project.id}/feedback-tasks/${props.task.id}/`;
watch(() => props.task, value => { current.value = value; });
watch([title, instruction, status, note, result, linked], () => { key = crypto.randomUUID(); }, { deep: true });
watch([mentorStatus, mentorText, mentorSource], () => { mentorKey = crypto.randomUUID(); });
watch(anyDirty, value => emit("dirtyChange", props.task.id, value));
function applySaved() { const saved = current.value.current; title.value = saved.title; instruction.value = saved.instruction; status.value = saved.status; note.value = saved.note; result.value = saved.result_kind; linked.value = saved.location; chosen.value = saved.location?.block_id || ""; version.value = saved.number; baseline.value = JSON.stringify(payload()); }
applySaved();
async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return; busy.value = true; error.value = ""; message.value = "";
  try { await action(); } catch (cause) { if (!mounted) return; error.value = cause instanceof Error ? cause.message : "请求失败，请重试。"; if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) { history.value = null; manuscript.value = null; feedback.value = null; emit("accessLost", cause); } }
  finally { if (mounted) busy.value = false; }
}
async function refresh() { const [task, draft] = await Promise.all([request<FeedbackTask>(base()), request<Manuscript>(`projects/${props.project.id}/manuscript/`)]); if (mounted) { current.value = task; manuscript.value = draft; if (props.project.role !== "author") applySaved(); } }
function relink() { const block = manuscript.value?.blocks.find(item => item.id === chosen.value); if (block && manuscript.value) linked.value = { manuscript_version: manuscript.value.version, block_id: block.id, block_version_id: block.version_id!, text: block.text, position: manuscript.value.blocks.indexOf(block) + 1, stale: false, current_version: manuscript.value.version, current_position: manuscript.value.blocks.indexOf(block) + 1 }; }
async function save() { const value = await request<FeedbackTask>(base(), "POST", { ...payload(), request_key: key, version: version.value }); if (mounted) { current.value = value; applySaved(); emit("saved", value); message.value = "处理记录已保存。"; } }
function loadSaved() { if (!dirty.value || window.confirm("用已保存处理记录替换当前草稿？")) applySaved(); }
async function loadFeedback() { const value = await request<Feedback>(`projects/${props.project.id}/feedback/${props.task.feedback_id}/`); if (mounted) feedback.value = value; }
async function loadHistory(number = 1) { const value = await request<Page<TaskProgress>>(`${base()}history/?page=${number}`); if (mounted) { history.value = value; historyPage.value = number; } }
async function report() { await request(base() + "mentor-reports/", "POST", { request_key: mentorKey, version: mentorVersion.value, status: mentorStatus.value, text: mentorText.value, source_label: mentorSource.value }); if (mounted) { mentorText.value = ""; mentorSource.value = ""; await refresh(); mentorVersion.value = current.value.current.number; message.value = "已记录作者转录的导师回复。"; } }
watch(() => current.value.current.number, value => { if (!mentorText.value && !mentorSource.value) mentorVersion.value = value; });
function relinkReport() { mentorVersion.value = current.value.current.number; mentorKey = crypto.randomUUID(); }
function beforeUnload(event: BeforeUnloadEvent) { if (anyDirty.value) { event.preventDefault(); event.returnValue = ""; } }
onMounted(() => { window.addEventListener("beforeunload", beforeUnload); void perform(refresh); });
onUnmounted(() => { mounted = false; window.removeEventListener("beforeunload", beforeUnload); emit("dirtyChange", props.task.id, false); });
</script>
<template>
  <article :aria-label="`修改待办：${current.current.title}`" :aria-busy="busy">
    <h3>{{ current.current.title }} · {{ progressLabels[current.current.status] }}</h3><p>处理 v{{ current.current.number }} · {{ current.candidate_id ? '作者确认的 AI 候选' : '作者登记' }}</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p><p v-if="message" role="status">{{ message }}</p><p v-if="busy" role="status">处理中…</p>
    <button :disabled="busy" @click="perform(refresh)">刷新待办与原稿</button><button :disabled="busy" @click="perform(loadFeedback)">回查原始意见</button>
    <blockquote v-if="feedback">{{ feedback.text }}<p>{{ feedback.source_label }} · 作者转录</p></blockquote>
    <details v-if="current.original_location"><summary>任务初始原稿 v{{ current.original_location.manuscript_version }} · 块 {{ current.original_location.position }}</summary><p class="source-text">{{ current.original_location.text }}</p></details>
    <p v-if="current.current.location?.stale">关联位置已失效，请核对最新原稿并重新关联。</p>
    <details v-if="current.current.location"><summary>已保存处理位置 · 原稿 v{{ current.current.location.manuscript_version }} · 块 {{ current.current.location.position }}</summary><p class="source-text">{{ current.current.location.text }}</p></details>
    <form class="editor" @submit.prevent="perform(save)"><fieldset :disabled="busy || project.role !== 'author'">
      <label>待办标题<input v-model="title" maxlength="200" required /></label><label>处理要求<textarea v-model="instruction" maxlength="2000" rows="2" required /></label>
      <label>作者进度<select v-model="status" aria-label="作者进度"><option v-for="(label, value) in progressLabels" :key="value" :value="value">{{ label }}</option></select></label>
      <label>处理说明<textarea v-model="note" maxlength="4000" rows="3" /></label>
      <label v-if="status === 'completed'">处理结果<select v-model="result" aria-label="处理结果"><option value="pending">选择处理结果</option><option value="modified">已修改原稿</option><option value="no_change">无需改稿（在说明中填写原因）</option></select></label>
      <p>当前关联：{{ linked ? `原稿 v${linked.manuscript_version} · 块 ${linked.position}` : '未关联正文' }}</p>
      <label>最新稿件 v{{ manuscript?.version ?? 0 }}<select v-model="chosen" aria-label="重新关联正文块"><option value="">选择正文块</option><option v-for="(block, index) in manuscript?.blocks" :key="block.id" :value="block.id">块 {{ index + 1 }}：{{ block.text.slice(0, 60) }}</option></select></label>
      <button type="button" :disabled="!chosen" @click="relink">关联所选最新正文</button><button type="button" @click="linked = null">取消正文关联</button>
      <p v-if="versionChanged">另有新处理记录。先对照已保存内容，再更新基准。</p><details v-if="versionChanged"><summary>最新处理记录</summary><p>{{ current.current.title }} · {{ progressLabels[current.current.status] }}</p><p>{{ current.current.instruction }}</p><p>{{ current.current.note }}</p></details>
      <button v-if="versionChanged" type="button" @click="version = current.current.number">保留说明并更新处理基准</button>
      <button v-if="project.role === 'author'" type="button" @click="loadSaved">载入已存处理记录</button><button v-if="project.role === 'author'" type="submit" :disabled="versionChanged">保存处理记录</button>
    </fieldset></form>
    <h4>导师回复（作者转录）</h4><p v-if="!current.current.mentor_reports.length">当前处理版本尚未登记导师回复。</p>
    <p v-for="item in current.current.mentor_reports" :key="item.id">{{ mentorLabels[item.status] }}：{{ item.text }} · {{ item.source_label }} · 记录人 {{ item.created_by }}</p>
    <form v-if="project.role === 'author' && current.current.status === 'completed'" class="editor" @submit.prevent="perform(report)"><fieldset :disabled="busy || dirty || !!current.current.location?.stale">
      <label>导师对处理 v{{ mentorVersion }} 的回复<select v-model="mentorStatus"><option value="confirmed">确认本次处理</option><option value="changes_requested">仍需修改</option></select></label>
      <button v-if="mentorVersion !== current.current.number" type="button" @click="relinkReport">核对回复并关联当前处理版本</button>
      <label>导师回复原文<textarea v-model="mentorText" maxlength="3000" rows="2" required /></label><label>回复来源<input v-model="mentorSource" maxlength="500" required /></label><button type="submit">保存转录回复</button>
    </fieldset></form>
    <button :disabled="busy" @click="perform(() => loadHistory())">查看处理历史</button>
    <div v-if="history"><article v-for="revision in history.results" :key="revision.number"><h4>处理 v{{ revision.number }} · {{ progressLabels[revision.status] }}</h4><p>{{ revision.title }}</p><p>{{ revision.note }}</p><p v-if="revision.location">原稿 v{{ revision.location.manuscript_version }} · 块 {{ revision.location.position }}</p><p v-for="item in revision.mentor_reports" :key="item.id">导师回复（作者转录）：{{ mentorLabels[item.status] }} · {{ item.text }} · {{ item.source_label }}</p></article><button :disabled="busy || !history.previous" @click="perform(() => loadHistory(historyPage - 1))">上一页处理历史</button><button :disabled="busy || !history.next" @click="perform(() => loadHistory(historyPage + 1))">下一页处理历史</button></div>
  </article>
</template>
