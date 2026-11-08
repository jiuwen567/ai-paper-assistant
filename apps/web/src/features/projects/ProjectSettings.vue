<script setup lang="ts">
import type { ApiError } from "@/api/client";
import type { Project } from "./types";
import ProjectForm from "./ProjectForm.vue";
import PolicySettings from "./PolicySettings.vue";
import MemberSettings from "./MemberSettings.vue";
defineProps<{ project: Project; disabled: boolean }>();
const emit = defineEmits<{
  saved: [project: Project];
  accessLost: [error: ApiError];
  dirtyChange: [key: string, dirty: boolean];
  reload: [];
  back: [];
}>();
</script>
<template>
  <section class="project-settings">
  <div class="actions">
    <NButton :disabled="disabled" @click="emit('back')">返回列表</NButton>
    <NButton :disabled="disabled" @click="emit('reload')">重新加载</NButton>
  </div>
  <ProjectForm
    :project="project"
    :disabled="disabled"
    @saved="emit('saved', $event)"
    @access-lost="emit('accessLost', $event)"
    @dirty-change="emit('dirtyChange', 'project', $event)"
  />
  <div class="settings-content">
    <PolicySettings
      :project="project"
      :disabled="disabled"
      @saved="emit('saved', $event)"
      @access-lost="emit('accessLost', $event)"
      @dirty-change="emit('dirtyChange', 'policy', $event)"
    />
    <MemberSettings
      :project="project"
      :disabled="disabled"
      @saved="emit('saved', $event)"
      @access-lost="emit('accessLost', $event)"
    />
  </div>
  </section>
</template>
