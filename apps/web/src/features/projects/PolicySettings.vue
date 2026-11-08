<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { request, type ApiError } from "@/api/client";
import type { Page } from "@/api/types";
import { useAsyncState } from "@/composables/useAsyncState";
import AsyncFeedback from "@/ui/AsyncFeedback.vue";
import { aiActions, type AIAction, type Policy, type Project } from "./types";
const props = defineProps<{ project: Project; disabled?: boolean }>();
const emit = defineEmits<{
  saved: [project: Project];
  accessLost: [error: ApiError];
  dirtyChange: [dirty: boolean];
}>();
const { busy, error, message, perform, isActive } = useAsyncState((cause) => emit("accessLost", cause));
const canEdit = computed(() => props.project.role === "author");
const history = ref<Page<Policy> | null>(null);
const historyPage = ref(1);
const policy = reactive({
  source: "",
  source_version: "",
  notes: "",
  verified: false,
  allowed_actions: [] as AIAction[],
});
let baseline = "";
watch(
  [() => props.project.id, () => props.project.policy.version],
  () => {
    const value = props.project.policy;
    Object.assign(policy, {
      source: value.source,
      source_version: value.source_version,
      notes: value.notes,
      verified: value.verified,
      allowed_actions: [...value.allowed_actions],
    });
    baseline = JSON.stringify(policy);
  },
  { immediate: true },
);
watch(policy, () => emit("dirtyChange", JSON.stringify(policy) !== baseline), { deep: true });
async function loadHistory(page = 1) {
  const result = await request<Page<Policy>>(
    `projects/${props.project.id}/policies/?page=${page}`,
  );
  if (!isActive()) return;
  history.value = result;
  historyPage.value = page;
}
async function savePolicy() {
  const project = await request<Project>(`projects/${props.project.id}/policies/`, "POST", {
    ...policy,
    allowed_actions: policy.verified ? policy.allowed_actions : [],
    version: props.project.version,
  });
  if (!isActive()) return;
  emit("dirtyChange", false);
  emit("saved", project);
  await loadHistory();
  message.value = "规则已保存为新版本。";
}
onMounted(() => perform(loadHistory));
</script>
<template>
  <AsyncFeedback :busy="busy" :error="error" :message="message" />
  <form class="editor" @submit.prevent="perform(savePolicy)">
    <h2>AI 辅助规则 · v{{ project.policy.version }}</h2>
    <fieldset :disabled="busy || disabled || !canEdit">
      <label
        >规则来源<UiInput
          v-model="policy.source"
          maxlength="500"
          :required="policy.verified"
          :disabled="busy || disabled || !canEdit"
          :aria-label="'规则来源'"
      /></label>
      <label
        >来源版本<UiInput
          v-model="policy.source_version"
          maxlength="120"
          :required="policy.verified"
          :disabled="busy || disabled || !canEdit"
          :aria-label="'来源版本'"
      /></label>
      <label
        >使用要求<UiInput
          v-model="policy.notes"
          rows="3"
          maxlength="20000"
          :disabled="busy || disabled || !canEdit"
          type="textarea"
          :aria-label="'使用要求'"
      /></label>
      <UiCheckbox
        v-model="policy.verified"
        @change="policy.allowed_actions = []"
        :disabled="busy || disabled || !canEdit"
        :aria-label="'已核对学校或课程规则'"
        class="check-label"
        >已核对学校或课程规则</UiCheckbox
      >
      <div class="action-options">
        <UiCheckbox
          v-model="policy.allowed_actions"
          :value="action"
          :disabled="busy || disabled || !canEdit || !policy.verified"
          :aria-label="String(label)"
          v-for="(label, action) in aiActions"
          :key="action"
          class="check-label"
          >{{ label }}</UiCheckbox
        >
      </div>
      <p v-if="!policy.verified" class="notice">
        {{ project.policy.verified ? "保存后将关闭 AI 辅助。" : "规则未核对，AI 辅助已关闭。" }}
      </p>
      <NButton
        v-if="canEdit"
        attr-type="submit"
        :disabled="busy || disabled || !canEdit"
        type="primary"
        >保存规则新版本</NButton
      >
    </fieldset>
  </form>
  <section>
    <h2>规则历史</h2>
    <UiDisclosure v-for="item in history?.results" :key="item.id" class="history-item">
      <template #header
        >v{{ item.version }} · {{ item.verified ? "已核对" : "未核对" }} · {{ item.created_by }} ·
        {{ new Date(item.created_at).toLocaleString("zh-CN") }}</template
      >
      <p>来源：{{ item.source || "未填写" }} {{ item.source_version }}</p>
      <p class="preserve-lines">{{ item.notes || "未填写使用要求" }}</p>
      <p>允许：{{ item.allowed_actions.map((action) => aiActions[action]).join("、") || "无" }}</p>
    </UiDisclosure>
    <div v-if="history && (history.next || history.previous)" class="actions" aria-label="规则分页">
      <NButton
        @click="perform(() => loadHistory(historyPage - 1))"
        :disabled="busy || !history.previous"
        >上一页规则</NButton
      >
      <NButton
        @click="perform(() => loadHistory(historyPage + 1))"
        :disabled="busy || !history.next"
        >下一页规则</NButton
      >
    </div>
  </section>
</template>
