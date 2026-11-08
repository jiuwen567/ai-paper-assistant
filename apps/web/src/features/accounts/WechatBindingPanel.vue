<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ApiError, request } from "@/api/client";
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
  <UiDisclosure class="editor">
    <template #header>微信账号{{ bound ? ' · 已绑定' : '' }}</template>
    <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert>
    <p v-if="busy" role="status">处理中…</p>
    <NButton v-if="bound === null" @click="perform()" :disabled="(busy)">刷新绑定状态</NButton>
    <template v-else-if="bound">
      <p>解绑后小程序登录立即失效，项目资料保留。</p>
      <NButton @click="perform('DELETE')" :disabled="(busy)">解除微信绑定</NButton>
    </template>
    <form v-else @submit.prevent="perform('POST')">
      <label>绑定码<UiInput v-model="code" required pattern="[a-fA-F0-9]{24}" maxlength="24" autocomplete="off" :aria-label="'绑定码'" /></label>
      <p>仅输入自己小程序显示的绑定码。</p>
      <NButton attr-type="submit" :disabled="(busy)" type="primary">确认绑定当前账号</NButton>
    </form>
  </UiDisclosure>
</template>
