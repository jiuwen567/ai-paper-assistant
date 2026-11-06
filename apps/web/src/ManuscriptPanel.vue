<script setup lang="ts">
import { useConfirm } from "./ui/confirm";
const confirmDiscard = useConfirm();
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ArrowUp, ArrowDown, Plus, Trash2, List, Save } from "@lucide/vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import { editableBlocks, researchLabels, type Block, type Research, type Manuscript, type Revision, type ImportSource, type ImportPreview, type ManuscriptDiff } from "./manuscript";

const props = defineProps<{ project: Project }>();
const emit = defineEmits<{ accessLost: [error: ApiError]; dirtyChange: [dirty: boolean] }>();
const version = ref(0), currentVersion = ref(0), research = ref<Research>({ question: "", method: "", result: "" });
const blocks = ref<Block[]>([]), saved = ref(""), initialized = ref(false);
const busy = ref(false), error = ref(""), message = ref("");
const history = ref<Page<Revision> | null>(null), historyPage = ref(1), past = ref<Manuscript | null>(null);
const before = ref(0), after = ref(0), diff = ref<ManuscriptDiff | null>(null);
const imports = ref<Page<ImportSource> | null>(null), importPage = ref(1), preview = ref<ImportPreview | null>(null);
const importMode = ref<"append" | "replace">("append");
const draft = computed(() => JSON.stringify({ research: research.value, blocks: editableBlocks(blocks.value) }));
const dirty = computed(() => initialized.value && draft.value !== saved.value);
watch(dirty, value => emit("dirtyChange", value));
const canEdit = computed(() => props.project.role === "author");
const headings = computed(() => blocks.value.filter(block => block.heading_level));
const kinds: Record<string, string> = { added: "新增", removed: "删除", modified: "修改", moved: "移动" };
const origins = { edit: "作者编辑", import: "DOCX 导入", restore: "恢复旧稿", expression: "采纳表达建议", cleanup: "资料删除后的保留稿" };
const base = () => `projects/${props.project.id}/manuscript/`;
let mounted = true, key = crypto.randomUUID();
watch([draft, importMode, preview, past], () => { key = crypto.randomUUID(); });

async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return;
  busy.value = true; error.value = ""; message.value = "";
  try { await action(); }
  catch (cause) {
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      blocks.value = []; research.value = { question: "", method: "", result: "" }; history.value = null;
      past.value = null; preview.value = null; diff.value = null; imports.value = null;
      initialized.value = false; emit("accessLost", cause);
    }
  } finally { busy.value = false; }
}
function hydrate(value: Manuscript) {
  if (!mounted) return;
  version.value = value.version; currentVersion.value = value.current_version;
  research.value = { ...value.research }; blocks.value = editableBlocks(value.blocks);
  saved.value = draft.value; initialized.value = true;
}
async function loadHistory(page = historyPage.value) {
  const data = await request<Page<Revision>>(`${base()}history/?page=${page}`);
  if (mounted) { history.value = data; historyPage.value = page; }
}
async function reload() {
  if (dirty.value && !(await confirmDiscard("放弃当前未保存的草稿并加载最新原稿？"))) return;
  hydrate(await request<Manuscript>(base()));
  await loadHistory(1);
}
async function save() {
  const data = await request<Manuscript>(base(), "PUT", { version: version.value, request_key: key, ...JSON.parse(draft.value) });
  hydrate(data); await loadHistory(1); key = crypto.randomUUID();
  message.value = `原稿 v${data.version} 已保存。`;
}
function add(level: number, index = blocks.value.length) {
  blocks.value.splice(index, 0, { id: crypto.randomUUID(), text: "", heading_level: level });
}
function move(index: number, step: number) {
  const item = blocks.value.splice(index, 1)[0]!; blocks.value.splice(index + step, 0, item);
}
async function inspect(number: number) {
  const data = await request<Manuscript>(`${base()}history/${number}/`);
  if (mounted) { past.value = data; currentVersion.value = data.current_version; before.value = number; after.value = data.current_version; }
}
async function compare() {
  const data = await request<ManuscriptDiff>(`${base()}diff/?before=${before.value}&after=${after.value}`);
  if (mounted) diff.value = data;
}
async function restore() {
  const data = await request<Manuscript>(`${base()}restore/`, "POST", { version: version.value, request_key: key, from_version: past.value!.version });
  hydrate(data); await loadHistory(1); key = crypto.randomUUID();
  message.value = `已恢复为新版本 v${data.version}，历史保留。`;
}
async function loadImports(page = importPage.value) {
  const data = await request<Page<ImportSource>>(`${base()}imports/?page=${page}`);
  if (mounted) { imports.value = data; importPage.value = page; }
}
async function previewImport(id: string) {
  const data = await request<ImportPreview>(`${base()}imports/${id}/`);
  if (mounted) preview.value = data;
}
async function importDocx() {
  const data = await request<Manuscript>(`${base()}imports/`, "POST", {
    version: version.value, request_key: key, parse_id: preview.value!.source.parse_id,
    token: preview.value!.token, mode: importMode.value,
  });
  hydrate(data); preview.value = null; await loadHistory(1); key = crypto.randomUUID();
  message.value = `DOCX 正文已保存为 v${data.version}。`;
}
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value) { event.preventDefault(); event.returnValue = ""; } }
onMounted(async () => {
  window.addEventListener("beforeunload", beforeUnload);
  await perform(reload);
});
onUnmounted(() => { mounted = false; emit("dirtyChange", false); window.removeEventListener("beforeunload", beforeUnload); });
</script>

<template>
  <section class="manuscript-workspace" aria-label="作者原稿" :aria-busy="busy">
    <div class="document-toolbar"><div class="actions"><h2 :aria-label="`作者原稿 · v${version}`">作者原稿</h2><NTag size="small" :bordered="false">v{{ version }}</NTag><span class="save-state">{{ dirty ? '未保存' : '已保存' }}</span></div><div class="actions"><NButton @click="perform(reload)" :disabled="(busy)">加载最新原稿</NButton><NButton v-if="canEdit" attr-type="button" @click="perform(save)" :disabled="(busy || !dirty)" type="primary"><Save :size="16" />保存原稿新版本</NButton></div></div>
    <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="busy" role="status">处理中…</p>
    <p v-if="dirty" role="status">有未保存的修改。</p>
    <p v-if="currentVersion > version" role="status">已有更新版本 v{{ currentVersion }}。</p>
    <form v-if="initialized" class="editor" @submit.prevent="perform(save)">
      <div class="document-layout">
      <aside class="document-outline"><h3><List :size="16" />目录</h3><nav v-if="headings.length" aria-label="章节树"><ol class="chapter-tree"><li v-for="heading in headings" :key="heading.id" :style="{ paddingLeft: `${Math.min(heading.heading_level - 1, 4) * 12}px` }"><a :href="`#block-${heading.id}`">{{ heading.text || '未填写标题' }}</a></li></ol></nav><p v-else class="notice">添加章节后显示目录</p></aside>
      <div class="document-paper">
      <NEmpty v-if="!blocks.length" description="从一个章节或一段正文开始" class="document-empty" />
      <div v-for="(block, index) in blocks" :id="`block-${block.id}`" :key="block.id" class="manuscript-block">
        <template v-if="canEdit">
          <div class="block-tools"><label class="block-kind"><span class="sr-only">块 {{ index + 1 }} 类型</span><UiSelect v-model="block.heading_level" :aria-label="`块 ${index + 1} 类型`" :disabled="(busy)" :options="[({ value: 0, label: '正文' }), ...Array.from({ length: 9 }, (_, i) => i + 1).map((level) => ({ value: level, label: String(level) + ' 级标题' }))]" /></label>
          <div class="actions">
            <NButton attr-type="button" @click="move(index, -1)" :aria-label="`上移块 ${index + 1}`" :title="`上移块 ${index + 1}`" :disabled="(busy || index === 0)"><ArrowUp :size="15" /></NButton>
            <NButton attr-type="button" @click="move(index, 1)" :aria-label="`下移块 ${index + 1}`" :title="`下移块 ${index + 1}`" :disabled="(busy || index === blocks.length - 1)"><ArrowDown :size="15" /></NButton>
            <NButton attr-type="button" @click="add(0, index + 1)" :disabled="(busy || blocks.length >= 500)" :aria-label="`在块 ${index + 1} 后插入`" :title="`在块 ${index + 1} 后插入`"><Plus :size="15" /></NButton>
            <NButton attr-type="button" @click="blocks.splice(index, 1)" :aria-label="`删除块 ${index + 1}`" :title="`删除块 ${index + 1}`" :disabled="(busy)"><Trash2 :size="15" /></NButton>
          </div></div>
          <label :class="['document-text', { 'document-heading': block.heading_level > 0 }]"><span class="sr-only">{{ block.heading_level ? '标题' : '正文块' }} {{ index + 1 }}</span><UiInput v-model="block.text" :aria-label="`${block.heading_level ? '标题' : '正文块'} ${index + 1}`" rows="1" maxlength="20000" :placeholder="block.heading_level ? '章节标题' : '在此撰写正文…'" :disabled="(busy)" type="textarea" /></label>
        </template>
        <component :is="block.heading_level ? 'h3' : 'p'" v-else class="plain-text">{{ block.text }}</component>
      </div>
      <div v-if="canEdit" class="actions">
        <NButton attr-type="button" @click="add(1)" :disabled="(busy || blocks.length >= 500)">添加章节</NButton>
        <NButton attr-type="button" @click="add(0)" :disabled="(busy || blocks.length >= 500)">添加正文块</NButton>

      </div>
      </div></div>
      <UiDisclosure class="research-details"><template #header>研究说明</template><fieldset :disabled="busy || !canEdit"><label v-for="(label, field) in researchLabels" :key="field">{{ label }}<UiInput v-model="research[field]" :readonly="!canEdit" maxlength="10000" rows="3" :disabled="(busy || !canEdit)" type="textarea" :aria-label="String(label)" /></label></fieldset></UiDisclosure>
    </form>
    <UiDisclosure v-if="canEdit && initialized"><template #header>导入 DOCX 正文</template>
      <NButton @click="perform(() => loadImports(1))" :disabled="(busy)">选择已解析 DOCX</NButton>
      <p v-if="imports?.count === 0">暂无可导入的 DOCX，请先在材料区上传并解析。</p>
      <ul class="project-list"><li v-for="source in imports?.results" :key="source.id"><NButton @click="perform(() => previewImport(source.id))" :disabled="(busy)">预览 {{ source.file_name }} · v{{ source.source_number }} · 解析 {{ source.number }}</NButton></li></ul>
      <div v-if="imports && (imports.next || imports.previous)" class="actions"><NButton @click="perform(() => loadImports(importPage - 1))" :disabled="(busy || !imports.previous)">上一页 DOCX</NButton><NButton @click="perform(() => loadImports(importPage + 1))" :disabled="(busy || !imports.next)">下一页 DOCX</NButton></div>
      <div v-if="preview" aria-label="DOCX 导入预览">
        <h3>{{ preview.source.file_name }}</h3>
        <p>仅导入顶层文字段落与标题，不保留 Word 排版、表格、图片或公式。</p>
        <p v-for="warning in preview.source.warnings" :key="warning" role="status">{{ warning }}</p>
        <div class="import-preview"><component :is="block.heading_level ? 'h4' : 'p'" v-for="block in preview.blocks" :key="block.id" class="plain-text">{{ block.text }}</component></div>
        <label>导入方式<UiSelect v-model="importMode" aria-label="导入方式" :disabled="(busy)" :options="[({ value: 'append', label: '追加到正文末尾' }), ({ value: 'replace', label: '替换正文并保留历史' })]" /></label>
        <p v-if="dirty">请先保存原稿修改，再导入。</p>
        <NButton @click="perform(importDocx)" :disabled="(busy || dirty)">确认导入并保存新版本</NButton>
      </div>
    </UiDisclosure>
    <UiDisclosure><template #header>历史版本与对照</template>
      <NButton @click="perform(() => loadHistory(1))" :disabled="(busy)">刷新原稿历史</NButton>
      <p v-if="history?.count === 0">暂无已保存版本。</p>
      <ul class="project-list"><li v-for="revision in history?.results" :key="revision.version"><NButton @click="perform(() => inspect(revision.version))" :disabled="(busy)">查看原稿 v{{ revision.version }} · {{ origins[revision.origin] }}</NButton></li></ul>
      <div v-if="history && (history.next || history.previous)" class="actions"><NButton @click="perform(() => loadHistory(historyPage - 1))" :disabled="(busy || !history.previous)">上一页原稿版本</NButton><NButton @click="perform(() => loadHistory(historyPage + 1))" :disabled="(busy || !history.next)">下一页原稿版本</NButton></div>
      <article v-if="past" aria-label="历史原稿">
        <h3>历史原稿 v{{ past.version }}</h3>
        <p>{{ origins[past.origin] }} · {{ past.created_at ? new Date(past.created_at).toLocaleString() : '' }}</p>
        <p v-for="warning in past.source.warnings" :key="warning">{{ warning }}</p>
        <div v-for="(label, field) in researchLabels" :key="field"><h4>{{ label }}</h4><p class="plain-text">{{ past.research[field] }}</p></div>
        <component :is="block.heading_level ? 'h4' : 'p'" v-for="block in past.blocks" :key="block.id" class="plain-text">{{ block.text }}</component>
        <p v-if="dirty && canEdit">请先保存当前修改，再恢复旧稿。</p>
        <NButton v-if="canEdit" @click="perform(restore)" :disabled="(busy || dirty)">恢复此稿为新版本</NButton>
      </article>
      <form class="editor" @submit.prevent="perform(compare)"><fieldset :disabled="busy"><legend>版本对照</legend>
        <label>原版本<UiInput v-model="before" type="number" min="0" :max="currentVersion" required :disabled="(busy)" :aria-label="'原版本'" /></label>
        <label>对照版本<UiInput v-model="after" type="number" min="0" :max="currentVersion" required :disabled="(busy)" :aria-label="'对照版本'" /></label>
        <NButton attr-type="submit" :disabled="(busy)" type="primary">查看原稿差异</NButton>
      </fieldset></form>
      <div v-if="diff" aria-label="原稿差异">
        <h3>v{{ diff.before }} → v{{ diff.after }}</h3>
        <p v-if="!diff.blocks.length && !Object.keys(diff.research).length">内容和顺序相同。</p>
        <div v-for="(change, field) in diff.research" :key="field"><h4>{{ researchLabels[field] }}</h4><div class="comparison"><div><strong>原版本</strong><p class="plain-text">{{ change?.before }}</p></div><div><strong>对照版本</strong><p class="plain-text">{{ change?.after }}</p></div></div></div>
        <div v-for="change in diff.blocks" :key="change.id"><h4>{{ change.kinds.map(kind => kinds[kind]).join('、') }} · 块 {{ change.before_position ?? '无' }} → {{ change.after_position ?? '无' }}</h4>
          <div class="comparison"><div><strong>原版本{{ change.before?.heading_level ? ` · ${change.before.heading_level} 级标题` : '' }}</strong><p class="plain-text">{{ change.before?.text ?? '（无）' }}</p></div><div><strong>对照版本{{ change.after?.heading_level ? ` · ${change.after.heading_level} 级标题` : '' }}</strong><p class="plain-text">{{ change.after?.text ?? '（无）' }}</p></div></div>
        </div>
      </div>
    </UiDisclosure>
  </section>
</template>

<style scoped>
.manuscript-block { margin-block: 1rem; scroll-margin-top: 1rem; }
.chapter-tree { list-style: none; padding: 0; }
.chapter-tree a { overflow-wrap: anywhere; }
.plain-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; padding: .75rem; border: 1px solid var(--border); }
.import-preview { max-height: 24rem; overflow-y: auto; padding: .75rem; border: 1px solid var(--border); }
@media (max-width: 600px) { .comparison { grid-template-columns: 1fr; } }
</style>
