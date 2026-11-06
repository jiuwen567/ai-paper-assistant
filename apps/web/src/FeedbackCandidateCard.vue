<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Project } from "./projects-api";
import type { FeedbackCandidate } from "./feedback";
const props = defineProps<{ project: Project; candidate: FeedbackCandidate; location: { manuscript_version: number | null; block_id: string | null } }>();
const emit = defineEmits<{ saved: []; accessLost: [error: ApiError]; dirtyChange: [id: string, dirty: boolean] }>();
const title = ref(props.candidate.model_output.title), instruction = ref(props.candidate.model_output.instruction), reason = ref(""), confirmed = ref(false), busy = ref(false), error = ref("");
let key = crypto.randomUUID();
const saved = ref(false);
const dirty = computed(() => !saved.value && !props.candidate.decision && (title.value !== props.candidate.model_output.title || instruction.value !== props.candidate.model_output.instruction || !!reason.value || confirmed.value));
watch(dirty, value => emit("dirtyChange", props.candidate.id, value));
onUnmounted(() => emit("dirtyChange", props.candidate.id, false));
watch([title, instruction, reason, confirmed, () => props.location], () => { key = crypto.randomUUID(); }, { deep: true });
watch([title, instruction], () => { confirmed.value = false; });
async function decide(action: "accepted" | "rejected") {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try {
    await request(`projects/${props.project.id}/feedback-candidates/${props.candidate.id}/decision/`, "POST", { request_key: key, policy_version: props.project.policy.version, title: title.value, instruction: instruction.value, reason: reason.value, confirmed: confirmed.value, action, ...props.location });
    saved.value = true; emit("dirtyChange", props.candidate.id, false); emit("saved");
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "保存失败，请重试。"; if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) emit("accessLost", cause); }
  finally { busy.value = false; }
}
</script>
<template>
  <article :aria-label="`反馈候选：${candidate.model_output.title}`" :aria-busy="busy">
    <h4>{{ candidate.model_output.title }}</h4><blockquote>{{ candidate.model_output.quote }}</blockquote><p>{{ candidate.model_output.instruction }}</p>
    <p v-if="candidate.input_changed">拆分时的原稿或来源已变化，请重新拆分或手动登记核对后的任务。</p>
    <p v-if="candidate.decision">{{ candidate.decision.action === 'accepted' ? '作者已确认并加入待办' : '作者已拒绝' }} · {{ candidate.decision.reason }}</p>
    <form v-else-if="project.role === 'author'" class="editor" @submit.prevent="decide('accepted')"><fieldset :disabled="busy">
      <label>候选任务标题<UiInput v-model="title" required maxlength="200" :disabled="(busy)" :aria-label="'候选任务标题'" /></label><label>候选任务要求<UiInput v-model="instruction" required maxlength="2000" rows="2" :disabled="(busy)" type="textarea" :aria-label="'候选任务要求'" /></label><label>候选决定原因<UiInput v-model="reason" maxlength="2000" rows="2" :disabled="(busy)" type="textarea" :aria-label="'候选决定原因'" /></label>
      <UiCheckbox v-model="confirmed" :disabled="(busy)" :aria-label="'已核对任务与原始意见'" class="check-label">已核对任务与原始意见</UiCheckbox>
      <NButton attr-type="submit" :disabled="(busy) || (!confirmed || candidate.input_changed || !project.policy.allowed_actions.includes('feedback'))" type="primary">确认加入待办</NButton><NButton attr-type="button" @click="decide('rejected')" :disabled="(busy)">拒绝候选</NButton>
    </fieldset></form><p v-if="busy" role="status">保存中…</p><NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert>
  </article>
</template>
