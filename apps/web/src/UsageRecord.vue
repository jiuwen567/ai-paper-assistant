<script setup lang="ts">
import { onUnmounted, ref } from "vue";
import { ApiError, request, type Project } from "./projects-api";
import { purposeLabels, statusLabels, type Usage } from "./disclosure";
import { decisionLabels, type Suggestion } from "./expression";
import type { Manuscript } from "./manuscript";
import { progressLabels, type Feedback, type FeedbackTask } from "./feedback";
import { readingFields, type ReadingRecord } from "./reading";
import { decisionLabels as reviewDecisions, type ReviewFinding, type ReviewRecord } from "./review";
import type { SourceLocation } from "./sources";
import SourceContext from "./SourceContext.vue";
import TextChanges from "./TextChanges.vue";
const props = defineProps<{ project: Project; usage: Usage }>();
const emit = defineEmits<{ accessLost: [error: ApiError] }>();
const detail = ref<Usage | null>(null), suggestion = ref<Suggestion | null>(null), manuscript = ref<Manuscript | null>(null);
const location = ref<SourceLocation | null>(null), output = ref<string[]>([]), busy = ref(false), error = ref("");
let mounted = true;
const base = () => `projects/${props.project.id}/`;
async function perform(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { await action(); }
  catch (cause) {
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "读取失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      detail.value = null; suggestion.value = null; manuscript.value = null; location.value = null; output.value = [];
      emit("accessLost", cause);
    }
  } finally { if (mounted) busy.value = false; }
}
async function load() { const value = await request<Usage>(`${base()}usage/${props.usage.id}/`); if (mounted) detail.value = value; }
async function loadSuggestion(id: string) { const value = await request<Suggestion>(`${base()}suggestions/${id}/`); if (mounted) { suggestion.value = value; manuscript.value = null; } }
async function loadManuscript(number: number) { const value = await request<Manuscript>(`${base()}manuscript/history/${number}/`); if (mounted) manuscript.value = value; }
async function loadSource(id: string) { const value = await request<SourceLocation>(`${base()}chunks/${id}/`); if (mounted) location.value = value; }
async function loadReading(id: string) {
  const value = await request<ReadingRecord>(`${base()}reading/${id}/`);
  if (mounted) output.value = value.model_output.documents.flatMap(document => [document.title || document.file_name, ...Object.entries(readingFields).map(([field, label]) => `${label}：${document.fields[field as keyof typeof readingFields].text}`), ...(value.author_revision ? [`作者修订 v${value.author_revision.number}：${value.author_revision.note}`, ...value.author_revision.edits.map(edit => `${readingFields[edit.field]}：${edit.text}`)] : [])]);
  if (mounted && value.model_output.comparison) output.value.push(`比较说明：${value.model_output.comparison.reason}`);
}
async function loadReview(id: string) { const value = await request<ReviewRecord>(`${base()}reviews/${id}/`); if (mounted) output.value = [value.summary]; }
async function loadFeedback(id: string) { const value = await request<Feedback>(`${base()}feedback/${id}/`); if (mounted) output.value = ["原始意见（作者转录）", value.text, value.source_label]; }
async function loadFeedbackTask(id: string) { const value = await request<FeedbackTask>(`${base()}feedback-tasks/${id}/`); if (mounted) output.value = [value.current.title, value.current.instruction, `作者进度：${progressLabels[value.current.status]}`, value.current.note, ...(value.original_location ? [`初始原稿 v${value.original_location.manuscript_version}：${value.original_location.text}`] : []), ...(value.current.location ? [`处理原稿 v${value.current.location.manuscript_version}：${value.current.location.text}`] : [])]; }
async function loadFinding(id: string) {
  const value = await request<ReviewFinding>(`${base()}review-findings/${id}/`);
  if (mounted) output.value = [`原稿 v${value.manuscript_version}：${value.model_output.quote}`, value.model_output.reason, value.model_output.action, `作者判断：${reviewDecisions[value.status]}`, value.author_decision?.reason || ""];
}
async function loadImpact(id: string) { const value = await request<import("./impact").ImpactItem>(`${base()}impact-items/${id}/`); if (mounted) output.value = [value.location?.text || "", value.snapshot.reason || "", value.snapshot.change_quote || "", value.current ? `作者处理：${value.current.note}` : "待作者复核"]; }
async function loadNotes() { const value = await request<{ output: { proposals?: { text: string }[] } }>(`${base()}jobs/${props.usage.id}/`); if (mounted) output.value = (value.output?.proposals || []).map(item => item.text); }
onUnmounted(() => { mounted = false; });
</script>
<template>
  <article class="usage-record" :aria-busy="busy">
    <h3>{{ purposeLabels[usage.purpose] || usage.purpose }} · {{ statusLabels[usage.status] }}</h3>
    <p>{{ new Date(usage.created_at).toLocaleString() }} · {{ usage.model.model || usage.embedding.model_name || '未记录模型名称' }}</p>
    <p>发起调用 {{ usage.calls.length }} 次 · 表达建议 {{ usage.suggestions.length }} 条 · 实际采纳 {{ usage.suggestions.filter(item => item.decision && item.decision.action !== 'rejected').length }} 条</p>
    <button :disabled="busy" @click="perform(load)">查看使用详情</button>
    <p v-if="error" role="alert" class="error">{{ error }}</p><p v-if="busy" role="status">读取中…</p>
    <template v-if="detail">
      <p>执行器 {{ detail.model.runtime || detail.embedding.runtime || '未记录' }} · {{ detail.model.prompt_version || detail.embedding.pipeline_version || '未记录版本' }} · 项目规则 v{{ detail.policy_version }}</p>
      <p v-if="detail.kind === 'index'">本地向量索引任务，未计入生成模型调用；检索时的查询向量不在任务清单内。</p>
      <p>输入范围：<span v-if="detail.kind === 'ai'">{{ detail.input.version_ids.length }} 个文件版本、</span>{{ detail.input.source_count }} 个资料片段<span v-if="detail.input.manuscript_version">，原稿 v{{ detail.input.manuscript_version }} 的块 {{ detail.input.blocks.map(block => block.position).join('、') }}</span>。</p>
      <button v-if="detail.input.manuscript_version" :disabled="busy" @click="perform(() => loadManuscript(detail!.input.manuscript_version!))">查看输入稿件版本</button>
      <details v-if="detail.sources?.length"><summary>输入资料片段</summary><button v-for="(source, index) in detail.sources" :key="source.chunk_id || source.id" :disabled="busy" @click="perform(() => loadSource((source.chunk_id || source.id)!))">片段 {{ index + 1 }}</button></details>
      <ul><li v-for="call in detail.calls" :key="`${call.generation}-${call.number}`">执行代次 {{ call.generation }} · 调用 {{ call.number }} · {{ statusLabels[call.status] }} · {{ call.elapsed_ms === null ? '耗时未知' : `${call.elapsed_ms} ms` }}<p v-if="call.usage">Token：输入 {{ call.usage.input }}，输出 {{ call.usage.output }}，缓存读取 {{ call.usage.cache_read }}，缓存写入 {{ call.usage.cache_write }}</p><p v-else>用量未知</p><p v-if="call.error_code">错误：{{ call.error_code }}</p></li></ul>
      <button v-for="(item, index) in detail.impact_candidates" :key="item.id" :disabled="busy" @click="perform(() => loadImpact(item.id))">回查影响候选 {{ index + 1 }}</button>
      <button v-if="detail.reading" :disabled="busy" @click="perform(() => loadReading(detail!.reading!.id))">回查阅读结果与作者修订</button>
      <button v-if="detail.notes" :disabled="busy" @click="perform(loadNotes)">回查摘记结果</button>
      <button v-if="detail.review" :disabled="busy" @click="perform(() => loadReview(detail!.review!.id))">回查诊断说明</button>
      <button v-if="detail.input.feedback_id" :disabled="busy" @click="perform(() => loadFeedback(detail!.input.feedback_id!))">回查原始反馈</button>
      <p v-if="detail.feedback_candidates.length">反馈候选 {{ detail.feedback_candidates.length }} 条，确认待办不代表正文采纳。</p>
      <template v-for="(item, index) in detail.feedback_candidates" :key="item.id"><button v-if="item.task_id" :disabled="busy" @click="perform(() => loadFeedbackTask(item.task_id!))">回查修改待办 {{ index + 1 }}</button><p v-else>候选 {{ index + 1 }} · {{ item.decision === 'rejected' ? '作者拒绝' : '待作者确认' }}</p></template>
      <button v-for="(finding, index) in detail.review?.findings" :key="finding.id" :disabled="busy" @click="perform(() => loadFinding(finding.id))">回查诊断 {{ index + 1 }}</button>
      <button v-for="(item, index) in detail.suggestions" :key="item.id" :disabled="busy" @click="perform(() => loadSuggestion(item.id))">回查建议 {{ index + 1 }} · {{ item.decision ? decisionLabels[item.decision.action] : '未决定' }}</button>
      <p v-if="!detail.reading && !detail.notes && !detail.review && !detail.suggestions.length && !detail.feedback_candidates.length && !detail.impact_candidates.length && detail.kind === 'ai'">没有发布可回查的输出。</p>
      <div v-if="output.length"><p v-for="(line, index) in output" :key="index" class="source-text">{{ line }}</p></div>
      <section v-if="suggestion" aria-label="使用记录中的表达修改">
        <h4>原建议 · 稿件 v{{ suggestion.manuscript_version }}</h4>
        <TextChanges :parts="suggestion.diff" /><p>{{ suggestion.model_output.reason }}</p>
        <template v-if="suggestion.decision"><p>作者决定：{{ decisionLabels[suggestion.decision.action] }} · {{ new Date(suggestion.decision.created_at).toLocaleString() }}</p><p class="source-text">{{ suggestion.decision.text }}</p><p>{{ suggestion.decision.reason }}</p><p>确认者：{{ suggestion.decision.created_by }} · 规则 v{{ suggestion.decision.policy_version }}</p></template>
        <button :disabled="busy" @click="perform(() => loadManuscript(suggestion!.manuscript_version))">查看修改前稿件</button>
        <button v-if="suggestion.decision?.manuscript_version" :disabled="busy" @click="perform(() => loadManuscript(suggestion!.decision!.manuscript_version!))">查看采纳后稿件</button>
      </section>
      <details v-if="manuscript" open><summary>稿件 v{{ manuscript.version }}</summary><p v-for="(block, index) in manuscript.blocks" :key="block.id" class="source-text">块 {{ index + 1 }}：{{ block.text }}</p></details>
      <SourceContext v-if="location" :key="location.chunk.id" :project="project" :location="location" />
    </template>
  </article>
</template>
