<script setup lang="ts">
import { useConfirm } from "./ui/confirm";
const confirmDiscard = useConfirm();
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import type { Manuscript } from "./manuscript";
import { anchorLabel, type Anchor, type SourceLocation } from "./sources";
import { graphLabels, relationLabels, linkStateLabels, type EvidenceLink, type GraphPath, type GraphResult, type LinkDecision } from "./graph";
import SourceContext from "./SourceContext.vue";
import { decisionLabels, supportLabels, type ReviewFinding } from "./review";
const props = defineProps<{ project: Project }>();
const emit = defineEmits<{ accessLost: [error: ApiError]; dirtyChange: [value: boolean] }>();
type Evidence = { id: string; chunk: string; quote: string; anchor: Anchor; source: { file_name: string; access_state: string } };
type Material = { id: string; title: string };
const manuscript = ref<Manuscript | null>(null), materials = ref<Page<Material> | null>(null), evidence = ref<Page<Evidence> | null>(null);
const graph = ref<GraphResult | null>(null), links = ref<Page<EvidenceLink> | null>(null), selected = ref<EvidenceLink | null>(null);
const diagnosis = ref<ReviewFinding | null>(null);
const sourceContext = ref<SourceLocation | null>(null), fixed = ref<GraphPath | null>(null), history = ref<Page<LinkDecision> | null>(null);
const busy = ref(false), error = ref(""), message = ref(""), blockFilter = ref(""), materialFilter = ref("");
const evidencePage = ref(1), materialPage = ref(1), linkPage = ref(1), historyPage = ref(1);
const blockId = ref(""), location = ref<{ version: number; block_id: string; text: string } | null>(null), chosenEvidence = ref<Evidence | null>(null);
const claim = ref(""), quote = ref(""), claimOccurrence = ref(1), evidenceOccurrence = ref(1), kind = ref("supports"), note = ref(""), confirmed = ref(false);
const decisionState = ref("confirmed"), decisionKind = ref("supports"), decisionNote = ref(""), decisionConfirmed = ref(false), decisionVersion = ref(0), decisionBaseline = ref("");
const decisionPayload = () => ({ state: decisionState.value, kind: decisionKind.value, note: decisionNote.value, confirmed: decisionConfirmed.value });
const decisionDirty = computed(() => !!selected.value && decisionBaseline.value !== JSON.stringify(decisionPayload()));
const dirty = computed(() => props.project.role === "author" && (!!claim.value || !!quote.value || !!note.value || decisionDirty.value));
let mounted = true, key = crypto.randomUUID(), decisionKey = crypto.randomUUID(), rebuildKey = crypto.randomUUID(), rebuildVersion: number | null = null;
const base = () => `projects/${props.project.id}/`;
watch([claim, quote, claimOccurrence, evidenceOccurrence, kind, note, location, chosenEvidence], () => { key = crypto.randomUUID(); confirmed.value = false; }, { deep: true });
watch(confirmed, () => { key = crypto.randomUUID(); });
watch([decisionState, decisionKind, decisionNote], () => { decisionKey = crypto.randomUUID(); decisionConfirmed.value = false; });
watch(decisionConfirmed, () => { decisionKey = crypto.randomUUID(); });
watch(dirty, value => emit("dirtyChange", value));
function lost(cause: ApiError) { graph.value = null; links.value = null; selected.value = null; fixed.value = null; sourceContext.value = null; diagnosis.value = null; manuscript.value = null; materials.value = null; evidence.value = null; chosenEvidence.value = null; location.value = null; claim.value = quote.value = note.value = decisionNote.value = ""; emit("accessLost", cause); }
async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return; busy.value = true; error.value = ""; message.value = "";
  try { await action(); } catch (cause) { if (!mounted) return; error.value = cause instanceof Error ? cause.message : "请求失败，请重试。"; if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) lost(cause); }
  finally { if (mounted) busy.value = false; }
}
async function loadGraph(page = 1) { const params = new URLSearchParams({ page: String(page) }); if (blockFilter.value) params.set("block_id", blockFilter.value); if (materialFilter.value) params.set("material_id", materialFilter.value); const value = await request<GraphResult>(base() + "graph/paths/?" + params); if (mounted) { if (graph.value && graph.value.revision !== value.revision) { fixed.value = null; sourceContext.value = null; diagnosis.value = null; } graph.value = value; } }
async function loadEvidence(page = 1) { const value = await request<Page<Evidence>>(base() + "evidence/?page=" + page); if (mounted) { evidence.value = value; evidencePage.value = page; } }
async function loadMaterials(page = 1) { const value = await request<Page<Material>>(base() + "materials/?page=" + page); if (mounted) { materials.value = value; materialPage.value = page; } }
async function loadLinks(page = linkPage.value) { const value = await request<Page<EvidenceLink>>(base() + "evidence-links/?page=" + page); if (mounted) { links.value = value; linkPage.value = page; } }
async function refresh() { const draft = await request<Manuscript>(base() + "manuscript/"); if (mounted) manuscript.value = draft; await Promise.all([loadGraph(), loadEvidence(evidencePage.value), loadMaterials(materialPage.value), loadLinks()]); if (selected.value) await refreshLink(); }
function chooseBlock() { const block = manuscript.value?.blocks.find(item => item.id === blockId.value); location.value = block && manuscript.value ? { version: manuscript.value.version, block_id: block.id, text: block.text } : null; }
function chooseEvidence(item: Evidence) { chosenEvidence.value = item; quote.value = item.quote.slice(0, 2000); evidenceOccurrence.value = 1; }
async function create() { if (!location.value || !chosenEvidence.value) return; await request(base() + "evidence-links/", "POST", { request_key: key, manuscript_version: location.value.version, block_id: location.value.block_id, chunk_id: chosenEvidence.value.chunk, claim: claim.value, claim_occurrence: claimOccurrence.value, evidence_quote: quote.value, evidence_occurrence: evidenceOccurrence.value, kind: kind.value, note: note.value, confirmed: confirmed.value }); if (mounted) { claim.value = quote.value = note.value = ""; chosenEvidence.value = null; confirmed.value = false; message.value = "依据关系已保存，等待图同步。"; await Promise.all([loadGraph(), loadLinks(1)]); } }
async function loadDiagnosis(id: string) { const value = await request<ReviewFinding>(base() + `review-findings/${id}/`); if (mounted) diagnosis.value = value; }
async function loadSource(id: string) { const value = await request<SourceLocation>(base() + `chunks/${id}/`); if (mounted) sourceContext.value = value; }
async function selectLink(id: string) {
  if (decisionDirty.value && !(await confirmDiscard("切换关系将放弃未保存决定，是否继续？"))) return;
  const value = await request<EvidenceLink>(base() + `evidence-links/${id}/`);
  if (mounted) { selected.value = value; decisionState.value = value.current.state; decisionKind.value = value.current.kind; decisionNote.value = value.current.note; decisionConfirmed.value = false; decisionVersion.value = value.current.number; decisionBaseline.value = JSON.stringify(decisionPayload()); history.value = null; }
}
async function refreshLink() { if (!selected.value) return; const value = await request<EvidenceLink>(base() + `evidence-links/${selected.value.id}/`); if (mounted) selected.value = value; }
function adoptDecision() { if (selected.value) { decisionVersion.value = selected.value.current.number; decisionKey = crypto.randomUUID(); decisionConfirmed.value = false; } }
async function saveDecision() { const value = await request<EvidenceLink>(base() + `evidence-links/${selected.value!.id}/`, "POST", { ...decisionPayload(), version: decisionVersion.value, request_key: decisionKey }); if (mounted) { selected.value = value; decisionVersion.value = value.current.number; decisionConfirmed.value = false; decisionBaseline.value = JSON.stringify(decisionPayload()); message.value = "关系决定已保存，等待图同步。"; await Promise.all([loadGraph(), loadLinks()]); } }
async function loadHistory(page = 1) { const value = await request<Page<LinkDecision>>(base() + `evidence-links/${selected.value!.id}/history/?page=${page}`); if (mounted) { history.value = value; historyPage.value = page; } }
async function rebuild() { if (!graph.value) return; if (rebuildVersion !== graph.value.revision) { rebuildKey = crypto.randomUUID(); rebuildVersion = graph.value.revision; } await request(base() + "graph/rebuild/", "POST", { request_key: rebuildKey, revision: rebuildVersion }); if (mounted) { message.value = "已登记重建请求。"; await loadGraph(); } }
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value) { event.preventDefault(); event.returnValue = ""; } }
onMounted(() => { window.addEventListener("beforeunload", beforeUnload); void perform(refresh); });
onUnmounted(() => { mounted = false; window.removeEventListener("beforeunload", beforeUnload); emit("dirtyChange", false); });
</script>
<template>
  <section aria-label="依据关系" :aria-busy="busy"><h2>依据关系</h2>
    <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert><p v-if="message" role="status">{{ message }}</p><p v-if="busy" role="status">处理中…</p>
    <NButton @click="perform(refresh)" :disabled="(busy)">刷新依据关系</NButton>
    <p v-if="graph" role="status">{{ graphLabels[graph.status] }} · 业务 v{{ graph.revision }} / 图 v{{ graph.projected_revision ?? 0 }}</p>
    <p v-if="graph?.error_code" class="error">同步诊断：{{ graph.error_code }}</p>
    <NButton v-if="project.role === 'author'" @click="perform(rebuild)" :disabled="(busy || !graph)">重建本项目关系图</NButton>
    <form class="actions" @submit.prevent="perform(() => loadGraph())">
      <label>按正文查依据<UiSelect v-model="blockFilter" aria-label="按正文查依据" :disabled="(busy)" :options="[({ value: '', label: '全部正文版本' }), ...(manuscript?.blocks ?? []).map((block, index) => ({ value: block.id, label: '块 ' + String(index + 1) + '：' + String(block.text.slice(0, 35)) }))]" /></label>
      <label>按材料查正文<UiSelect v-model="materialFilter" aria-label="按材料查正文" :disabled="(busy)" :options="[({ value: '', label: '全部材料' }), ...(materials?.results ?? []).map((item) => ({ value: item.id, label: String(item.title) }))]" /></label><NButton :disabled="(busy)" attr-type="submit">查询路径</NButton>
    </form>
    <div v-if="materials?.next || materials?.previous"><NButton @click="perform(() => loadMaterials(materialPage - 1))" :disabled="(busy || !materials?.previous)">上一页材料选项</NButton><NButton @click="perform(() => loadMaterials(materialPage + 1))" :disabled="(busy || !materials?.next)">下一页材料选项</NButton></div>
    <p v-if="graph?.status === 'synced' && graph.count === 0">当前查询范围没有已登记的依据路径。</p>
    <article v-for="item in graph?.results" :key="item.id" :aria-label="`依据路径：${item.claim.slice(0, 50)}`">
      <h3>原稿 v{{ item.location.manuscript_version }} · 块 {{ item.location.position }} → 主张 → 证据 → {{ item.material_title }} v{{ item.source_number }}</h3>
      <p>{{ linkStateLabels[item.state] }} · {{ relationLabels[item.kind] }}<span v-if="item.location.stale || item.needs_review"> · 原稿或来源已变化，需重新核对</span></p>
      <p v-if="item.origin === 'model'">诊断中的模型候选；问题状态：{{ item.finding_status === 'confirmed' ? '作者确认问题' : '待判断' }}。不代表作者确认支持关系。</p>
      <p v-if="item.origin === 'citation'">此路径记录正文引用，不证明材料支持该段全部论述。</p>
      <blockquote>{{ item.claim }}</blockquote><blockquote>{{ item.evidence_quote }}</blockquote><p>{{ anchorLabel(item.anchor) }}</p>
      <NButton @click="fixed = item" :disabled="(busy)">回查固定正文</NButton><NButton @click="perform(() => loadSource(item.chunk_id))" :disabled="(busy)">回查依据原文</NButton><NButton v-if="item.finding_id" @click="perform(() => loadDiagnosis(item.finding_id!))" :disabled="(busy)">回查诊断记录</NButton><NButton v-if="item.link_id" @click="perform(() => selectLink(item.link_id!))" :disabled="(busy)">查看关系决定</NButton>
    </article>
    <div v-if="graph && (graph.next || graph.previous)"><NButton @click="perform(() => loadGraph(graph!.page - 1))" :disabled="(busy || !graph.previous)">上一页路径</NButton><NButton @click="perform(() => loadGraph(graph!.page + 1))" :disabled="(busy || !graph.next)">下一页路径</NButton></div>
    <section v-if="fixed" aria-label="路径固定正文"><h3>原稿 v{{ fixed.location.manuscript_version }} · 块 {{ fixed.location.position }}</h3><p class="source-text">{{ fixed.location.text }}</p></section>
    <section v-if="diagnosis" aria-label="路径诊断记录"><h3>原稿 v{{ diagnosis.manuscript_version }} 的诊断 · {{ decisionLabels[diagnosis.status] }}</h3><blockquote>{{ diagnosis.model_output.quote }}</blockquote><p>{{ supportLabels[diagnosis.model_output.support] }} · {{ diagnosis.model_output.reason }}</p><p>{{ diagnosis.model_output.action }}</p><p v-if="diagnosis.author_decision">{{ diagnosis.author_decision.reason }}</p></section>
    <SourceContext v-if="sourceContext" :project="project" :location="sourceContext" />
    <UiDisclosure v-if="project.role === 'author'"><template #header>登记作者核对的依据</template>
      <form class="editor" @submit.prevent="perform(create)"><fieldset :disabled="busy">
        <label>选择原稿正文<UiSelect v-model="blockId" aria-label="选择原稿正文" @change="chooseBlock" :disabled="(busy)" :options="[({ value: '', label: '选择正文块' }), ...(manuscript?.blocks ?? []).map((block, index) => ({ value: block.id, label: '块 ' + String(index + 1) + '：' + String(block.text.slice(0, 40)) }))]" /></label>
        <p v-if="location">原稿 v{{ location.version }}：{{ location.text }}</p>
        <label>原稿中的主张<UiInput v-model="claim" rows="2" maxlength="2000" required :disabled="(busy)" type="textarea" :aria-label="'原稿中的主张'" /></label><label>主张原话出现次序<UiInput v-model="claimOccurrence" type="number" min="1" max="1000" required :disabled="(busy)" :aria-label="'主张原话出现次序'" /></label>
        <p v-if="!evidence?.count">请先在资料区保存来源证据卡。</p><NButton v-for="item in evidence?.results" :key="item.id" attr-type="button" @click="chooseEvidence(item)" :disabled="(busy) || (item.source.access_state !== 'active')">{{ item.source.file_name }} · {{ anchorLabel(item.anchor) }}：{{ item.quote.slice(0, 70) }}</NButton>
        <NButton attr-type="button" @click="perform(() => loadEvidence(evidencePage - 1))" :disabled="(busy) || (!evidence?.previous)">上一页依据选项</NButton><NButton attr-type="button" @click="perform(() => loadEvidence(evidencePage + 1))" :disabled="(busy) || (!evidence?.next)">下一页依据选项</NButton>
        <p v-if="chosenEvidence">已选：{{ chosenEvidence.source.file_name }} · {{ anchorLabel(chosenEvidence.anchor) }}</p>
        <label>来源原话<UiInput v-model="quote" rows="2" maxlength="2000" required :disabled="(busy)" type="textarea" :aria-label="'来源原话'" /></label><label>来源原话出现次序<UiInput v-model="evidenceOccurrence" type="number" min="1" max="1000" required :disabled="(busy)" :aria-label="'来源原话出现次序'" /></label>
        <label>关系<UiSelect v-model="kind" aria-label="登记依据关系" :disabled="(busy)" :options="[({ value: 'supports', label: '支持' }), ({ value: 'contradicts', label: '矛盾' }), ({ value: 'context', label: '背景材料' })]" /></label><label>核对说明<UiInput v-model="note" rows="2" maxlength="2000" :disabled="(busy)" type="textarea" :aria-label="'核对说明'" /></label>
        <UiCheckbox v-model="confirmed" :disabled="(busy)" :aria-label="'已核对主张、来源原话与关系'" class="check-label">已核对主张、来源原话与关系</UiCheckbox><NButton :disabled="(busy) || (!confirmed || !location || !chosenEvidence)" attr-type="submit">保存依据关系</NButton>
      </fieldset></form>
    </UiDisclosure>
    <UiDisclosure><template #header>作者关系记录（含撤回）</template><p v-if="links?.count === 0">暂无作者关系记录。</p><NButton v-for="item in links?.results" :key="item.id" @click="perform(() => selectLink(item.id))" :disabled="(busy)">{{ item.claim.slice(0, 50) }} · {{ linkStateLabels[item.current.state] }}{{ item.needs_review ? ' · 需复核' : '' }}</NButton>
      <NButton @click="perform(() => loadLinks(linkPage - 1))" :disabled="(busy || !links?.previous)">上一页关系记录</NButton><NButton @click="perform(() => loadLinks(linkPage + 1))" :disabled="(busy || !links?.next)">下一页关系记录</NButton>
    </UiDisclosure>
    <section v-if="selected" aria-label="作者关系决定"><h3>关系决定 v{{ selected.current.number }}</h3><blockquote>{{ selected.claim }}</blockquote><blockquote v-if="selected.source_available">{{ selected.evidence_quote }}</blockquote><p v-else>来源已撤回，原话不再展示。</p><p v-if="selected.needs_review">原稿或来源已变化，需重新核对；原稿主张变化时须另登记新关系。</p>
      <NButton @click="perform(refreshLink)" :disabled="(busy)">刷新关系决定（保留草稿）</NButton>
      <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(saveDecision)"><fieldset :disabled="busy">
        <label>决定状态<UiSelect v-model="decisionState" aria-label="决定状态" :disabled="(busy)" :options="[({ value: 'confirmed', label: '作者已核对' }), ({ value: 'withdrawn', label: '撤回关系' })]" /></label><label>决定关系<UiSelect v-model="decisionKind" aria-label="决定关系" :disabled="(busy)" :options="[({ value: 'supports', label: '支持' }), ({ value: 'contradicts', label: '矛盾' }), ({ value: 'context', label: '背景材料' })]" /></label><label>关系决定说明<UiInput v-model="decisionNote" rows="2" maxlength="2000" :disabled="(busy)" type="textarea" :aria-label="'关系决定说明'" /></label>
        <UiCheckbox v-model="decisionConfirmed" :disabled="(busy)" :aria-label="'已重新核对当前主张与依据'" v-if="decisionState === 'confirmed'" class="check-label">已重新核对当前主张与依据</UiCheckbox>
        <div v-if="decisionVersion !== selected.current.number"><p>另有新决定：{{ linkStateLabels[selected.current.state] }} · {{ selected.current.note }}</p><NButton attr-type="button" @click="adoptDecision" :disabled="(busy)">保留说明并更新决定基准</NButton></div>
        <NButton :disabled="(busy) || (decisionVersion !== selected.current.number || (decisionState === 'confirmed' && !decisionConfirmed))" attr-type="submit">保存关系决定</NButton>
      </fieldset></form>
      <NButton @click="perform(() => loadHistory())" :disabled="(busy)">查看关系历史</NButton><article v-for="item in history?.results" :key="item.number"><h4>关系 v{{ item.number }} · {{ linkStateLabels[item.state] }} · {{ relationLabels[item.kind] }}</h4><p>{{ item.note }} · 记录人 {{ item.created_by }}</p></article>
      <div v-if="history && (history.next || history.previous)"><NButton @click="perform(() => loadHistory(historyPage - 1))" :disabled="(busy || !history.previous)">上一页关系历史</NButton><NButton @click="perform(() => loadHistory(historyPage + 1))" :disabled="(busy || !history.next)">下一页关系历史</NButton></div>
    </section>
  </section>
</template>
<style scoped>
button { white-space: normal; overflow-wrap: anywhere; max-width: 100%; }
h3, blockquote { overflow-wrap: anywhere; }
</style>
