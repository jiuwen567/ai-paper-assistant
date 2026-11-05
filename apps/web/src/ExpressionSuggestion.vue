<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Project } from "./projects-api";
import { decisionLabels, type DiffPart, type Suggestion } from "./expression";
import type { SourceLocation } from "./sources";
import SourceContext from "./SourceContext.vue";
import TextChanges from "./TextChanges.vue";
const props = defineProps<{ project: Project; suggestion: Suggestion }>();
const emit = defineEmits<{ saved: [suggestion: Suggestion]; accessLost: [error: ApiError] }>();
const editing = ref(false), text = ref(props.suggestion.model_output.replacement), confirmed = ref(false), reason = ref("");
const preview = ref<{ text: string; diff: DiffPart[]; guard_reasons: string[] } | null>(null);
const busy = ref(false), error = ref(""), message = ref(""), location = ref<SourceLocation | null>(null);
let mounted = true, key = crypto.randomUUID();
const base = () => `projects/${props.project.id}/suggestions/${props.suggestion.id}/`;
const allowed = computed(() => props.project.role === "author" && props.project.policy.allowed_actions.includes("expression") && !props.suggestion.input_changed && !props.suggestion.decision && props.suggestion.model_output.kind === "expression");
const segment = (start: number, end?: number) => Array.from(props.suggestion.manuscript_text).slice(start, end).join("");
watch([text, editing, reason, confirmed], () => { key = crypto.randomUUID(); });
watch(text, () => { preview.value = null; confirmed.value = false; });
watch(editing, () => { confirmed.value = false; });
watch(() => props.suggestion, suggestion => { text.value = suggestion.model_output.replacement; editing.value = false; preview.value = null; confirmed.value = false; });
async function perform(action: () => Promise<void>) {
  if (busy.value || !mounted) return;
  busy.value = true; error.value = ""; message.value = "";
  try { await action(); }
  catch (cause) {
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) emit("accessLost", cause);
  } finally { if (mounted) busy.value = false; }
}
async function checkEdit() {
  const value = text.value;
  const result = await request<{ diff: DiffPart[]; guard_reasons: string[] }>(base() + "preview/", "POST", { text: value });
  if (mounted && value === text.value) preview.value = { text: value, ...result };
}
async function decide(action: "accepted" | "edited" | "rejected") {
  const result = await request<Suggestion>(base() + "decision/", "POST", {
    request_key: key, manuscript_version: props.suggestion.manuscript_version, policy_version: props.project.policy.version,
    action, meaning_confirmed: action !== "rejected" && confirmed.value, reason: reason.value,
    ...(action === "edited" ? { text: text.value } : {}),
  });
  if (!mounted) return;
  emit("saved", result);
  message.value = result.decision?.manuscript_version ? `已保存原稿 v${result.decision.manuscript_version}，可加载最新原稿查看。` : "已拒绝，原稿未修改。";
}
async function reload() { const result = await request<Suggestion>(base()); if (mounted) emit("saved", result); }
async function locate(id: string) { const result = await request<SourceLocation>(`projects/${props.project.id}/chunks/${id}/`); if (mounted) location.value = result; }
onUnmounted(() => { mounted = false; });
</script>
<template>
  <article :aria-label="`表达建议：${suggestion.model_output.quote}`" class="suggestion">
    <h3>原稿 v{{ suggestion.manuscript_version }} · {{ suggestion.decision ? decisionLabels[suggestion.decision.action] : '待审阅' }}</h3>
    <h4>原句</h4><blockquote>{{ suggestion.model_output.quote }}</blockquote>
    <details><summary>查看固定版本原稿</summary><p class="plain-text">{{ segment(0, suggestion.model_output.start) }}<mark>{{ segment(suggestion.model_output.start, suggestion.model_output.end) }}</mark>{{ segment(suggestion.model_output.end) }}</p></details>
    <template v-if="suggestion.model_output.kind === 'expression'"><h4>建议</h4><p class="plain-text">{{ suggestion.model_output.replacement }}</p><TextChanges :parts="suggestion.diff" /></template>
    <p>{{ suggestion.model_output.reason }}</p>
    <p v-for="guard in suggestion.model_output.guard_reasons" :key="guard" role="status">{{ guard }}</p>
    <details v-if="suggestion.model_output.citations.length"><summary>相关依据</summary><div v-for="(citation, index) in suggestion.model_output.citations" :key="index"><blockquote>{{ citation.quote }}</blockquote><button :disabled="busy" @click="perform(() => locate(citation.chunk_id))">回查表达依据 {{ index + 1 }}</button></div></details>
    <p v-if="suggestion.input_changed && !suggestion.decision" role="status">原稿或依据已变化，旧建议不能覆盖新稿。</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p><p v-if="message" role="status">{{ message }}</p><p v-if="busy" role="status">处理中…</p>
    <div v-if="suggestion.decision"><p v-if="suggestion.decision.manuscript_version">已生成原稿 v{{ suggestion.decision.manuscript_version }}</p><p v-if="suggestion.decision.action === 'edited'" class="plain-text">作者采用：{{ suggestion.decision.text }}</p><p v-if="suggestion.decision.reason">作者原因：{{ suggestion.decision.reason }}</p></div>
    <fieldset v-else-if="project.role === 'author'" :disabled="busy" class="editor">
      <template v-if="allowed">
        <button type="button" @click="editing = !editing">{{ editing ? '取消编辑建议' : '编辑建议' }}</button>
        <template v-if="editing"><label>作者编辑<textarea v-model="text" maxlength="1200" rows="4" /></label><button type="button" @click="perform(checkEdit)">查看编辑差异</button><template v-if="preview"><TextChanges :parts="preview.diff" /><p v-for="guard in preview.guard_reasons" :key="guard" role="status">{{ guard }}</p></template></template>
        <label class="check-label"><input v-model="confirmed" type="checkbox" />已核对原意、数据、条件和依据，确认只是表达修改</label>
      </template>
      <label>决定原因<textarea v-model="reason" maxlength="2000" rows="2" /></label>
      <div class="actions"><button v-if="!editing" type="button" :disabled="!allowed || !confirmed || !!suggestion.model_output.guard_reasons.length" @click="perform(() => decide('accepted'))">接受建议</button><button v-else type="button" :disabled="!allowed || !confirmed || !preview || preview.text !== text || !!preview.guard_reasons.length" @click="perform(() => decide('edited'))">编辑后接受</button><button type="button" @click="perform(() => decide('rejected'))">拒绝建议</button></div>
    </fieldset>
    <button :disabled="busy" @click="perform(reload)">重新加载建议</button>
    <SourceContext v-if="location" :key="location.chunk.id" :project="project" :location="location" />
  </article>
</template>
<style scoped>
.suggestion { border-top: 1px solid #d9e2d2; padding-block: .75rem; }
.plain-text, blockquote { white-space: pre-wrap; overflow-wrap: anywhere; }
blockquote { margin-inline: 0; padding-left: .75rem; border-left: 3px solid #a6b99b; }
</style>
