<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import type { Block } from "./manuscript";
type Material = { id: string; title: string };
type Preview = { token: string; counts: Record<string, number>; objects: number; removed_blocks: Block[]; manuscript_version: number };
type CleanupRecord = { id: string; project_id: string; material_id: string | null; scope: string; status: string; generation: number; error_code: string; created_at: string; counts: { [key: string]: number }; progress: { [key: string]: number }; items: { id: number; kind: string; status: string; error_code: string }[]; attempts: { generation: number; status: string; error_code: string; errors: { id: number; kind: string; error_code: string }[] }[] };
const props = defineProps<{ project: Project | null; hasDraft: boolean; disabled: boolean }>();
const emit = defineEmits<{ accessLost: [error: ApiError]; deleted: [scope: string, projectId: string]; deleting: [value: boolean] }>();
const materials = ref<Page<Material> | null>(null), records = ref<Page<CleanupRecord> | null>(null), selected = ref<CleanupRecord | null>(null);
const scope = ref("material"), materialId = ref(""), preview = ref<Preview | null>(null), confirmed = ref(false);
const busy = ref(false), error = ref(""), message = ref(""), materialPage = ref(1), page = ref(1), expanded = ref(false);
const names: { [key: string]: string } = { material: "材料", materialversion: "原文件版本", parserun: "解析记录", sourcechunk: "解析片段", chunkembedding: "向量片段", bibliographyrevision: "题录版本", evidencecard: "证据卡", evidencenote: "证据笔记", job: "后台任务", modelcall: "模型调用记录", readingrecord: "阅读结果", readingrevision: "阅读修订", manuscriptrevision: "稿件历史版本", blockversion: "正文块版本", reviewrecord: "诊断结果", reviewfinding: "诊断问题", expressionsuggestion: "表达建议", expressiondecision: "表达决定", manuscriptcitation: "正文引用", feedback: "反馈原文", feedbacktask: "修改待办", feedbacktaskrevision: "待办历史", mentorreport: "导师回复", evidencelink: "依据关系", evidencelinkrevision: "依据关系决定", materialchange: "材料变更", impactrun: "影响清单", impactitem: "影响项", exportsnapshot: "导出快照", exportfile: "导出文件", exportdownload: "下载记录", disclosurerevision: "披露历史" };
const statuses: { [key: string]: string } = { queued: "等待清理", running: "清理中", failed: "清理未完成", succeeded: "在线清理完成", pending: "待处理", removed: "已移除", shared: "其他引用仍使用，保留对象" };
const kinds: { [key: string]: string } = { database: "业务数据及向量", object: "文件对象", graph: "图关系" };
const canPreview = computed(() => props.project?.role === "author" && !props.hasDraft && !props.disabled && (scope.value === "project" ? props.project.is_owner : Boolean(materialId.value)));
let mounted = true, key = crypto.randomUUID(), timer: ReturnType<typeof setTimeout> | undefined;
watch([scope, materialId, () => props.project?.id, () => props.hasDraft], () => { preview.value = null; confirmed.value = false; key = crypto.randomUUID(); });
watch(() => props.project?.id, () => { materials.value = null; materialId.value = ""; scope.value = "material"; materialPage.value = 1; });
async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return;
  busy.value = true; error.value = ""; message.value = "";
  try { await action(); }
  catch (cause) {
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) { preview.value = null; materials.value = null; emit("accessLost", cause); }
  } finally { if (mounted) busy.value = false; }
}
async function loadMaterials(number = materialPage.value) {
  if (!props.project) return;
  const id = props.project.id;
  const value = await request<Page<Material>>(`projects/${id}/materials/?page=${number}`);
  if (mounted && props.project?.id === id) { materials.value = value; materialPage.value = number; }
}
async function loadRecords(number = page.value) {
  const value = await request<Page<CleanupRecord>>(`cleanups/?page=${number}`);
  if (mounted) { records.value = value; page.value = number; }
}
function selection() { return { scope: scope.value, material_id: scope.value === "material" ? materialId.value : null }; }
async function makePreview() {
  const id = props.project!.id, choice = JSON.stringify(selection());
  const value = await request<Preview>(`projects/${id}/cleanup-preview/`, "POST", selection());
  if (mounted && props.project?.id === id && choice === JSON.stringify(selection()) && !props.hasDraft) { preview.value = value; confirmed.value = false; }
}
async function remove() {
  const id = props.project!.id;
  emit("deleting", true);
  let value: CleanupRecord;
  try { value = await request<CleanupRecord>(`projects/${id}/cleanup/`, "POST", { ...selection(), preview_token: preview.value!.token, confirmed: confirmed.value, request_key: key }); }
  finally { emit("deleting", false); }
  if (!mounted) return;
  selected.value = value; preview.value = null; confirmed.value = false; materials.value = null; materialId.value = "";
  message.value = "访问已停止，业务数据已移除；文件及图关系的清理状态见下方记录。";
  emit("deleted", value.scope, id); await loadRecords(1); schedule();
}
async function detail(id: string) {
  const value = await request<CleanupRecord>(`cleanups/${id}/`);
  if (mounted) { selected.value = value; schedule(); }
}
function schedule() {
  clearTimeout(timer);
  if (mounted && selected.value && ["queued", "running"].includes(selected.value.status)) timer = setTimeout(() => {
    if (busy.value) { schedule(); return; }
    void perform(async () => { await detail(selected.value!.id); await loadRecords(); });
  }, 2000);
}
async function retry() {
  const value = await request<CleanupRecord>(`cleanups/${selected.value!.id}/`, "POST", { generation: selected.value!.generation });
  if (mounted) { selected.value = value; schedule(); }
}
function countRows(value: Preview) { return Object.entries(value.counts).filter(([name]) => names[name]); }
onMounted(() => { void perform(() => loadRecords()); });
onUnmounted(() => { mounted = false; clearTimeout(timer); });
</script>
<template>
  <section aria-label="删除与清理" :aria-busy="busy">
    <UiDisclosure :open="expanded" @toggle="expanded = ($event.target as HTMLDetailsElement).open">
      <template #header>删除与清理</template>
      <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert><p v-if="message" role="status">{{ message }}</p><p v-if="busy" role="status">处理中…</p>
      <form v-if="project?.role === 'author'" class="editor" @submit.prevent="perform(makePreview)">
        <p>撤回只停止后续使用，保留历史。这里会永久移除所选范围的在线数据；备份、已下载副本和已发送给模型服务的内容无法由本次清理撤回。</p>
        <p v-if="hasDraft">请先保存或放弃当前未保存的修改，再预览删除范围。</p>
        <fieldset :disabled="busy || hasDraft || disabled">
          <label>删除范围<UiSelect v-model="scope" :disabled="(busy || hasDraft || disabled)" :options="[({ value: 'material', label: '一项材料及派生数据' }), ({ value: 'project', label: '整个项目' })]" :aria-label="'删除范围'" /></label>
          <template v-if="scope === 'material'">
            <NButton attr-type="button" @click="perform(() => loadMaterials())" :disabled="(busy || hasDraft || disabled) || (busy)">加载可选材料</NButton>
            <label>待删除材料<UiSelect v-model="materialId" :disabled="(busy || hasDraft || disabled)" :options="[({ value: '', label: '请选择' }), ...(materials?.results ?? []).map((item) => ({ value: item.id, label: String(item.title || '未命名材料') }))]" :aria-label="'待删除材料'" /></label>
            <p v-if="materials && !materials.count">没有可删除的材料。</p>
            <NButton v-if="materials?.previous" attr-type="button" @click="perform(() => loadMaterials(materialPage - 1))" :disabled="(busy || hasDraft || disabled)">上一页材料</NButton><NButton v-if="materials?.next" attr-type="button" @click="perform(() => loadMaterials(materialPage + 1))" :disabled="(busy || hasDraft || disabled)">下一页材料</NButton>
          </template>
          <NButton :disabled="(busy || hasDraft || disabled) || (!canPreview)" attr-type="submit">预览删除影响</NButton>
        </fieldset>
      </form>
      <div v-if="preview" aria-label="删除影响预览">
        <p>文件对象 {{ preview.objects }} 个。关联的多来源结果会整体移除；其他原材料保留。未登记出处的手工转抄不能自动识别。</p>
        <ul><li v-for="[name, count] in countRows(preview)" :key="name">{{ names[name] }}：{{ count }}</li></ul>
        <p v-if="scope === 'project'">整个项目及全部稿件历史将删除。</p>
        <template v-if="scope === 'material' && preview.removed_blocks.length"><p>以下派生正文将从当前稿及相关历史中移除，包含在这些位置上的后续修订。其余当前正文保留为新稿。</p><blockquote v-for="block in preview.removed_blocks" :key="block.id">{{ block.text }}</blockquote></template>
        <UiCheckbox v-model="confirmed" :disabled="(busy || hasDraft)" :aria-label="'已核对影响范围，确认永久删除，无法撤销'" class="check-label">已核对影响范围，确认永久删除，无法撤销</UiCheckbox>
        <NButton @click="perform(remove)" :disabled="(busy || hasDraft || disabled || !confirmed)">确认永久删除</NButton>
      </div>
      <h3>我发起的清理</h3><NButton @click="perform(() => loadRecords())" :disabled="(busy)">刷新清理记录</NButton>
      <p v-if="records && !records.count">暂无清理记录。</p>
      <ul><li v-for="item in records?.results" :key="item.id"><NButton @click="perform(() => detail(item.id))" :disabled="(busy)">{{ item.scope === 'project' ? '项目删除' : '材料删除' }} · {{ new Date(item.created_at).toLocaleString() }} · {{ statuses[item.status] }}</NButton></li></ul>
      <NButton v-if="records?.previous" @click="perform(() => loadRecords(page - 1))" :disabled="(busy)">上一页清理</NButton><NButton v-if="records?.next" @click="perform(() => loadRecords(page + 1))" :disabled="(busy)">下一页清理</NButton>
      <article v-if="selected" aria-label="清理记录详情">
        <p role="status">{{ statuses[selected.status] }} · 第 {{ selected.generation }} 次执行</p>
        <NAlert type="error" :show-icon="false" v-if="selected.error_code" role="alert">{{ selected.error_code }}；已移除的步骤会保留，重试继续处理剩余项。</NAlert>
        <p>已移除 {{ selected.progress.removed || 0 }} 项 · 共享保留 {{ selected.progress.shared || 0 }} 项 · 未处理 {{ (selected.progress.pending || 0) + (selected.progress.failed || 0) }} 项。下方最多显示前 100 项。</p>
        <ul><li v-for="item in selected.items" :key="item.id">{{ kinds[item.kind] }} {{ item.id }} · {{ statuses[item.status] }}<span v-if="item.error_code"> · {{ item.error_code }}</span></li></ul>
        <NButton @click="perform(() => detail(selected!.id))" :disabled="(busy)">刷新此清理</NButton><NButton v-if="selected.status === 'failed'" @click="perform(retry)" :disabled="(busy)">继续清理失败项</NButton>
        <UiDisclosure><template #header>执行记录</template><ul><li v-for="item in selected.attempts" :key="item.generation">第 {{ item.generation }} 次 · {{ statuses[item.status] }} {{ item.error_code }}<p v-for="failure in item.errors" :key="failure.id">{{ kinds[failure.kind] }} {{ failure.id }} · {{ failure.error_code }}</p></li></ul></UiDisclosure>
      </article>
    </UiDisclosure>
  </section>
</template>
<style scoped>
button { white-space: normal; max-width: 100%; overflow-wrap: anywhere; } p, blockquote { overflow-wrap: anywhere; } blockquote { white-space: pre-wrap; } .check-label { display: flex; gap: .5rem; align-items: center; }
</style>
