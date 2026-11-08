<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import { request, type ApiError } from "@/api/client";
import { useAsyncState } from "@/composables/useAsyncState";
import AsyncFeedback from "@/ui/AsyncFeedback.vue";
import type { Project, ProjectFields } from "./types";
const props = defineProps<{ project?: Project | null; disabled?: boolean }>();
const emit = defineEmits<{
  saved: [project: Project];
  accessLost: [error: ApiError];
  dirtyChange: [dirty: boolean];
}>();
const { busy, error, message, perform, isActive } = useAsyncState((cause) => emit("accessLost", cause));
const creating = computed(() => !props.project);
const canEdit = computed(() => creating.value || props.project?.role === "author");
const fields = reactive<ProjectFields>({
  name: "",
  paper_type: "",
  requirements: "",
  template: "",
});
const baseline = reactive<ProjectFields>({ ...fields });
watch(
  [() => props.project?.id, () => props.project?.name, () => props.project?.paper_type,
   () => props.project?.requirements, () => props.project?.template],
  () => {
    const project = props.project;
    Object.assign(
      fields,
      project
        ? {
            name: project.name,
            paper_type: project.paper_type,
            requirements: project.requirements,
            template: project.template,
          }
        : { name: "", paper_type: "", requirements: "", template: "" },
    );
    Object.assign(baseline, fields);
  },
  { immediate: true },
);
watch(fields, () => emit("dirtyChange", JSON.stringify(fields) !== JSON.stringify(baseline)), {
  deep: true,
});
async function saveProject() {
  const result = await request<Project>(
    props.project ? `projects/${props.project.id}/` : "projects/",
    props.project ? "PATCH" : "POST",
    { ...fields, ...(props.project ? { version: props.project.version } : {}) },
  );
  if (!isActive()) return;
  Object.assign(baseline, fields);
  emit("dirtyChange", false);
  emit("saved", result);
  message.value = "项目已保存。";
}
</script>
<template>
  <AsyncFeedback :busy="busy" :error="error" :message="message" />
  <form class="editor settings-form" @submit.prevent="perform(saveProject)">
    <h2>{{ creating ? "创建项目" : "项目设置" }}</h2>
    <fieldset :disabled="busy || disabled || !canEdit">
      <label
        >项目名称<UiInput
          v-model="fields.name"
          required
          maxlength="120"
          :disabled="busy || disabled || !canEdit"
          :aria-label="'项目名称'"
      /></label>
      <label
        >论文类型<UiInput
          v-model="fields.paper_type"
          maxlength="80"
          :disabled="busy || disabled || !canEdit"
          :aria-label="'论文类型'"
      /></label>
      <label
        >写作要求<UiInput
          v-model="fields.requirements"
          rows="4"
          maxlength="20000"
          :disabled="busy || disabled || !canEdit"
          type="textarea"
          :aria-label="'写作要求'"
      /></label>
      <label
        >模板<UiSelect
          v-model="fields.template"
          :disabled="busy || disabled || !canEdit"
          :options="[
            { value: '', label: '暂不选择' },
            { value: 'department-default', label: '中文论文示例模板（自制）' },
          ]"
          :aria-label="'模板'"
      /></label>
      <NButton
        v-if="canEdit"
        attr-type="submit"
        :disabled="busy || disabled || !canEdit"
        type="primary"
        >{{ creating ? "创建" : "保存项目" }}</NButton
      >
    </fieldset>
  </form>
</template>
