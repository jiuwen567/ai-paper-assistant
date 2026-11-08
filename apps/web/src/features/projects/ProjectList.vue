<script setup lang="ts">
import { FolderOpen } from "@lucide/vue";
import type { Page } from "@/api/types";
import type { Project } from "./types";
import { roleName } from "@/app/workspaces";
defineProps<{ projects: Page<Project> | null; projectPage: number; busy: boolean }>();
const emit = defineEmits<{ create: []; refresh: []; open: [id: string]; page: [page: number] }>();
</script>
<template>
  <div class="section-heading">
    <div>
      <h2>我的论文</h2>
      <p class="notice">从资料整理到原稿修订。</p>
    </div>
    <div class="actions">
      <NButton @click="emit('create')" :disabled="busy" type="primary">创建项目</NButton>
      <NButton @click="emit('refresh')" :disabled="busy">刷新列表</NButton>
    </div>
  </div>
  <p v-if="projects?.count === 0">还没有论文项目。</p>
  <ul class="project-list">
    <li v-for="project in projects?.results" :key="project.id">
      <NButton @click="emit('open', project.id)" :disabled="busy">
        <FolderOpen :size="22" :stroke-width="1.5" />
        <div class="project-list-title">
          <strong>{{ project.name }}</strong
          ><small>{{ project.paper_type || "论文项目" }}</small>
        </div>
        <NTag size="small" :bordered="false">{{ roleName(project.role) }}</NTag>
      </NButton>
    </li>
  </ul>
  <div
    v-if="projects && (projects.next || projects.previous)"
    class="actions"
    aria-label="项目分页"
  >
    <NButton @click="emit('page', projectPage - 1)" :disabled="busy || !projects.previous"
      >上一页</NButton
    >
    <span>{{ projectPage }}</span>
    <NButton @click="emit('page', projectPage + 1)" :disabled="busy || !projects.next"
      >下一页</NButton
    >
  </div>
</template>
