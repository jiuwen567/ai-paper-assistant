<script setup lang="ts">
import { ref, watch } from "vue";
import { ApiError, request, type Project } from "./projects-api";
import { decisionLabels, reviewCategories, supportLabels, type ReviewFinding } from "./review";
import { researchLabels, type Manuscript } from "./manuscript";
import type { SourceLocation } from "./sources";
import SourceContext from "./SourceContext.vue";
const props = defineProps<{ project: Project; finding: ReviewFinding; inputChanged: boolean }>();
const emit = defineEmits<{ saved: [finding: ReviewFinding]; accessLost: [error: ApiError] }>();
const status = ref(props.finding.status), reason = ref(props.finding.author_decision?.reason ?? "");
const busy = ref(false), error = ref(""), message = ref("");
const location = ref<SourceLocation | null>(null), relatedText = ref<string | null>(null);
watch(() => props.finding, finding => { status.value = finding.status; reason.value = finding.author_decision?.reason ?? ""; });
const base = () => `projects/${props.project.id}/`;
const segment = (start: number, end?: number) => Array.from(props.finding.manuscript_text).slice(start, end).join("");
async function perform(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = ""; message.value = "";
  try { await action(); }
  catch (cause) {
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) emit("accessLost", cause);
  } finally { busy.value = false; }
}
async function save() {
  const result = await request<ReviewFinding>(`${base()}review-findings/${props.finding.id}/`, "PATCH", { version: props.finding.revision, status: status.value, reason: reason.value });
  emit("saved", result); message.value = "作者判断已保存。";
}
async function reload() { emit("saved", await request<ReviewFinding>(`${base()}review-findings/${props.finding.id}/`)); }
async function locate(id: string) { location.value = await request<SourceLocation>(`${base()}chunks/${id}/`); }
async function showRelated(versionId: string) {
  const revision = await request<Manuscript>(`${base()}manuscript/history/${props.finding.manuscript_version}/`);
  relatedText.value = revision.blocks.find(block => block.version_id === versionId)?.text ?? "原稿位置不可用。";
}
</script>
<template>
  <article :aria-label="`问题：${finding.model_output.quote}`" class="finding">
    <h4>{{ reviewCategories[finding.category] }} · {{ decisionLabels[finding.status] }}</h4>
    <p>原稿 v{{ finding.manuscript_version }}</p>
    <blockquote>{{ finding.model_output.quote }}</blockquote>
    <details><summary>查看固定版本原稿</summary><p class="plain-text">{{ segment(0, finding.model_output.start) }}<mark>{{ segment(finding.model_output.start, finding.model_output.end) }}</mark>{{ segment(finding.model_output.end) }}</p></details>
    <p>{{ supportLabels[finding.model_output.support] }}</p>
    <p>{{ finding.model_output.reason }}</p>
    <p>建议作者：{{ finding.model_output.action }}</p>
    <details v-if="finding.model_output.citations.length"><summary>材料原文依据</summary><div v-for="(citation, index) in finding.model_output.citations" :key="index"><blockquote>{{ citation.quote }}</blockquote><button :disabled="busy" @click="perform(() => locate(citation.chunk_id))">回查依据 {{ index + 1 }}</button></div></details>
    <div v-for="(citation, index) in finding.model_output.related_blocks" :key="index"><p>相关原稿 v{{ finding.manuscript_version }}</p><blockquote>{{ citation.quote }}</blockquote><button :disabled="busy" @click="perform(() => showRelated(citation.block_version_id))">查看相关原稿 {{ index + 1 }}</button></div>
    <p v-if="relatedText !== null" class="plain-text">{{ relatedText }}</p>
    <div v-for="(evidence, index) in finding.model_output.research_evidence" :key="index"><p>作者{{ researchLabels[evidence.field] }}</p><blockquote>{{ evidence.quote }}</blockquote></div>
    <p v-if="!finding.model_output.citations.length && !finding.model_output.related_blocks.length && !finding.model_output.research_evidence.length">未提供可回查的支持或反驳依据。</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(save)"><fieldset :disabled="busy">
      <label>作者处理<select v-model="status" aria-label="作者处理"><option v-for="(label, value) in decisionLabels" :key="value" :value="value" :disabled="value === 'confirmed' && inputChanged">{{ label }}</option></select></label>
      <label>处理原因<textarea v-model="reason" maxlength="2000" rows="2" :required="status === 'ignored'" /></label>
      <div class="actions"><button type="submit">保存作者判断</button><button type="button" @click="perform(reload)">重新加载问题</button></div>
    </fieldset></form>
    <p v-else-if="finding.author_decision?.reason">作者原因：{{ finding.author_decision.reason }}</p>
    <SourceContext v-if="location" :key="location.chunk.id" :project="project" :location="location" />
  </article>
</template>
<style scoped>
.finding { border-top: 1px solid #d9e2d2; padding-block: .75rem; }
.plain-text, blockquote { white-space: pre-wrap; overflow-wrap: anywhere; }
blockquote { margin: .75rem 0; padding-left: .75rem; border-left: 3px solid #a6b99b; }
</style>
