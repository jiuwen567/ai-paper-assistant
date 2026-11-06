<script setup lang="ts">
import { NConfigProvider, NDialogProvider, zhCN, dateZhCN } from "naive-ui";
import { theme } from "./ui/theme";
import EnvironmentPage from "./EnvironmentPage.vue";
import ProjectsPage from "./ProjectsPage.vue";
const environment = ["/environment", "/wechat"].includes(window.location.pathname);
</script>

<template>
  <NConfigProvider :theme-overrides="theme" :locale="zhCN" :date-locale="dateZhCN"><NDialogProvider>
  <EnvironmentPage v-if="environment" />
  <ProjectsPage v-else />
  </NDialogProvider></NConfigProvider>
</template>
