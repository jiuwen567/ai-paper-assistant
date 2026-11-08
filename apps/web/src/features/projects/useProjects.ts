import { computed, ref } from "vue";
import { request, ApiError } from "@/api/client";
import type { Page } from "@/api/types";
import { session, logout, type User } from "@/features/accounts/api";
import { useAsyncState } from "@/composables/useAsyncState";
import type { Project } from "./types";

export function useProjects(onAccessLost: () => Promise<unknown>) {
  const user = ref<User | null>(null);
  const initialized = ref(false);
  const projects = ref<Page<Project> | null>(null);
  const projectPage = ref(1);
  const selected = ref<Project | null>(null);
  const loading = ref(false);
  let generation = 0;
  const state = useAsyncState(accessLost);
  const busy = computed(() => state.busy.value || loading.value);

  async function loadProjects(page = projectPage.value) {
    const actor = user.value?.id;
    const data = await request<Page<Project>>(`projects/?page=${page}`);
    if (state.isActive() && actor === user.value?.id) {
      projects.value = data;
      projectPage.value = page;
    }
  }
  async function initialize() {
    user.value = (await session()).user;
    if (user.value) await loadProjects();
    initialized.value = true;
  }
  async function signIn(credentials: { username: string; password: string }) {
    user.value = (await session("POST", credentials)).user;
    await loadProjects();
  }
  async function signOut() {
    await logout();
    generation += 1;
    user.value = null;
    selected.value = null;
    projects.value = null;
  }
  async function accessLost(cause: ApiError) {
    generation += 1;
    loading.value = false;
    selected.value = null;
    projects.value = null;
    state.error.value = cause.message;
    try {
      user.value = (await session()).user;
    } catch {
      user.value = null;
    }
    await onAccessLost();
  }
  async function loadProject(id?: string) {
    const current = ++generation;
    if (!id) {
      selected.value = null;
      loading.value = false;
      return;
    }
    if (selected.value?.id !== id) selected.value = null;
    loading.value = true;
    state.error.value = "";
    try {
      const project = await request<Project>(`projects/${id}/`);
      if (current === generation && state.isActive()) selected.value = project;
    } catch (cause) {
      if (current !== generation || !state.isActive()) return;
      state.error.value = cause instanceof Error ? cause.message : "项目加载失败，请重试。";
      if (cause instanceof ApiError && [401, 403, 404].includes(cause.status))
        await accessLost(cause);
    } finally {
      if (current === generation) loading.value = false;
    }
  }
  return {
    ...state,
    busy,
    user,
    initialized,
    projects,
    projectPage,
    selected,
    loadProjects,
    loadProject,
    initialize,
    signIn,
    signOut,
    accessLost,
  };
}
