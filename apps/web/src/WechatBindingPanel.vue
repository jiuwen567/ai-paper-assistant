<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ApiError, request } from "./projects-api";
const emit = defineEmits<{ accessLost: [error: ApiError] }>();
const bound = ref<boolean | null>(null);
const code = ref("");
const busy = ref(false);
const error = ref("");
async function perform(method = "GET") {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await request<{ bound: boolean }>("auth/wechat/binding/", method,
      method === "POST" ? { code: code.value.trim() } : undefined);
    bound.value = result.bound;
    code.value = "";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403].includes(cause.status)) emit("accessLost", cause);
  } finally { busy.value = false; }
}
onMounted(() => perform());
</script>

<template>
  <details class="editor">
    <summary>微信账号{{ bound ? ' · 已绑定' : '' }}</summary>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="busy" role="status">处理中…</p>
    <button v-if="bound === null" :disabled="busy" @click="perform()">刷新绑定状态</button>
    <template v-else-if="bound">
      <p>解绑后小程序登录立即失效，项目资料保留。</p>
      <button :disabled="busy" @click="perform('DELETE')">解除微信绑定</button>
    </template>
    <form v-else @submit.prevent="perform('POST')">
      <label>绑定码<input v-model="code" required pattern="[a-fA-F0-9]{24}" maxlength="24" autocomplete="off" /></label>
      <p>仅输入自己小程序显示的绑定码。</p>
      <button :disabled="busy" type="submit">确认绑定当前账号</button>
    </form>
  </details>
</template>
