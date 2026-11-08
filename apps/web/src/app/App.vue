<script setup lang="ts">
import { NConfigProvider, NDialogProvider, zhCN, dateZhCN } from 'naive-ui';
import { RouterView } from 'vue-router';
import { theme } from '@/ui/theme';
</script>

<template>
  <NConfigProvider :theme-overrides="theme" :locale="zhCN" :date-locale="dateZhCN">
    <NDialogProvider><RouterView /></NDialogProvider>
  </NConfigProvider>
</template>
