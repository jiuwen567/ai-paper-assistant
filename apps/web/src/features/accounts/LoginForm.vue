<script setup lang="ts">
import { ref } from "vue";
import { BookOpen } from "@lucide/vue";
defineProps<{ busy: boolean }>();
const emit = defineEmits<{ submit: [credentials: { username: string; password: string }] }>();
const username = ref("");
const password = ref("");
function submit() {
  emit("submit", { username: username.value, password: password.value });
  password.value = "";
}
</script>
<template>
  <form class="editor login-form" @submit.prevent="submit">
    <BookOpen :size="28" :stroke-width="1.5" />
    <h2>登录论文工作台</h2>
    <p class="notice">继续你的研究与写作。</p>
    <label
      >用户名<UiInput
        v-model="username"
        autocomplete="username"
        required
        maxlength="150"
        aria-label="用户名"
        :disabled="busy"
    /></label>
    <label
      >密码<UiInput
        v-model="password"
        type="password"
        autocomplete="current-password"
        required
        maxlength="1024"
        aria-label="密码"
        :disabled="busy"
    /></label>
    <NButton attr-type="submit" :disabled="busy" type="primary">登录</NButton>
  </form>
</template>
