<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import { handlingLabels, type ImpactDecision, type ImpactItem } from "./impact";
import type { SourceLocation } from "./sources";
import SourceContext from "./SourceContext.vue";
import type { Suggestion } from "./expression";
import type { FeedbackTask } from "./feedback";
const props = defineProps<{ project: Project; item: ImpactItem }>();
const emit = defineEmits<{ saved: [item: ImpactItem]; accessLost: [error: ApiError]; dirtyChange: [id: string, value: boolean] }>();
const current = ref(props.item), state = ref("pending"), note = ref(""), confirmed = ref(false), busy = ref(false), error = ref(""), message = ref("");
const baseline = ref(""), baselineToken = ref(props.item.facts_token), baselineVersion = ref(props.item.current?.number ?? 0), history = ref<Page<ImpactDecision> | null>(null), historyPage = ref(1);
const source = ref<SourceLocation | null>(null), target = ref<string[]>([]);
let mounted = true, key = crypto.randomUUID();
const dirty = computed(() => props.project.role === "author" && JSON.stringify([state.value, note.value]) !== baseline.value);
const conflict = computed(() => baselineToken.value !== current.value.facts_token || baselineVersion.value !== (current.value.current?.number ?? 0));
const base = () => `projects/${props.project.id}/`;
function reset() { state.value = current.value.current?.state ?? "pending"; note.value = current.value.current?.note ?? ""; baseline.value = JSON.stringify([state.value, note.value]); adopt(); }
function adopt() { baselineToken.value = current.value.facts_token; baselineVersion.value = current.value.current?.number ?? 0; confirmed.value = false; key = crypto.randomUUID(); }
reset();
watch(() => props.item, value => { current.value = value; source.value = null; target.value = []; });
watch([state, note, confirmed], () => { key = crypto.randomUUID(); });
watch(dirty, value => emit("dirtyChange", props.item.id, value));
async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return; busy.value = true; error.value = ""; message.value = "";
  try { await action(); } catch (cause) { if (!mounted) return; error.value = cause instanceof Error ? cause.message : "操作失败，请重试。";
    if (cause instanceof ApiError && [401,403,404].includes(cause.status)) { source.value = null; target.value = []; history.value = null; emit("accessLost", cause); }
  } finally { if (mounted) busy.value = false; }
}
async function refresh() { const value = await request<ImpactItem>(`${base()}impact-items/${props.item.id}/`); if (mounted) { current.value = value; source.value = null; target.value = []; } }
async function save() { if (conflict.value) throw new Error("请先核对并采用最新状态。"); const value = await request<ImpactItem>(`${base()}impact-items/${props.item.id}/`, "POST", { request_key: key, version: baselineVersion.value, facts_token: baselineToken.value, state: state.value, note: note.value, confirmed: confirmed.value }); if (mounted) { current.value = value; reset(); history.value = null; message.value = "作者处理已记录。"; emit("saved", value); } }
async function loadHistory(page = 1) { const value = await request<Page<ImpactDecision>>(`${base()}impact-items/${props.item.id}/history/?page=${page}`); if (mounted) { history.value = value; historyPage.value = page; } }
async function locate(id: string) { const value = await request<SourceLocation>(`${base()}chunks/${id}/`); if (mounted) source.value = value; }
async function loadTarget() { const snapshot = current.value.snapshot; if (snapshot.task_id) { const value = await request<FeedbackTask>(`${base()}feedback-tasks/${snapshot.task_id}/`); if (mounted) target.value = [value.current.title, value.current.instruction, `任务 v${value.current.number}：${value.current.note}`]; } else if (snapshot.suggestion_id) { const value = await request<Suggestion>(`${base()}suggestions/${snapshot.suggestion_id}/`); if (mounted) target.value = [value.model_output.quote, value.model_output.replacement, value.model_output.reason, value.input_changed ? "输入已变化，不能直接采纳。" : "请在表达建议区核对后处理。", value.decision ? `作者决定：${value.decision.action}` : "待作者决定"]; } }
onUnmounted(() => { mounted = false; emit("dirtyChange", props.item.id, false); });
</script>
<template>
  <article class="impact-item" :aria-busy="busy">
    <h4>{{ current.origin === 'registered' ? '已登记依赖' : '模型补充候选' }} · {{ { paragraph: '正文', suggestion: '表达建议', task: '修改任务' }[current.snapshot.kind] || current.snapshot.kind }}</h4>
    <p v-if="current.location">原稿 v{{ current.location.manuscript_version }} · 块 {{ current.location.position }}{{ current.location.stale ? ' · 原位置已变化' : '' }}</p>
    <blockquote v-if="current.location">{{ current.location.text }}</blockquote><p>{{ current.snapshot.title }}</p><p>{{ current.snapshot.instruction || current.snapshot.reason }}</p>
    <p v-if="current.snapshot.other_evidence?.length">另有 {{ current.snapshot.other_evidence.length }} 条有效来源记录，请复核其支持范围。</p>
    <UiDisclosure v-if="current.snapshot.dependencies?.length"><template #header>登记依据</template><NButton v-for="(dependency, index) in current.snapshot.dependencies" :key="dependency.record_id" @click="perform(() => locate(dependency.chunk_id))" :disabled="(busy)">回查依赖 {{ index + 1 }} · {{ dependency.kind.startsWith('author_') ? '作者登记关系' : '正文引用' }}</NButton></UiDisclosure>
    <UiDisclosure v-if="current.snapshot.other_evidence?.length"><template #header>其他有效来源</template><NButton v-for="(dependency, index) in current.snapshot.other_evidence" :key="dependency.record_id" @click="perform(() => locate(dependency.chunk_id))" :disabled="(busy)">回查其他依据 {{ index + 1 }}</NButton></UiDisclosure>
    <template v-if="current.origin === 'model'"><p>补查依据：{{ { old: '旧材料', new: '新材料', note: '作者变更说明' }[current.snapshot.basis || 'note'] }}</p><blockquote>{{ current.snapshot.change_quote }}</blockquote><NButton v-if="current.snapshot.chunk_id" @click="perform(() => locate(current.snapshot.chunk_id!))" :disabled="(busy)">回查模型引用</NButton></template>
    <NButton v-if="current.snapshot.task_id || current.snapshot.suggestion_id" @click="perform(loadTarget)" :disabled="(busy)">查看原记录当前状态</NButton><p v-for="(line, index) in target" :key="index" class="source-text">{{ line }}</p><SourceContext v-if="source" :key="source.chunk.id" :project="project" :location="source" />
    <p>{{ current.needs_review ? '需要作者复核' : handlingLabels[current.current?.state || 'pending'] }}</p><p v-if="current.current">{{ current.current.note }}</p>
    <NButton @click="perform(refresh)" :disabled="(busy)">刷新此项状态</NButton><NButton @click="perform(() => loadHistory())" :disabled="(busy)">处理历史</NButton>
    <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert><p v-if="message" role="status">{{ message }}</p><p v-if="busy" role="status">处理中…</p>
    <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(save)"><fieldset :disabled="busy">
      <p v-if="conflict" role="status">材料、原稿或处理记录已变化，填写内容已保留。<NButton attr-type="button" @click="adopt" :disabled="(busy)">核对后采用最新状态</NButton></p>
      <label>处理结果<UiSelect v-model="state" aria-label="处理结果" :disabled="(busy)" :options="[...Object.entries(handlingLabels).map(([value, label]) => ({ value: value, label: String(label) }))]" /></label>
      <label>处理说明<UiInput v-model="note" rows="2" maxlength="2000" required :disabled="(busy)" type="textarea" :aria-label="'处理说明'" /></label>
      <UiCheckbox v-model="confirmed" :disabled="(busy) || (conflict)" :aria-label="'我已核对材料、当前位置与处理结果'" class="inline">我已核对材料、当前位置与处理结果</UiCheckbox><NButton attr-type="submit" :disabled="(busy) || (!confirmed || conflict)" type="primary">记录作者处理</NButton>
    </fieldset></form>
    <ol v-if="history"><li v-for="decision in history.results" :key="decision.number">v{{ decision.number }} · {{ handlingLabels[decision.state] }} · 确认者 {{ decision.created_by }}<p>{{ decision.note }}</p><time>{{ new Date(decision.created_at).toLocaleString() }}</time></li></ol>
    <div v-if="history && (history.next || history.previous)"><NButton @click="perform(() => loadHistory(historyPage - 1))" :disabled="(busy || !history.previous)">上一页处理历史</NButton><NButton @click="perform(() => loadHistory(historyPage + 1))" :disabled="(busy || !history.next)">下一页处理历史</NButton></div>
  </article>
</template>
<style scoped>.impact-item { border-top: 1px solid var(--border, #ddd); padding-block: 1rem; } button { white-space: normal; overflow-wrap: anywhere; max-width: 100%; } blockquote { white-space: pre-wrap; overflow-wrap: anywhere; }.inline { display: flex; align-items: center; gap: .5rem; } .inline input { width: auto; margin: 0; flex-shrink: 0; }</style>
