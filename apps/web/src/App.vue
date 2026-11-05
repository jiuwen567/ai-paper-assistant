<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { fetchHealth, serviceNames, type Health, type Service } from "./api";

const health = ref<Health | null>(null);
const loading = ref(false);
const error = ref("");
const checkedAt = ref("尚未检查");
const isWechat = window.location.pathname === "/wechat";
const state = computed(() =>
  loading.value
    ? "正在检查服务"
    : error.value
      ? "API 连接失败"
      : health.value?.status === "ok"
        ? "本地服务已就绪"
        : "等待服务就绪",
);
const services = Object.entries(serviceNames) as [Service, string][];

function serviceStatus(key: Service) {
  if (loading.value) return "检查中";
  if (!health.value) return "未连接";
  return health.value.checks[key] === "ok" ? "已就绪" : "不可用";
}
async function refresh() {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  health.value = null;
  try {
    health.value = await fetchHealth();
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "连接失败，请稍后重试。";
  } finally {
    loading.value = false;
    checkedAt.value = new Date().toLocaleTimeString("zh-CN");
  }
}
onMounted(refresh);
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <a class="brand" href="/">Paper Assistant</a>
      <nav aria-label="主导航">
        <a href="/" :aria-current="!isWechat ? 'page' : undefined">环境概览</a>
        <a href="/wechat" :aria-current="isWechat ? 'page' : undefined">微信接入</a>
        <a href="https://github.com/jiuwen567/ai-paper-assistant/blob/main/docs/development.md">开发文档</a>
      </nav>
    </aside>
    <main>
      <h1>{{ isWechat ? "微信接入" : "本地开发环境" }}</h1>
      <section class="status-panel" aria-live="polite">
        <div>
          <h2>{{ state }}</h2>
          <p v-if="error">{{ error }}</p>
          <small>最近检查：{{ checkedAt }}</small>
        </div>
        <button :disabled="loading" @click="refresh">
          {{ loading ? "检查中…" : "重新检查" }}
        </button>
      </section>

      <template v-if="!isWechat">
        <h2>基础服务</h2>
        <dl class="services">
          <div v-for="[key, name] in services" :key="key">
            <dt>{{ name }}</dt>
            <dd :class="{ ready: health?.checks[key] === 'ok' }">{{ serviceStatus(key) }}</dd>
          </div>
        </dl>
        <p class="notice">账号、材料管理、AI 阅读、原稿审阅与导出尚未接入。</p>
      </template>
      <template v-else>
        <h2>微信小程序</h2>
        <p>在微信开发者工具导入 <code>apps/miniapp</code>，配置测试 AppID，点击“检查 API 连接”。</p>
        <p>真机调试需要手机可访问的 HTTPS API，并配置 request 合法域名。</p>
        <h2>公众号</h2>
        <p>当前提供本地 H5 说明页。网页授权、自定义菜单和消息回调尚未接入。</p>
      </template>
    </main>
  </div>
</template>
