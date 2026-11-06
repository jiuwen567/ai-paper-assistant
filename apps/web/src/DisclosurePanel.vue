<script setup lang="ts">
import { useConfirm } from "./ui/confirm";
const confirmDiscard = useConfirm();
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import { purposeLabels, type DisclosureRevision, type DisclosureState, type ExternalUse, type Usage } from "./disclosure";
import UsageRecord from "./UsageRecord.vue";
const props = defineProps<{ project: Project }>();
const emit = defineEmits<{ accessLost: [error: ApiError]; dirtyChange: [value: boolean] }>();
const state = ref<DisclosureState | null>(null), records = ref<Page<Usage> | null>(null), history = ref<Page<DisclosureRevision> | null>(null);
const historical = ref<DisclosureRevision & { facts: { manuscript_version: number; summary: DisclosureState['summary'] } } | null>(null);
const text = ref(""), external = ref<ExternalUse[]>([]), verified = ref(false), version = ref(0);
const busy = ref(false), error = ref(""), message = ref(""), recordPage = ref(1), historyPage = ref(1), baseline = ref("");
const editable = computed(() => props.project.role === "author");
const content = () => JSON.stringify({ text: text.value, external: external.value, verified: verified.value });
const dirty = computed(() => editable.value && baseline.value !== "" && baseline.value !== content());
const versionChanged = computed(() => version.value !== (state.value?.current?.number || 0));
let mounted = true, key = crypto.randomUUID();
const base = () => `projects/${props.project.id}/`;
watch([text, external, verified, version], () => { key = crypto.randomUUID(); message.value = ""; }, { deep: true });
watch([text, external], () => {
  if (baseline.value && baseline.value !== content()) verified.value = false;
}, { deep: true, flush: "sync" });
watch(dirty, value => emit("dirtyChange", value));
async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return;
  busy.value = true; error.value = ""; message.value = "";
  try { await action(); }
  catch (cause) {
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) accessLost(cause);
  } finally { if (mounted) busy.value = false; }
}
function accessLost(cause: ApiError) {
  state.value = null; records.value = null; history.value = null; historical.value = null;
  text.value = ""; external.value = []; baseline.value = "";
  emit("accessLost", cause);
}
function applySaved() {
  const current = state.value?.current;
  text.value = current?.text ?? state.value?.draft ?? "";
  external.value = (current?.external_uses || []).map(item => ({ ...item }));
  verified.value = Boolean(current?.verified && !state.value?.stale);
  version.value = current?.number || 0; baseline.value = content();
}
async function loadRecords(number = recordPage.value) {
  const value = await request<Page<Usage>>(`${base()}usage/?page=${number}`);
  if (mounted) { records.value = value; recordPage.value = number; }
}
async function loadHistory(number = historyPage.value) {
  const value = await request<Page<DisclosureRevision>>(`${base()}disclosure/history/?page=${number}`);
  if (mounted) { history.value = value; historyPage.value = number; }
}
async function refresh(initial = false) {
  const value = await request<DisclosureState>(base() + "disclosure/");
  if (!mounted) return;
  if (state.value?.facts_token !== value.facts_token) { verified.value = false; key = crypto.randomUUID(); }
  state.value = value;
  if (initial || !editable.value) applySaved();
  await Promise.all([loadRecords(), loadHistory()]);
}
async function reloadSaved() { if (!dirty.value || (await confirmDiscard("用已保存清单替换当前未保存草稿？"))) applySaved(); }
function adoptBase() { version.value = state.value?.current?.number || 0; verified.value = false; }
async function save() {
  const value = await request<DisclosureState>(base() + "disclosure/", "POST", {
    version: version.value, request_key: key, facts_token: state.value!.facts_token,
    text: text.value, external_uses: external.value, verified: verified.value,
  });
  if (!mounted) return;
  state.value = value; applySaved();
  await loadHistory(1); message.value = "披露清单已保存为新版本。";
}
async function viewHistory(number: number) {
  const value = await request<NonNullable<typeof historical.value>>(`${base()}disclosure/history/${number}/`);
  if (mounted) historical.value = value;
}
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value) { event.preventDefault(); event.returnValue = ""; } }
onMounted(() => { window.addEventListener("beforeunload", beforeUnload); void perform(() => refresh(true)); });
onUnmounted(() => { mounted = false; window.removeEventListener("beforeunload", beforeUnload); emit("dirtyChange", false); });
</script>
<template>
  <section aria-label="AI 使用与披露" :aria-busy="busy">
    <h2>AI 使用与披露</h2>
    <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert><p v-if="message" role="status">{{ message }}</p><p v-if="busy" role="status">处理中…</p>
    <NButton @click="perform(() => refresh(!state))" :disabled="(busy)">刷新使用记录</NButton>
    <template v-if="state">
      <p>发起模型调用 {{ state.summary.calls }} 次 · 表达建议 {{ state.summary.expression_suggestions }} 条 · 实际采纳 {{ state.summary.accepted }} 条</p>
      <p>阅读记录 {{ state.summary.reading_records }} 份 · 摘记 {{ state.summary.notes }} 条 · 诊断 {{ state.summary.review_findings }} 条</p>
      <p v-if="state.summary.feedback_candidates">反馈候选 {{ state.summary.feedback_candidates }} 条 · 作者确认待办 {{ state.summary.confirmed_tasks }} 项 · 作者标记完成 {{ state.summary.completed_tasks }} 项（不计入正文采纳）</p>
      <p>仅记录系统内任务和明确保存的采纳。调用与产出不代表采纳；系统外使用由作者补充，不推算原创比例，不出具原创或学术合规证明。</p>
      <UiDisclosure><template #header>按使用环节查看</template><ul><li v-for="(counts, purpose) in state.purposes" :key="purpose">{{ purposeLabels[purpose] || purpose }}：任务 {{ counts.tasks }}，发起调用 {{ counts.calls }}，成功调用 {{ counts.successful_calls }}，发布结果的任务 {{ counts.published_tasks }}，实际采纳 {{ counts.accepted }}</li></ul></UiDisclosure>
      <p v-if="state.current">已保存清单 v{{ state.current.number }} · {{ state.stale ? '记录或稿件已变化，需重新核对' : state.current.verified ? '作者已核对' : '待作者核对' }}</p>
      <form class="editor" @submit.prevent="perform(save)"><fieldset :disabled="busy || !editable">
        <label>AI 使用说明<UiInput v-model="text" rows="7" maxlength="20000" :disabled="(busy || !editable)" type="textarea" :aria-label="'AI 使用说明'" /></label>
        <UiDisclosure><template #header>当前记录生成的参考草稿</template><p class="source-text">{{ state.draft }}</p></UiDisclosure>
        <h3>系统外使用（作者补充）</h3>
        <p v-if="!external.length">尚未补充系统外使用。</p>
        <fieldset v-for="(item, index) in external" :key="index"><legend>外部使用 {{ index + 1 }}</legend>
          <label>工具与版本<UiInput v-model="item.tool" required maxlength="200" :disabled="(busy || !editable)" :aria-label="'工具与版本'" /></label>
          <label>用途<UiInput v-model="item.purpose" required maxlength="1000" :disabled="(busy || !editable)" :aria-label="'用途'" /></label>
          <label>使用范围或稿件位置<UiInput v-model="item.scope" required maxlength="1000" :disabled="(busy || !editable)" :aria-label="'使用范围或稿件位置'" /></label>
          <label>使用时间<UiInput v-model="item.used_at" maxlength="100" :disabled="(busy || !editable)" :aria-label="'使用时间'" /></label>
          <label>实际采纳与备注<UiInput v-model="item.note" maxlength="2000" rows="2" :disabled="(busy || !editable)" type="textarea" :aria-label="'实际采纳与备注'" /></label>
          <NButton v-if="editable" attr-type="button" @click="external.splice(index, 1)" :disabled="(busy || !editable)">移除外部使用 {{ index + 1 }}</NButton>
        </fieldset>
        <NButton v-if="editable" attr-type="button" @click="external.push({ tool: '', purpose: '', scope: '', used_at: '', note: '' })" :disabled="(busy || !editable) || (external.length >= 50)">补充外部使用</NButton>
        <UiCheckbox v-model="verified" :disabled="(busy || !editable)" :aria-label="'已核对使用记录、实际采纳和系统外补充'" class="check-label">已核对使用记录、实际采纳和系统外补充</UiCheckbox>
        <p v-if="versionChanged">另有新版本。请对照已保存清单，再决定保留当前草稿。</p>
        <UiDisclosure v-if="versionChanged && state.current"><template #header>最新保存的说明</template><p class="source-text">{{ state.current.text }}</p><p v-for="(item, index) in state.current.external_uses" :key="index">{{ item.tool }} · {{ item.purpose }} · {{ item.scope }} · {{ item.used_at }} · {{ item.note }}</p></UiDisclosure>
        <NButton v-if="versionChanged" attr-type="button" @click="adoptBase" :disabled="(busy || !editable)">保留草稿并更新保存基准</NButton>
        <NButton v-if="editable" attr-type="button" @click="reloadSaved" :disabled="(busy || !editable)">载入已存清单</NButton>
        <NButton v-if="editable" attr-type="submit" :disabled="(busy || !editable) || (versionChanged)" type="primary">保存披露新版本</NButton>
      </fieldset></form>
      <UiDisclosure><template #header>披露修改历史</template><p v-if="!history?.count">暂无已保存版本。</p>
        <NButton v-for="revision in history?.results" :key="revision.number" @click="perform(() => viewHistory(revision.number))" :disabled="(busy)">清单 v{{ revision.number }} · {{ revision.verified ? '当时已核对' : '当时未核对' }}</NButton>
        <div v-if="history && (history.next || history.previous)" class="actions"><NButton @click="perform(() => loadHistory(historyPage - 1))" :disabled="(busy || !history.previous)">上一页披露历史</NButton><NButton @click="perform(() => loadHistory(historyPage + 1))" :disabled="(busy || !history.next)">下一页披露历史</NButton></div>
        <article v-if="historical" aria-label="披露历史版本"><h3>清单 v{{ historical.number }} · 稿件 v{{ historical.facts.manuscript_version }}</h3><p>记录人 {{ historical.created_by }} · {{ new Date(historical.created_at).toLocaleString() }}</p><p class="source-text">{{ historical.text }}</p><p>当时发起调用 {{ historical.facts.summary.calls }} 次，实际采纳 {{ historical.facts.summary.accepted }} 条。</p><p v-for="(item, index) in historical.external_uses" :key="index">{{ item.tool }} · {{ item.purpose }} · {{ item.scope }} · {{ item.used_at }} · {{ item.note }}</p></article>
      </UiDisclosure>
      <UiDisclosure><template #header>逐项回查使用记录</template><p v-if="!records?.count">暂无系统内模型任务。</p>
        <UsageRecord v-for="record in records?.results" :key="`${record.id}-${state.facts_token}`" :project="project" :usage="record" @access-lost="accessLost" />
        <div v-if="records && (records.next || records.previous)" class="actions"><NButton @click="perform(() => loadRecords(recordPage - 1))" :disabled="(busy || !records.previous)">上一页使用记录</NButton><NButton @click="perform(() => loadRecords(recordPage + 1))" :disabled="(busy || !records.next)">下一页使用记录</NButton></div>
      </UiDisclosure>
    </template>
  </section>
</template>
