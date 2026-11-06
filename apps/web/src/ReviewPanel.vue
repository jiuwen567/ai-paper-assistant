<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import type { Manuscript } from "./manuscript";
import { scopeLabels } from "./sources";
import { decisionLabels, reviewCategories, type ReviewRecord, type ReviewFinding } from "./review";
import ReviewFindingCard from "./ReviewFindingCard.vue";
const props = defineProps<{ project: Project }>();
const emit = defineEmits<{ accessLost: [error: ApiError] }>();
type Source = { id: string; title: string; number: number; source_scope: string };
type Task = { id: string; status: string; generation: number; retryable: boolean; error_message: string; output: { review_id?: string } | null };
const manuscript = ref<Manuscript | null>(null), sources = ref<Page<Source> | null>(null), records = ref<Page<ReviewRecord> | null>(null);
const sourcePage = ref(1), recordPage = ref(1), selectedBlocks = ref<string[]>([]), selectedSources = ref<Source[]>([]), question = ref("");
const selected = ref<ReviewRecord | null>(null), findings = ref<Page<ReviewFinding> | null>(null), previousId = ref<string | null>(null);
const filterStatus = ref(""), filterCategory = ref(""), task = ref<Task | null>(null);
const busy = ref(false), error = ref(""), message = ref("");
const canCreate = computed(() => props.project.role === "author" && props.project.policy.allowed_actions.includes("review"));
const taskLabels: Record<string, string> = { queued: "等待执行", running: "执行中", succeeded: "成功", failed: "失败", cancelled: "已取消" };
const base = () => `projects/${props.project.id}/`;
let mounted = true, key = crypto.randomUUID(), timer: ReturnType<typeof setTimeout> | undefined;
watch([selectedBlocks, selectedSources, question, previousId], () => { key = crypto.randomUUID(); }, { deep: true });
async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return;
  busy.value = true; error.value = ""; message.value = "";
  try { await action(); }
  catch (cause) {
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      manuscript.value = null; sources.value = null; records.value = null; selected.value = null; findings.value = null;
      selectedBlocks.value = []; selectedSources.value = []; task.value = null;
      emit("accessLost", cause);
    }
  } finally { busy.value = false; }
}
async function loadManuscript() {
  const data = await request<Manuscript>(`${base()}manuscript/`);
  if (mounted) { manuscript.value = data; selectedBlocks.value = selectedBlocks.value.filter(id => data.blocks.some(block => block.id === id)); }
}
async function loadSources(page = sourcePage.value) {
  const data = await request<Page<Source>>(`${base()}reading/sources/?page=${page}`);
  if (mounted) { sources.value = data; sourcePage.value = page; }
}
async function loadRecords(page = recordPage.value) {
  const data = await request<Page<ReviewRecord>>(`${base()}reviews/?page=${page}`);
  if (mounted) { records.value = data; recordPage.value = page; }
}
async function loadFindings() {
  if (!selected.value) return;
  const query = new URLSearchParams({ status: filterStatus.value, category: filterCategory.value });
  const data = await request<Page<ReviewFinding>>(`${base()}reviews/${selected.value.id}/findings/?${query}`);
  if (mounted) findings.value = data;
}
async function open(id: string) {
  const data = await request<ReviewRecord>(`${base()}reviews/${id}/`);
  if (!mounted) return;
  selected.value = data; filterStatus.value = ""; filterCategory.value = "";
  if (records.value) records.value.results = records.value.results.map(item => item.id === id ? data : item);
  await loadFindings();
}
async function refresh() {
  await Promise.all([loadManuscript(), loadSources(), loadRecords()]);
  if (selected.value) await open(selected.value.id);
}
function toggleSource(source: Source) { selectedSources.value = selectedSources.value.some(item => item.id === source.id) ? selectedSources.value.filter(item => item.id !== source.id) : [...selectedSources.value, source]; }
function updateFinding(finding: ReviewFinding) {
  if (findings.value) {
    const count = findings.value.results.length;
    findings.value.results = findings.value.results.map(item => item.id === finding.id ? finding : item).filter(item => !filterStatus.value || item.status === filterStatus.value);
    findings.value.count -= count - findings.value.results.length;
  }
}
async function create() {
  const data = await request<Task>(`${base()}reviews/tasks/`, "POST", {
    idempotency_key: key, policy_version: props.project.policy.version, manuscript_version: manuscript.value!.version,
    block_ids: selectedBlocks.value, version_ids: selectedSources.value.map(item => item.id), previous_review_id: previousId.value,
    ...(question.value.trim() ? { question: question.value } : {}),
  });
  key = crypto.randomUUID(); if (mounted) task.value = data;
}
async function prepareRecheck() {
  await loadManuscript();
  if (!mounted || !selected.value || !manuscript.value) return;
  previousId.value = selected.value.id;
  selectedBlocks.value = selected.value.block_ids.filter(id => manuscript.value!.blocks.some(block => block.id === id));
  selectedSources.value = selected.value.source_checks.map(source => ({ id: source.version_id, title: source.title, number: source.source_number, source_scope: source.source_scope }));
  question.value = selected.value.question;
  message.value = selectedBlocks.value.length ? "已选择原审阅范围在当前稿件中的正文，请核对资料后开始复查。" : "原审阅块已删除，请选择当前稿件中需要复查的正文。";
}
async function control(action: "cancel" | "retry") {
  const data = await request<Task>(`${base()}jobs/${task.value!.id}/${action}/`, "POST", { generation: task.value!.generation });
  if (mounted) task.value = data;
}
async function poll() {
  if (!mounted) return;
  if (task.value && ["queued", "running"].includes(task.value.status)) await perform(async () => {
    const data = await request<Task>(`${base()}jobs/${task.value!.id}/`);
    if (!mounted) return;
    task.value = data;
    if (data.status === "succeeded" && data.output?.review_id) { await loadRecords(1); await open(data.output.review_id); }
  });
  if (mounted) timer = setTimeout(poll, 2000);
}
onMounted(async () => { await perform(refresh); void poll(); });
onUnmounted(() => { mounted = false; clearTimeout(timer); });
</script>
<template>
  <section aria-label="原稿诊断" :aria-busy="busy">
    <h2>原稿诊断</h2>
    <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert><p v-if="message" role="status">{{ message }}</p><p v-if="busy" role="status">处理中…</p>
    <NButton @click="perform(refresh)" :disabled="(busy)">刷新审阅区</NButton>
    <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(create)"><fieldset :disabled="busy">
      <UiDisclosure><template #header>选择原稿 v{{ manuscript?.version ?? 0 }}（{{ selectedBlocks.length }}/20）</template>
        <p v-if="!manuscript?.blocks.length">暂无已保存正文，请先保存作者原稿。</p>
        <UiCheckbox v-model="selectedBlocks" :value="block.id" :disabled="(busy) || (selectedBlocks.length >= 20 && !selectedBlocks.includes(block.id))" :aria-label="'块 ' + String(index + 1) + '：' + String(block.text.slice(0, 80) || '空正文')" v-for="(block, index) in manuscript?.blocks" :key="block.id" class="check-label">块 {{ index + 1 }}：{{ block.text.slice(0, 80) || '空正文' }}</UiCheckbox>
      </UiDisclosure>
      <UiDisclosure><template #header>选择依据（{{ selectedSources.length }}/5）</template>
        <p v-if="sources?.count === 0">尚无已解析资料；只能检查所选原稿与研究说明。</p>
        <UiCheckbox :checked="selectedSources.some(item => item.id === source.id)" @change="toggleSource(source)" :disabled="(busy) || (selectedSources.length >= 5 && !selectedSources.some(item => item.id === source.id))" :aria-label="String(source.title) + ' · v' + String(source.number) + ' · ' + String(scopeLabels[source.source_scope])" v-for="source in sources?.results" :key="source.id" class="check-label">{{ source.title }} · v{{ source.number }} · {{ scopeLabels[source.source_scope] }}</UiCheckbox>
        <div v-if="sources && (sources.previous || sources.next)" class="actions"><NButton attr-type="button" @click="perform(() => loadSources(sourcePage - 1))" :disabled="(busy) || (!sources.previous)">上一页审阅依据</NButton><NButton attr-type="button" @click="perform(() => loadSources(sourcePage + 1))" :disabled="(busy) || (!sources.next)">下一页审阅依据</NButton></div>
      </UiDisclosure>
      <div class="actions"><NButton v-for="source in selectedSources" :key="source.id" attr-type="button" @click="toggleSource(source)" :disabled="(busy)">移除依据 {{ source.title }} v{{ source.number }}</NButton></div>
      <label>核对重点<UiInput v-model="question" maxlength="500" rows="2" :disabled="(busy)" type="textarea" :aria-label="'核对重点'" /></label>
      <div class="actions"><NButton attr-type="submit" :disabled="(busy) || (!canCreate || !selectedBlocks.length)" type="primary">{{ previousId ? '开始复查' : '开始诊断' }}</NButton><NButton v-if="previousId" attr-type="button" @click="previousId = null" :disabled="(busy)">取消复查关联</NButton></div>
      <p v-if="!canCreate">当前规则未允许原稿诊断。</p>
    </fieldset></form>
    <div v-if="task" role="status">{{ taskLabels[task.status] }}<p v-if="task.error_message">{{ task.error_message }}</p><NButton v-if="['queued','running'].includes(task.status)" @click="perform(() => control('cancel'))" :disabled="(busy)">取消诊断任务</NButton><NButton v-if="task.status === 'failed' && task.retryable" @click="perform(() => control('retry'))" :disabled="(busy)">重试诊断任务</NButton></div>
    <p v-if="records?.count === 0">暂无诊断记录。</p>
    <ul class="project-list"><li v-for="record in records?.results" :key="record.id"><NButton :aria-pressed="selected?.id === record.id" @click="perform(() => open(record.id))" :disabled="(busy)">原稿 v{{ record.manuscript_version }} · {{ record.findings_count }} 项建议{{ record.input_changed ? ' · 输入已变化' : '' }}{{ record.previous_review_id ? ' · 复查' : '' }}</NButton></li></ul>
    <div v-if="records && (records.previous || records.next)" class="actions"><NButton @click="perform(() => loadRecords(recordPage - 1))" :disabled="(busy || !records.previous)">上一页诊断</NButton><NButton @click="perform(() => loadRecords(recordPage + 1))" :disabled="(busy || !records.next)">下一页诊断</NButton></div>
    <article v-if="selected" aria-label="诊断结果">
      <h3>原稿 v{{ selected.manuscript_version }} · 模型建议</h3>
      <p>{{ selected.summary }}</p><p>仅覆盖所选原稿和已读取依据，需作者核对，不作为学术合规认证。</p>
      <p v-if="selected.input_changed" role="status">原稿或依据已变化，请复查后再确认。</p>
      <p v-if="selected.research_limited">作者研究说明仅提供各字段前 1000 字符，未检查剩余部分。</p>
      <div class="actions"><NButton @click="perform(() => open(selected!.id))" :disabled="(busy)">重新加载诊断</NButton><NButton v-if="project.role === 'author'" @click="perform(prepareRecheck)" :disabled="(busy || !canCreate)">按当前原稿复查</NButton></div>
      <p v-if="selected.previous_review_id"><NButton @click="perform(() => open(selected!.previous_review_id!))" :disabled="(busy)">查看前次诊断</NButton></p>
      <p v-for="recheck in selected.recheck_tasks" :key="recheck.id">复查任务：{{ taskLabels[recheck.status] }} <NButton v-if="recheck.output?.review_id" @click="perform(() => open(recheck.output!.review_id!))" :disabled="(busy)">查看复查结果</NButton></p>
      <UiDisclosure><template #header>资料与全文范围</template><p v-if="!selected.source_checks.length">本次未提供文献或研究资料，不能核验外部引用。</p><div v-for="source in selected.source_checks" :key="source.version_id"><h4>{{ source.title }} · v{{ source.source_number }}</h4><p>项目内有原件 · {{ source.bibliography_registered ? '已登记题录' : '未登记题录' }} · 出版真实性未核验</p><p>{{ scopeLabels[source.source_scope] }}{{ source.source_scope === 'abstract' ? '；未提供全文' : '' }}</p></div></UiDisclosure>
      <form class="actions" @submit.prevent="perform(loadFindings)"><label>处理状态<UiSelect v-model="filterStatus" aria-label="处理状态" :disabled="(busy)" :options="[({ value: '', label: '全部状态' }), ...Object.entries(decisionLabels).map(([value, label]) => ({ value: value, label: String(label) }))]" /></label><label>问题类型<UiSelect v-model="filterCategory" aria-label="问题类型" :disabled="(busy)" :options="[({ value: '', label: '全部类型' }), ...Object.entries(reviewCategories).map(([value, label]) => ({ value: value, label: String(label) }))]" /></label><NButton attr-type="submit" :disabled="(busy)" type="primary">筛选问题</NButton></form>
      <p v-if="findings?.count === 0">当前范围没有问题卡；不代表全文无误。</p>
      <ReviewFindingCard v-for="finding in findings?.results" :key="finding.id" :project="project" :finding="finding" :input-changed="selected.input_changed" @saved="updateFinding" @access-lost="cause => perform(async () => { throw cause; })" />
    </article>
  </section>
</template>
