<script setup lang="ts">
import { useConfirm } from "./ui/confirm";
const confirmDiscard = useConfirm();
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import { changeLabels, usageLabels, type ImpactItem, type ImpactRun, type ImpactSource, type MaterialChange } from "./impact";
import type { Manuscript } from "./manuscript";
import type { Chunk, SourceLocation } from "./sources";
import { statusLabels } from "./disclosure";
import ImpactItemCard from "./ImpactItemCard.vue";
import SourceContext from "./SourceContext.vue";
type Version = { id: string; number: number; file_name: string; status: string; usage_state: string; usage_version: number };
type Material = { id: string; title: string; access_state: string; state_version: number };
type Job = { id: string; status: string; generation: number; retryable: boolean; error_message: string; output: { summary: string } | null };
const props = defineProps<{ project: Project }>();
const emit = defineEmits<{ accessLost: [error: ApiError]; dirtyChange: [value: boolean] }>();
const materials = ref<Material[]>([]), versions = ref<Version[]>([]), materialId = ref(""), oldId = ref(""), newId = ref(""), kind = ref("supplement"), note = ref(""), confirmed = ref(false);
const records = ref<Page<MaterialChange> | null>(null), selected = ref<MaterialChange | null>(null), runs = ref<Page<ImpactRun> | null>(null), run = ref<ImpactRun | null>(null), items = ref<Page<ImpactItem> | null>(null);
const recordPage = ref(1), runPage = ref(1), itemPage = ref(1), chunkPage = ref(1), busy = ref(false), error = ref(""), message = ref(""), dirtyItems = ref(new Set<string>());
const manuscript = ref<Manuscript | null>(null), blocks = ref<string[]>([]), job = ref<Job | null>(null), jobs = ref<Page<Job> | null>(null), jobPage = ref(1);
const reading = ref<ImpactSource | null>(null), chunks = ref<Page<Chunk> | null>(null), location = ref<SourceLocation | null>(null);
const base = () => `projects/${props.project.id}/`;
const dirty = computed(() => props.project.role === 'author' && (!!note.value || !!dirtyItems.value.size));
const material = computed(() => materials.value.find(m => m.id === materialId.value));
const oldVersion = computed(() => versions.value.find(v => v.id === oldId.value));
const newVersion = computed(() => versions.value.find(v => v.id === newId.value));
let mounted = true, changeKey = crypto.randomUUID(), scanKey = crypto.randomUUID(), modelKey = crypto.randomUUID(), timer: ReturnType<typeof setTimeout> | undefined;
watch([oldId, newId, kind, note, confirmed], () => { changeKey = crypto.randomUUID(); });
watch([run, blocks], () => { modelKey = crypto.randomUUID(); }, { deep: true });
watch(dirty, value => emit('dirtyChange', value));
function itemDirty(id: string, value: boolean) { const next = new Set(dirtyItems.value); if (value) next.add(id); else next.delete(id); dirtyItems.value = next; }
async function maySwitch() { return !dirtyItems.value.size || (await confirmDiscard("放弃此清单中尚未保存的处理说明？")); }
function accessLost(cause: ApiError) { records.value = null; selected.value = null; runs.value = null; run.value = null; items.value = null; materials.value = []; versions.value = []; manuscript.value = null; reading.value = null; chunks.value = null; location.value = null; job.value = null; jobs.value = null; note.value = ''; emit('accessLost', cause); }
async function perform(action: () => Promise<void>) { if (busy.value || !mounted) return; busy.value = true; error.value = ''; message.value = ''; try { await action(); } catch (cause) { if (!mounted) return; error.value = cause instanceof Error ? cause.message : '操作失败，请重试。'; if (cause instanceof ApiError && [401,403,404].includes(cause.status)) accessLost(cause); } finally { if (mounted) busy.value = false; } }
async function all<T>(suffix: string) { const result: T[] = []; for (let page = 1; mounted; page++) { const value = await request<Page<T>>(`${base()}${suffix}?page=${page}`); result.push(...value.results); if (!value.next) break; } return result; }
async function loadVersions() { oldId.value = ''; newId.value = ''; confirmed.value = false; versions.value = materialId.value ? await all<Version>(`materials/${materialId.value}/versions/`) : []; }
async function loadRecords(page = recordPage.value) { const value = await request<Page<MaterialChange>>(`${base()}material-changes/?page=${page}`); if (mounted) { records.value = value; recordPage.value = page; } }
async function loadRuns(page = 1) { const value = await request<Page<ImpactRun>>(`${base()}material-changes/${selected.value!.id}/runs/?page=${page}`); if (mounted) { runs.value = value; runPage.value = page; } }
async function loadItems(page = 1) { const value = await request<Page<ImpactItem>>(`${base()}impact-runs/${run.value!.id}/items/?page=${page}`); if (mounted) { items.value = value; itemPage.value = page; } }
async function loadJobs(page = 1) { const value = await request<Page<Job>>(`${base()}impact-runs/${run.value!.id}/model/?page=${page}`); if (mounted) { jobs.value = value; jobPage.value = page; } }
async function openRun(value: ImpactRun) { if (!(await maySwitch())) return; run.value = value; items.value = null; job.value = null; blocks.value = []; manuscript.value = await request<Manuscript>(`${base()}manuscript/`); await loadItems(); await loadJobs(); job.value = jobs.value?.results[0] ?? null; }
async function open(value: MaterialChange) { if (!(await maySwitch())) return; selected.value = await request<MaterialChange>(`${base()}material-changes/${value.id}/`); scanKey = crypto.randomUUID(); run.value = null; items.value = null; job.value = null; reading.value = null; chunks.value = null; location.value = null; await loadRuns(); if (runs.value?.results[0]) await openRun(runs.value.results[0]); }
async function refresh() { materials.value = await all<Material>('materials/'); if (materialId.value) versions.value = await all<Version>(`materials/${materialId.value}/versions/`); confirmed.value = false; await loadRecords(); if (selected.value) { selected.value = await request<MaterialChange>(`${base()}material-changes/${selected.value.id}/`); reading.value = null; chunks.value = null; location.value = null; await loadRuns(runPage.value); if (run.value) { run.value = await request<ImpactRun>(`${base()}impact-runs/${run.value.id}/`); await loadItems(itemPage.value); await loadJobs(jobPage.value); } } }
async function recordChange() { if (!material.value || !oldVersion.value) throw new Error('请选择材料及旧版。'); const value = await request<MaterialChange>(`${base()}material-changes/`, 'POST', { request_key: changeKey, source_version_id: oldId.value, replacement_id: kind.value === 'withdrawal' ? null : newId.value || null, kind: kind.value, note: note.value, confirmed: confirmed.value, state_version: material.value.state_version, usage_version: oldVersion.value.usage_version, replacement_usage_version: kind.value === 'withdrawal' ? null : newVersion.value?.usage_version ?? null }); note.value = ''; confirmed.value = false; await refresh(); await open(value); message.value = '材料变更已记录。'; }
async function scan() { if (!(await maySwitch())) return; const value = await request<ImpactRun>(`${base()}material-changes/${selected.value!.id}/runs/`, 'POST', { request_key: scanKey, sources_token: selected.value!.sources_token }); scanKey = crypto.randomUUID(); await loadRuns(); await openRun(value); }
async function model() { job.value = await request<Job>(`${base()}impact-runs/${run.value!.id}/model/`, 'POST', { idempotency_key: modelKey, policy_version: props.project.policy.version, block_ids: blocks.value }); await loadJobs(); }
async function control(action: 'cancel' | 'retry') { job.value = await request<Job>(`${base()}jobs/${job.value!.id}/${action}/`, 'POST', { generation: job.value!.generation, policy_version: props.project.policy.version }); }
async function poll() { if (!mounted) return; if (job.value && ['queued','running'].includes(job.value.status)) await perform(async () => { const value = await request<Job>(`${base()}jobs/${job.value!.id}/`); if (mounted) { job.value = value; if (value.status === 'succeeded' && run.value) { run.value = await request<ImpactRun>(`${base()}impact-runs/${run.value.id}/`); await loadItems(itemPage.value); await loadJobs(jobPage.value); } } }); if (mounted) timer = setTimeout(poll, 2000); }
async function readSource(source: ImpactSource, page = 1) { if (!source.parse_id) throw new Error('此版本尚无成功解析，请在材料区解析后刷新。'); const value = await request<Page<Chunk>>(`${base()}parses/${source.parse_id}/chunks/?page=${page}`); if (mounted) { reading.value = source; chunks.value = value; location.value = null; chunkPage.value = page; } }
async function locate(chunk: Chunk) { const value = await request<SourceLocation>(`${base()}chunks/${chunk.id}/`); if (mounted) location.value = value; }
function saved(value: ImpactItem) { if (items.value) items.value.results = items.value.results.map(i => i.id === value.id ? value : i); }
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value) { event.preventDefault(); event.returnValue = ''; } }
onMounted(async () => { window.addEventListener('beforeunload', beforeUnload); await perform(refresh); void poll(); });
onUnmounted(() => { mounted = false; clearTimeout(timer); window.removeEventListener('beforeunload', beforeUnload); emit('dirtyChange', false); });
</script>
<template>
  <section aria-label="材料变更与影响" :aria-busy="busy"><h2>材料变更与影响</h2>
    <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert><p v-if="message" role="status">{{ message }}</p><p v-if="busy" role="status">处理中…</p><NButton @click="perform(refresh)" :disabled="(busy)">刷新变更区</NButton>
    <UiDisclosure v-if="project.role === 'author'"><template #header>登记材料变更</template><form class="editor" @submit.prevent="perform(recordChange)"><fieldset :disabled="busy">
      <label>变更材料<UiSelect v-model="materialId" aria-label="变更材料" @change="perform(loadVersions)" :disabled="(busy)" :options="[({ value: '', label: '选择材料' }), ...(materials ?? []).map((m) => ({ value: m.id, label: String(m.title), disabled: m.access_state !== 'active' }))]" /></label>
      <label>变更类型<UiSelect v-model="kind" aria-label="变更类型" :disabled="(busy)" :options="[...Object.entries(changeLabels).map(([value, label]) => ({ value: value, label: String(label) }))]" /></label>
      <label>旧文件版本<UiSelect v-model="oldId" aria-label="旧文件版本" required :disabled="(busy)" :options="[({ value: '', label: '选择旧版' }), ...(versions ?? []).map((v) => ({ value: v.id, label: 'v' + String(v.number) + ' · ' + String(v.file_name) + ' · ' + String(usageLabels[v.usage_state]), disabled: v.status !== 'available' || v.usage_state === 'withdrawn' || (kind !== 'withdrawal' && v.usage_state !== 'active') }))]" /></label>
      <label v-if="kind !== 'withdrawal'">新文件版本<UiSelect v-model="newId" aria-label="新文件版本" required :disabled="(busy)" :options="[({ value: '', label: '选择已上传的新版' }), ...(versions ?? []).map((v) => ({ value: v.id, label: 'v' + String(v.number) + ' · ' + String(v.file_name), disabled: v.status !== 'available' || v.usage_state !== 'active' || v.number <= (oldVersion?.number ?? 0) }))]" /></label>
      <label>变更说明<UiInput v-model="note" rows="2" maxlength="2000" required :disabled="(busy)" type="textarea" :aria-label="'变更说明'" /></label><p>{{ kind === 'supplement' ? '补充保留旧版有效状态。' : kind === 'correction' ? '更正后旧版只供历史对照，不再用于新建议或旧建议采纳。' : '撤回后此版本停止用于检索和模型任务。' }}</p>
      <UiCheckbox v-model="confirmed" :disabled="(busy)" :aria-label="'我已核对文件版本、变更类型与说明'" class="inline">我已核对文件版本、变更类型与说明</UiCheckbox><NButton :disabled="(busy) || (!confirmed)" attr-type="submit">保存材料变更</NButton>
    </fieldset></form></UiDisclosure>
    <p v-if="records?.count === 0">暂无已登记的材料变更。上传新版后可在此说明它与旧版的关系。</p>
    <NButton v-for="record in records?.results" :key="record.id" @click="perform(() => open(record))" :disabled="(busy)">{{ record.sources.old.title }} v{{ record.sources.old.number }} · {{ changeLabels[record.kind] }}</NButton>
    <div v-if="records && (records.previous || records.next)"><NButton @click="perform(() => loadRecords(recordPage - 1))" :disabled="(busy || !records.previous)">上一页变更</NButton><NButton @click="perform(() => loadRecords(recordPage + 1))" :disabled="(busy || !records.next)">下一页变更</NButton></div>
    <section v-if="selected" aria-label="所选材料变更"><h3>{{ changeLabels[selected.kind] }} · {{ selected.sources.old.title }}</h3><p>{{ selected.note }}</p>
      <p>旧版 v{{ selected.sources.old.number }}：{{ usageLabels[selected.sources.old.usage_state] }}{{ selected.sources.old.access_state === 'withdrawn' ? ' · 整个材料已撤回' : '' }}<NButton @click="perform(() => readSource(selected!.sources.old))" :disabled="(busy || selected.sources.old.access_state !== 'active' || selected.sources.old.usage_state === 'withdrawn')">查看旧材料</NButton></p>
      <p v-if="selected.sources.new">新版 v{{ selected.sources.new.number }}：{{ usageLabels[selected.sources.new.usage_state] }}<NButton @click="perform(() => readSource(selected!.sources.new!))" :disabled="(busy || selected.sources.new.access_state !== 'active' || selected.sources.new.usage_state === 'withdrawn')">查看新材料</NButton></p>
      <div v-if="reading"><h4>{{ reading.file_name }} v{{ reading.number }}</h4><NButton v-for="chunk in chunks?.results" :key="chunk.id" @click="perform(() => locate(chunk))" :disabled="(busy)">片段 {{ chunk.ordinal }}：{{ chunk.text.slice(0, 90) }}</NButton><p v-if="chunks?.count === 0">此解析没有可读片段。</p><div v-if="chunks && (chunks.previous || chunks.next)"><NButton @click="perform(() => readSource(reading!, chunkPage - 1))" :disabled="(busy || !chunks.previous)">上一页材料片段</NButton><NButton @click="perform(() => readSource(reading!, chunkPage + 1))" :disabled="(busy || !chunks.next)">下一页材料片段</NButton></div><SourceContext v-if="location" :project="project" :location="location" /></div>
      <NButton v-if="project.role === 'author'" @click="perform(scan)" :disabled="(busy)">{{ runs?.count ? '复查已登记依赖' : '生成影响清单' }}</NButton><p v-if="runs?.count === 0">尚未生成影响清单。</p>
      <NButton v-for="r in runs?.results" :key="r.id" @click="perform(() => openRun(r))" :disabled="(busy)">第 {{ r.number }} 轮 · 已登记 {{ r.counts.registered }} 处 · 模型候选 {{ r.counts.model }} 处</NButton>
      <div v-if="runs && (runs.previous || runs.next)"><NButton @click="perform(() => loadRuns(runPage - 1))" :disabled="(busy || !runs.previous)">上一页复查</NButton><NButton @click="perform(() => loadRuns(runPage + 1))" :disabled="(busy || !runs.next)">下一页复查</NButton></div>
      <template v-if="run"><h3>第 {{ run.number }} 轮影响清单 · 原稿 v{{ run.manuscript_version ?? 0 }}</h3><p v-if="run.sources_changed" role="status">材料状态已有变化，请刷新并重新复查。</p>
        <p v-if="run.comparison">与第 {{ run.comparison.previous_number }} 轮相比：仍有登记 {{ run.comparison.remaining }} 处，新增 {{ run.comparison.new }} 处，已不在当前稿件登记中 {{ run.comparison.no_longer_registered }} 处。登记消失不代表论点已核对正确。</p>
        <p v-if="items?.count === 0">此轮未找到已登记依赖或模型候选，不代表没有隐含影响。</p>
        <ImpactItemCard v-for="item in items?.results" :key="item.id" :project="project" :item="item" @saved="saved" @dirty-change="itemDirty" @access-lost="accessLost" />
        <div v-if="items && (items.previous || items.next)"><NButton @click="perform(async () => { if (await maySwitch()) await loadItems(itemPage - 1); })" :disabled="(busy || !items.previous)">上一页影响项</NButton><NButton @click="perform(async () => { if (await maySwitch()) await loadItems(itemPage + 1); })" :disabled="(busy || !items.next)">下一页影响项</NButton></div>
        <UiDisclosure v-if="project.role === 'author'"><template #header>模型补查可能相关位置</template><p>最多 20 个正文块、6000 字符；新旧材料各最多 4000 字符。结果仅为补充候选。</p><UiCheckbox v-model="blocks" :value="block.id" :disabled="(busy || manuscript?.version !== run.manuscript_version)" :aria-label="'块 ' + String(index + 1) + '：' + String(block.text.slice(0, 60))" v-for="(block, index) in manuscript?.blocks" :key="block.id" class="inline">块 {{ index + 1 }}：{{ block.text.slice(0, 60) }}</UiCheckbox><NButton @click="perform(model)" :disabled="(busy || !blocks.length || run.sources_changed || !project.policy.allowed_actions.includes('review'))">发起影响补查</NButton></UiDisclosure>
        <div v-if="job" role="status">{{ statusLabels[job.status] }}<p>{{ job.error_message || job.output?.summary }}</p><NButton v-if="project.role === 'author' && ['queued','running'].includes(job.status)" @click="perform(() => control('cancel'))" :disabled="(busy)">取消补查</NButton><NButton v-if="project.role === 'author' && job.status === 'failed' && job.retryable" @click="perform(() => control('retry'))" :disabled="(busy)">重试补查</NButton></div>
        <UiDisclosure v-if="jobs?.count"><template #header>补查任务记录</template><NButton v-for="j in jobs.results" :key="j.id" @click="job = j" :disabled="(busy)">{{ statusLabels[j.status] }} · {{ j.id.slice(0, 8) }}</NButton><NButton v-if="jobs.previous" @click="perform(() => loadJobs(jobPage - 1))" :disabled="(busy)">上一页补查</NButton><NButton v-if="jobs.next" @click="perform(() => loadJobs(jobPage + 1))" :disabled="(busy)">下一页补查</NButton></UiDisclosure>
      </template>
    </section>
  </section>
</template>
<style scoped>button { white-space: normal; overflow-wrap: anywhere; max-width: 100%; } fieldset { min-width: 0; } select { max-width: 100%; } .inline { overflow-wrap: anywhere; }.inline { display: flex; align-items: center; gap: .5rem; } .inline input { width: auto; margin: 0; flex-shrink: 0; }</style>
