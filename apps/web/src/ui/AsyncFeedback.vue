<script setup lang="ts">
defineProps<{ busy?: boolean; error?: string; message?: string }>();
</script>
<template>
  <NAlert v-if="error" type="error" :show-icon="false" role="alert">{{ error }}</NAlert>
  <p v-if="message" role="status">{{ message }}</p>
  <p v-if="busy" role="status">处理中…</p>
</template>
