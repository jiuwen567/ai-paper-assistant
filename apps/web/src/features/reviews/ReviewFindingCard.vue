<script setup lang="ts">
import { ref, watch } from "vue";
import { ApiError, request } from "@/api/client";
import { type Project } from "@/features/projects/types";
import { decisionLabels, reviewCategories, supportLabels, type ReviewFinding } from "@/features/reviews/types";
import { researchLabels, type Manuscript } from "@/features/manuscripts/types";
import type { SourceLocation } from "@/features/materials/types";
import SourceContext from "@/features/materials/SourceContext.vue";
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
    <UiDisclosure><template #header>查看固定版本原稿</template><p class="plain-text">{{ segment(0, finding.model_output.start) }}<mark>{{ segment(finding.model_output.start, finding.model_output.end) }}</mark>{{ segment(finding.model_output.end) }}</p></UiDisclosure>
    <p>{{ supportLabels[finding.model_output.support] }}</p>
    <p>{{ finding.model_output.reason }}</p>
    <p>建议作者：{{ finding.model_output.action }}</p>
    <UiDisclosure v-if="finding.model_output.citations.length"><template #header>材料原文依据</template><div v-for="(citation, index) in finding.model_output.citations" :key="index"><blockquote>{{ citation.quote }}</blockquote><NButton @click="perform(() => locate(citation.chunk_id))" :disabled="(busy)">回查依据 {{ index + 1 }}</NButton></div></UiDisclosure>
    <div v-for="(citation, index) in finding.model_output.related_blocks" :key="index"><p>相关原稿 v{{ finding.manuscript_version }}</p><blockquote>{{ citation.quote }}</blockquote><NButton @click="perform(() => showRelated(citation.block_version_id))" :disabled="(busy)">查看相关原稿 {{ index + 1 }}</NButton></div>
    <p v-if="relatedText !== null" class="plain-text">{{ relatedText }}</p>
    <div v-for="(evidence, index) in finding.model_output.research_evidence" :key="index"><p>作者{{ researchLabels[evidence.field] }}</p><blockquote>{{ evidence.quote }}</blockquote></div>
    <p v-if="!finding.model_output.citations.length && !finding.model_output.related_blocks.length && !finding.model_output.research_evidence.length">未提供可回查的支持或反驳依据。</p>
    <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert>
    <p v-if="message" role="status">{{ message }}</p>
    <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(save)"><fieldset :disabled="busy">
      <label>作者处理<UiSelect v-model="status" aria-label="作者处理" :disabled="(busy)" :options="[...Object.entries(decisionLabels).map(([value, label]) => ({ value: value, label: String(label), disabled: value === 'confirmed' && inputChanged }))]" /></label>
      <label>处理原因<UiInput v-model="reason" maxlength="2000" rows="2" :required="status === 'ignored'" :disabled="(busy)" type="textarea" :aria-label="'处理原因'" /></label>
      <div class="actions"><NButton attr-type="submit" :disabled="(busy)" type="primary">保存作者判断</NButton><NButton attr-type="button" @click="perform(reload)" :disabled="(busy)">重新加载问题</NButton></div>
    </fieldset></form>
    <p v-else-if="finding.author_decision?.reason">作者原因：{{ finding.author_decision.reason }}</p>
    <SourceContext v-if="location" :key="location.chunk.id" :project="project" :location="location" />
  </article>
</template>
<style scoped>
.finding { border-top: 1px solid var(--border); padding-block: .75rem; }
.plain-text, blockquote { white-space: pre-wrap; overflow-wrap: anywhere; }
blockquote { margin: .75rem 0; padding-left: .75rem; border-left: 3px solid #8b98a6; }
</style>
