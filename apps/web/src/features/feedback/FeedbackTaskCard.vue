<script setup lang="ts">
import { useConfirm } from "@/ui/confirm";
const confirmDiscard = useConfirm();
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, request } from "@/api/client";
import { type Page } from "@/api/types";
import { type Project } from "@/features/projects/types";
import { mentorLabels, progressLabels, type Feedback, type FeedbackLocation, type FeedbackTask, type TaskProgress } from "@/features/feedback/types";
import type { Manuscript } from "@/features/manuscripts/types";
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
async function loadSaved() { if (!dirty.value || (await confirmDiscard("用已保存处理记录替换当前草稿？"))) applySaved(); }
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
    <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert><p v-if="message" role="status">{{ message }}</p><p v-if="busy" role="status">处理中…</p>
    <NButton @click="perform(refresh)" :disabled="(busy)">刷新待办与原稿</NButton><NButton @click="perform(loadFeedback)" :disabled="(busy)">回查原始意见</NButton>
    <blockquote v-if="feedback">{{ feedback.text }}<p>{{ feedback.source_label }} · 作者转录</p></blockquote>
    <UiDisclosure v-if="current.original_location"><template #header>任务初始原稿 v{{ current.original_location.manuscript_version }} · 块 {{ current.original_location.position }}</template><p class="source-text">{{ current.original_location.text }}</p></UiDisclosure>
    <p v-if="current.current.location?.stale">关联位置已失效，请核对最新原稿并重新关联。</p>
    <UiDisclosure v-if="current.current.location"><template #header>已保存处理位置 · 原稿 v{{ current.current.location.manuscript_version }} · 块 {{ current.current.location.position }}</template><p class="source-text">{{ current.current.location.text }}</p></UiDisclosure>
    <form class="editor" @submit.prevent="perform(save)"><fieldset :disabled="busy || project.role !== 'author'">
      <label>待办标题<UiInput v-model="title" maxlength="200" required :disabled="(busy || project.role !== 'author')" :aria-label="'待办标题'" /></label><label>处理要求<UiInput v-model="instruction" maxlength="2000" rows="2" required :disabled="(busy || project.role !== 'author')" type="textarea" :aria-label="'处理要求'" /></label>
      <label>作者进度<UiSelect v-model="status" aria-label="作者进度" :disabled="(busy || project.role !== 'author')" :options="[...Object.entries(progressLabels).map(([value, label]) => ({ value: value, label: String(label) }))]" /></label>
      <label>处理说明<UiInput v-model="note" maxlength="4000" rows="3" :disabled="(busy || project.role !== 'author')" type="textarea" :aria-label="'处理说明'" /></label>
      <label v-if="status === 'completed'">处理结果<UiSelect v-model="result" aria-label="处理结果" :disabled="(busy || project.role !== 'author')" :options="[({ value: 'pending', label: '选择处理结果' }), ({ value: 'modified', label: '已修改原稿' }), ({ value: 'no_change', label: '无需改稿（在说明中填写原因）' })]" /></label>
      <p>当前关联：{{ linked ? `原稿 v${linked.manuscript_version} · 块 ${linked.position}` : '未关联正文' }}</p>
      <label>最新稿件 v{{ manuscript?.version ?? 0 }}<UiSelect v-model="chosen" aria-label="重新关联正文块" :disabled="(busy || project.role !== 'author')" :options="[({ value: '', label: '选择正文块' }), ...(manuscript?.blocks ?? []).map((block, index) => ({ value: block.id, label: '块 ' + String(index + 1) + '：' + String(block.text.slice(0, 60)) }))]" /></label>
      <NButton attr-type="button" @click="relink" :disabled="(busy || project.role !== 'author') || (!chosen)">关联所选最新正文</NButton><NButton attr-type="button" @click="linked = null" :disabled="(busy || project.role !== 'author')">取消正文关联</NButton>
      <p v-if="versionChanged">另有新处理记录。先对照已保存内容，再更新基准。</p><UiDisclosure v-if="versionChanged"><template #header>最新处理记录</template><p>{{ current.current.title }} · {{ progressLabels[current.current.status] }}</p><p>{{ current.current.instruction }}</p><p>{{ current.current.note }}</p></UiDisclosure>
      <NButton v-if="versionChanged" attr-type="button" @click="version = current.current.number" :disabled="(busy || project.role !== 'author')">保留说明并更新处理基准</NButton>
      <NButton v-if="project.role === 'author'" attr-type="button" @click="loadSaved" :disabled="(busy || project.role !== 'author')">载入已存处理记录</NButton><NButton v-if="project.role === 'author'" attr-type="submit" :disabled="(busy || project.role !== 'author') || (versionChanged)" type="primary">保存处理记录</NButton>
    </fieldset></form>
    <h4>导师回复（作者转录）</h4><p v-if="!current.current.mentor_reports.length">当前处理版本尚未登记导师回复。</p>
    <p v-for="item in current.current.mentor_reports" :key="item.id">{{ mentorLabels[item.status] }}：{{ item.text }} · {{ item.source_label }} · 记录人 {{ item.created_by }}</p>
    <form v-if="project.role === 'author' && current.current.status === 'completed'" class="editor" @submit.prevent="perform(report)"><fieldset :disabled="busy || dirty || !!current.current.location?.stale">
      <label>导师对处理 v{{ mentorVersion }} 的回复<UiSelect v-model="mentorStatus" :disabled="(busy || dirty || !!current.current.location?.stale)" :options="[({ value: 'confirmed', label: '确认本次处理' }), ({ value: 'changes_requested', label: '仍需修改' })]" :aria-label="'导师对处理 v' + String(mentorVersion) + ' 的回复'" /></label>
      <NButton v-if="mentorVersion !== current.current.number" attr-type="button" @click="relinkReport" :disabled="(busy || dirty || !!current.current.location?.stale)">核对回复并关联当前处理版本</NButton>
      <label>导师回复原文<UiInput v-model="mentorText" maxlength="3000" rows="2" required :disabled="(busy || dirty || !!current.current.location?.stale)" type="textarea" :aria-label="'导师回复原文'" /></label><label>回复来源<UiInput v-model="mentorSource" maxlength="500" required :disabled="(busy || dirty || !!current.current.location?.stale)" :aria-label="'回复来源'" /></label><NButton attr-type="submit" :disabled="(busy || dirty || !!current.current.location?.stale)" type="primary">保存转录回复</NButton>
    </fieldset></form>
    <NButton @click="perform(() => loadHistory())" :disabled="(busy)">查看处理历史</NButton>
    <div v-if="history"><article v-for="revision in history.results" :key="revision.number"><h4>处理 v{{ revision.number }} · {{ progressLabels[revision.status] }}</h4><p>{{ revision.title }}</p><p>{{ revision.note }}</p><p v-if="revision.location">原稿 v{{ revision.location.manuscript_version }} · 块 {{ revision.location.position }}</p><p v-for="item in revision.mentor_reports" :key="item.id">导师回复（作者转录）：{{ mentorLabels[item.status] }} · {{ item.text }} · {{ item.source_label }}</p></article><NButton @click="perform(() => loadHistory(historyPage - 1))" :disabled="(busy || !history.previous)">上一页处理历史</NButton><NButton @click="perform(() => loadHistory(historyPage + 1))" :disabled="(busy || !history.next)">下一页处理历史</NButton></div>
  </article>
</template>
