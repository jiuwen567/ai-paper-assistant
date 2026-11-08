<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from "vue-router";
import type { ApiError } from "@/api/client";
import WorkspaceLayout from "@/app/components/WorkspaceLayout.vue";
import LoginForm from "@/features/accounts/LoginForm.vue";
import WechatBindingPanel from "@/features/accounts/WechatBindingPanel.vue";
import CleanupPanel from "@/features/cleanup/CleanupPanel.vue";
import AsyncFeedback from "@/ui/AsyncFeedback.vue";
import { useConfirm } from "@/ui/confirm";
import ProjectList from "./ProjectList.vue";
import ProjectForm from "./ProjectForm.vue";
import ProjectWorkspace from "./ProjectWorkspace.vue";
import { useProjects } from "./useProjects";
import type { Project } from "./types";

const route = useRoute(),
  router = useRouter();
const confirmDiscard = useConfirm();
const {
  user,
  initialized,
  busy,
  error,
  message,
  projects,
  projectPage,
  selected,
  perform,
  initialize,
  signIn,
  signOut,
  loadProjects,
  loadProject,
  accessLost,
} = useProjects(async () => {
  hasDraft.value = creatingDirty.value = false;
  await router.replace("/");
});
const hasDraft = ref(false),
  creatingDirty = ref(false),
  cleanupBusy = ref(false);
const workspace = computed(() => String(route.params.workspace || "overview"));
const tab = computed(() => (route.query.tab ? String(route.query.tab) : undefined));
const creating = computed(() => route.name === "project-new");
const projectId = computed(() =>
  route.params.projectId ? String(route.params.projectId) : undefined,
);
const disabled = computed(() => busy.value || cleanupBusy.value);

watch(
  [projectId, initialized, () => user.value?.id],
  async ([id, ready, account]) => {
    if (!ready || !account) return;
    hasDraft.value = false;
    await loadProject(id);
  },
  { immediate: true },
);
async function canLeave(prompt = "放弃当前未保存修改并离开项目？") {
  if (cleanupBusy.value) return false;
  return (
    !(hasDraft.value || creatingDirty.value) ||
    (await confirmDiscard(prompt))
  );
}
onBeforeRouteLeave(() => canLeave());
onBeforeRouteUpdate(async (to) => {
  if (cleanupBusy.value) return false;
  if (
    to.params.projectId !== route.params.projectId ||
    (route.name === "project-new" && to.name !== route.name)
  ) {
    return canLeave();
  }
});
function navigate(key: string, targetTab?: string) {
  if (!selected.value || disabled.value) return;
  void router.push({
    name: "project",
    params: { projectId: selected.value.id, workspace: key },
    query: targetTab ? { tab: targetTab } : {},
  });
}
async function saved(project: Project) {
  const created = creating.value;
  if (created) {
    creatingDirty.value = false;
    await router.push({
      name: "project",
      params: { projectId: project.id, workspace: "settings" },
    });
  } else {
    selected.value = project;
  }
  await perform(loadProjects);
  if (created && selected.value?.id === project.id) message.value = "项目已保存。";
}
async function reload() {
  if (await canLeave()) {
    hasDraft.value = false;
    await loadProject(projectId.value);
  }
}
async function lost(cause: ApiError) {
  await accessLost(cause);
}
async function leaveSession() {
  if (!(await canLeave("仍有未保存修改，确认退出？"))) return;
  if (await perform(signOut)) {
    hasDraft.value = creatingDirty.value = false;
    await router.replace("/");
  }
}
async function afterCleanup(scope: string, id: string) {
  hasDraft.value = false;
  if (selected.value?.id === id) {
    selected.value = null;
    await nextTick();
    if (scope === "material") await loadProject(id);
    else await router.replace("/");
  }
  await perform(loadProjects);
}
onMounted(() => perform(initialize));
</script>
<template>
  <WorkspaceLayout
    :selected="selected"
    :user="user"
    :workspace="workspace"
    :creating="creating"
    :busy="disabled"
    @navigate="navigate"
    @back="router.push('/')"
    @logout="leaveSession"
  >
    <AsyncFeedback :busy="busy" :error="error" :message="message" />
    <NButton v-if="!initialized" :disabled="disabled" @click="perform(initialize)"
      >重新连接</NButton
    >
    <LoginForm
      v-else-if="!user"
      :busy="disabled"
      @submit="(credentials) => perform(() => signIn(credentials))"
    />
    <ProjectForm
      v-else-if="creating"
      :disabled="disabled"
      @saved="saved"
      @access-lost="lost"
      @dirty-change="creatingDirty = $event"
    />
    <ProjectWorkspace
      v-else-if="selected"
      :key="selected.id"
      :project="selected"
      :user-id="user!.id"
      :workspace="workspace"
      :tab="tab"
      :disabled="cleanupBusy"
      @navigate="navigate"
      @saved="saved"
      @access-lost="lost"
      @dirty-change="hasDraft = $event"
      @reload="reload"
      @back="router.push('/')"
    />
    <NButton v-else-if="projectId && user" :disabled="disabled" @click="loadProject(projectId)"
      >重新加载项目</NButton
    >
    <ProjectList
      v-else-if="user"
      :projects="projects"
      :project-page="projectPage"
      :busy="disabled"
      @create="router.push({ name: 'project-new' })"
      @refresh="perform(loadProjects)"
      @page="(page) => perform(() => loadProjects(page))"
      @open="
        (id) => router.push({ name: 'project', params: { projectId: id, workspace: 'overview' } })
      "
    />
    <div v-show="!selected || workspace === 'settings'" class="account-settings">
      <WechatBindingPanel v-if="user" :key="user.id" @access-lost="lost" />
      <CleanupPanel
        v-if="user && !creating"
        :key="user.id"
        :project="selected"
        :disabled="busy"
        :has-draft="hasDraft"
        @deleting="cleanupBusy = $event"
        @deleted="afterCleanup"
        @access-lost="lost"
      />
    </div>
  </WorkspaceLayout>
</template>
