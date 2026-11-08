<script setup lang="ts">
import { computed, h, ref } from "vue";
import { NMenu, NDrawer, NDrawerContent } from "naive-ui";
import { BookOpen, ArrowLeft, FolderOpen, PanelLeft, LogOut } from "@lucide/vue";
import type { Project } from "@/features/projects/types";
import type { User } from "@/features/accounts/api";
import WorkspaceLauncher from "./WorkspaceLauncher.vue";
import { workspaces, roleName } from "../workspaces";
const props = defineProps<{
  selected: Project | null;
  user: User | null;
  workspace: string;
  creating: boolean;
  busy: boolean;
}>();
const emit = defineEmits<{ navigate: [key: string, tab?: string]; back: []; logout: [] }>();
const mobileMenu = ref(false);
const menuOptions = workspaces.map((item) => ({
  ...item,
  icon: () => h(item.icon, { size: 18, strokeWidth: 1.6 }),
}));
const workspaceTitle = computed(
  () => workspaces.find((item) => item.key === props.workspace)?.label,
);
function menuNodeProps(): { "aria-disabled": "true" | "false" } {
  return { "aria-disabled": props.busy ? "true" : "false" };
}
function navigate(key: string) {
  mobileMenu.value = false;
  emit("navigate", key);
}
function navigateTo(key: string, tab?: string) {
  mobileMenu.value = false;
  emit("navigate", key, tab);
}
</script>
<template>
  <div class="shell">
    <aside class="sidebar desktop-sidebar">
      <a class="brand" href="/"
        ><BookOpen :size="22" :stroke-width="1.6" /><span
          >Paper Assistant<small>论文工作台</small></span
        ></a
      >
      <template v-if="selected">
        <NButton class="project-back" @click="emit('back')" :disabled="busy"
          ><ArrowLeft :size="16" />我的论文</NButton
        >
        <div class="sidebar-project">
          {{ selected.name }}<small>{{ roleName(selected.role) }}</small>
        </div>
        <NMenu
          :value="workspace"
          :options="menuOptions"
          :disabled="busy"
          :node-props="menuNodeProps"
          :indent="16"
          aria-label="工作区导航"
          @update:value="navigate"
        />
      </template>
      <nav v-else aria-label="主导航">
        <a href="/" aria-current="page"><FolderOpen :size="18" />我的论文</a>
      </nav>
      <div class="sidebar-footer">
        <a href="/wechat">微信接入</a><a href="/environment">环境概览</a
        ><span v-if="user">{{ user.username }}</span>
      </div>
    </aside>
    <NDrawer v-model:show="mobileMenu" placement="left" :width="280"
      ><NDrawerContent title="论文工作台" closable
        ><NMenu
          v-if="selected"
          :value="workspace"
          :options="menuOptions"
          :disabled="busy"
          :node-props="menuNodeProps"
          @update:value="navigate"
        /><NButton
          v-if="selected"
          @click="
            mobileMenu = false;
            emit('back');
          "
          >返回列表</NButton
        >
        <nav><a href="/wechat">微信接入</a><a href="/environment">环境概览</a></nav></NDrawerContent
      ></NDrawer
    >
    <main
      :aria-busy="busy"
      :class="{
        'writing-workspace': selected && workspace === 'writing',
        'login-workspace': !user,
      }"
    >
      <header class="page-header">
        <div class="header-title">
          <NButton class="mobile-menu" aria-label="打开导航" @click="mobileMenu = true"
            ><PanelLeft :size="20" /></NButton
          ><span>{{ selected ? selected.name : "我的论文" }}</span
          ><span v-if="selected" class="breadcrumb-divider">/</span>
          <h1>{{ selected ? workspaceTitle : creating ? "创建项目" : "项目" }}</h1>
        </div>
        <div v-if="user" class="actions">
          <WorkspaceLauncher v-if="selected" :disabled="busy" @navigate="navigateTo" /><NTag
            v-if="selected"
            size="small"
            :bordered="false"
            >{{ roleName(selected.role) }}</NTag
          ><NButton @click="emit('logout')" :disabled="busy"><LogOut :size="15" />退出</NButton>
        </div>
      </header>
      <div class="workspace-content">
        <slot />
      </div>
    </main>
  </div>
</template>
