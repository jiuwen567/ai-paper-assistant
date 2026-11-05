<script setup lang="ts">
import EnvironmentPage from "./EnvironmentPage.vue";
import ProjectsPage from "./ProjectsPage.vue";
const environment = ["/environment", "/wechat"].includes(window.location.pathname);
</script>

<template>
  <EnvironmentPage v-if="environment" />
  <ProjectsPage v-else />
</template>
