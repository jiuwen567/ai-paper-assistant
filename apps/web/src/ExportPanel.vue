<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import type { Manuscript } from "./manuscript";
import { statusLabels, type DisclosureState } from "./disclosure";
import type { ExportContent as Content, ExportRecord, ExportTemplate } from "./export";
import ExportContent from "./ExportContent.vue";
const props = defineProps<{ project: Project; manuscriptDirty: boolean; disclosureDirty: boolean }>();
const emit = defineEmits<{ accessLost: [error: ApiError]; dirtyChange: [value: boolean] }>();
const templates = ref<ExportTemplate[]>([]), manuscript = ref<Manuscript | null>(null), disclosure = ref<DisclosureState | null>(null);
const records = ref<Page<ExportRecord> | null>(null), selected = ref<ExportRecord | null>(null), preview = ref<{ content: Content; preview_token: string } | null>(null);
const title = ref(props.project.name), author = ref(""), templateId = ref(""), captions = ref<Record<string, "" | "figure" | "table">>({});
const confirmed = ref(false), busy = ref(false), error = ref(""), message = ref(""), page = ref(1), baseline = ref("");
const editable = computed(() => props.project.role === "author");
const formValue = () => JSON.stringify([title.value, author.value, templateId.value, captions.value]);
const dirty = computed(() => editable.value && Boolean(baseline.value) && baseline.value !== formValue());
const ready = computed(() => !props.manuscriptDirty && !props.disclosureDirty && manuscript.value?.version && disclosure.value?.current?.verified && !disclosure.value.stale);
const chosenTemplate = computed(() => templates.value.find(t => t.id === templateId.value));
let mounted = true, key = crypto.randomUUID(), timer: ReturnType<typeof setTimeout> | undefined;
const base = () => `projects/${props.project.id}/`;
watch(dirty, value => emit("dirtyChange", value));
watch([title, author, templateId, captions], () => { preview.value = null; confirmed.value = false; key = crypto.randomUUID(); }, { deep: true, flush: "sync" });
watch(() => [props.manuscriptDirty, props.disclosureDirty], () => { preview.value = null; confirmed.value = false; });
async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return;
  busy.value = true; error.value = ""; message.value = "";
  try { await action(); }
  catch (cause) {
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      records.value = null; selected.value = null; preview.value = null; manuscript.value = null; disclosure.value = null;
      emit("accessLost", cause);
    }
  } finally { if (mounted) busy.value = false; }
}
async function loadRecords(number = page.value) {
  const value = await request<Page<ExportRecord>>(`${base()}exports/?page=${number}`);
  if (mounted) { records.value = value; page.value = number; }
}
async function refresh() {
  const [t, m, d] = await Promise.all([
    request<ExportTemplate[]>(base() + "export-templates/"), request<Manuscript>(base() + "manuscript/"), request<DisclosureState>(base() + "disclosure/"),
  ]);
  if (!mounted) return;
  templates.value = t; manuscript.value = m; disclosure.value = d;
  if (!templateId.value) templateId.value = (t.find(item => item.code === props.project.template) || t[0])?.id || "";
  preview.value = null; confirmed.value = false;
  if (!baseline.value) baseline.value = formValue();
  await loadRecords();
}
function selection() {
  return { manuscript_version: manuscript.value!.version, disclosure_version: disclosure.value!.current!.number, template_version_id: templateId.value,
    title: title.value, author: author.value, captions: Object.entries(captions.value).filter(([, kind]) => kind).map(([block_id, kind]) => ({ block_id, kind })) };
}
async function makePreview() {
  const value = await request<NonNullable<typeof preview.value>>(base() + "exports/preview/", "POST", selection());
  if (mounted) { preview.value = value; confirmed.value = false; }
}
async function create() {
  const value = await request<ExportRecord>(base() + "exports/", "POST", { ...selection(), preview_token: preview.value!.preview_token, confirmed: confirmed.value, request_key: key });
  if (!mounted) return;
  selected.value = value; preview.value = null; confirmed.value = false; baseline.value = formValue();
  message.value = "导出快照已保存，可继续编辑原稿。"; await loadRecords(1); schedule();
}
async function detail(id: string) {
  const value = await request<ExportRecord>(`${base()}exports/${id}/`);
  if (mounted) { selected.value = value; schedule(); }
}
function schedule() {
  clearTimeout(timer);
  if (mounted && selected.value && ["queued", "running"].includes(selected.value.job.status)) timer = setTimeout(() => {
    if (busy.value) { schedule(); return; }
    void perform(async () => { await detail(selected.value!.id); await loadRecords(); });
  }, 2000);
}
async function control(action: "retry" | "cancel") {
  const job = selected.value!.job;
  await request(`${base()}jobs/${job.id}/${action}/`, "POST", { generation: job.generation });
  if (mounted) { await detail(selected.value!.id); await loadRecords(); }
}
async function download() {
  const id = selected.value!.id;
  const response = await fetch(`/api/v1/${base()}exports/${id}/download/`, { credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(30000) });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(response.status, typeof data?.detail === "string" ? data.detail : "下载失败，请刷新导出状态。");
  }
  const blob = await response.blob();
  if (!mounted) return;
  const url = URL.createObjectURL(blob), link = document.createElement("a");
  link.href = url; link.download = `稿件-v${selected.value!.manuscript_version}-${id.slice(0, 8)}.docx`;
  document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  await detail(id);
}
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value) { event.preventDefault(); event.returnValue = ""; } }
onMounted(() => { window.addEventListener("beforeunload", beforeUnload); void perform(refresh); });
onUnmounted(() => { mounted = false; clearTimeout(timer); window.removeEventListener("beforeunload", beforeUnload); emit("dirtyChange", false); });
</script>
<template>
  <section aria-label="Word 导出" :aria-busy="busy">
    <h2>Word 导出</h2>
    <p v-if="error" role="alert" class="error">{{ error }}</p><p v-if="message" role="status">{{ message }}</p><p v-if="busy" role="status">处理中…</p>
    <button :disabled="busy" @click="perform(refresh)">刷新导出资料</button>
    <form v-if="editable && manuscript && disclosure" @submit.prevent="perform(makePreview)">
      <p v-if="!ready">请先保存原稿，并在“AI 使用与披露”核实当前清单，再刷新导出资料。</p>
      <fieldset :disabled="busy">
        <label>交付标题<input v-model="title" maxlength="200" required /></label>
        <label>署名<input v-model="author" maxlength="200" /></label>
        <label>导出模板<select v-model="templateId" required><option v-for="item in templates" :key="item.id" :value="item.id">{{ item.name }} v{{ item.number }}</option></select></label>
        <p v-if="chosenTemplate">{{ chosenTemplate.source_label }}</p>
        <details v-if="manuscript.blocks.length"><summary>图表题注</summary>
          <p>选择原稿中的单行题注标题，导出时分别顺序编号。正文导入仅保留文本，不恢复原文件的图表。</p>
          <label v-for="block in manuscript.blocks.filter(b => !b.heading_level && b.text.trim() && !b.text.includes('\n'))" :key="block.id" class="caption-option">
            <span>{{ block.text }}</span><select v-model="captions[block.id]" aria-label="题注类型"><option value="">正文</option><option value="figure">图题</option><option value="table">表题</option></select>
          </label>
        </details>
        <button :disabled="!ready || !templateId">预览导出</button>
      </fieldset>
    </form>
    <div v-if="preview">
      <ExportContent :content="preview.content" />
      <label class="check-label"><input v-model="confirmed" type="checkbox" :disabled="busy" />已核对正文、引用、模板和 AI 使用说明</label>
      <button :disabled="busy || !confirmed || !ready" @click="perform(create)">确认并生成 Word</button>
    </div>
    <h3>导出记录</h3>
    <p v-if="records && !records.count">暂无导出。</p>
    <ul v-if="records?.count"><li v-for="item in records.results" :key="item.id"><button :disabled="busy" @click="perform(() => detail(item.id))">{{ item.title }} · 稿件 v{{ item.manuscript_version }} · {{ statusLabels[item.job.status] }} · {{ new Date(item.created_at).toLocaleString() }}</button></li></ul>
    <button v-if="records?.previous" :disabled="busy" @click="perform(() => loadRecords(page - 1))">上一页导出</button><button v-if="records?.next" :disabled="busy" @click="perform(() => loadRecords(page + 1))">下一页导出</button>
    <article v-if="selected" aria-label="导出记录详情">
      <p role="status">{{ statusLabels[selected.job.status] }} · {{ selected.job.progress }}%</p>
      <p v-if="selected.job.error_message" role="alert">{{ selected.job.error_message }}（{{ selected.job.error_code }}）</p>
      <p v-if="selected.sources_changed">来源状态已变化，旧导出不可下载。</p>
      <ExportContent v-if="selected.content" :content="selected.content" />
      <button :disabled="busy" @click="perform(() => detail(selected!.id))">刷新此导出</button>
      <button v-if="editable && ['queued', 'running'].includes(selected.job.status)" :disabled="busy" @click="perform(() => control('cancel'))">取消导出</button>
      <button v-if="editable && selected.job.status === 'failed' && selected.job.retryable" :disabled="busy" @click="perform(() => control('retry'))">重试此快照</button>
      <button v-if="selected.downloadable" :disabled="busy" @click="perform(download)">下载 Word</button>
      <p>在 Word 中打开后，更新整个目录并检查分页、题注和引用编号。</p>
      <details><summary>版本与下载记录</summary><p class="digest">快照 {{ selected.digest }}<br />导出器 {{ selected.renderer_version }}<br />模板摘要 {{ selected.template.digest }}<br />文件摘要 {{ selected.file?.sha256 || '尚未生成' }}</p>
        <p>以下记录表示服务端已校验并发出文件，不代表客户端已保存。最多显示最近 100 次。</p>
        <ul><li v-for="item in selected.downloads" :key="item.id">用户 {{ item.created_by_id }} · 文件 {{ item.file_id }} · {{ new Date(item.created_at).toLocaleString() }}</li></ul>
      </details>
    </article>
  </section>
</template>
<style scoped>
button { white-space: normal; overflow-wrap: anywhere; max-width: 100%; }
p { overflow-wrap: anywhere; }
fieldset { border: 0; padding: 0; } .caption-option { display: flex; gap: 1rem; align-items: start; } .caption-option span { flex: 1; overflow-wrap: anywhere; } .caption-option select { width: auto; } .digest { overflow-wrap: anywhere; }
</style>
