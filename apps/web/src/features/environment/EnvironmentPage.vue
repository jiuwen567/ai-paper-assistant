<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { fetchHealth, serviceNames, type Health, type Service } from "@/features/environment/api";

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
        <a href="/">我的论文</a>
        <a href="/environment" :aria-current="!isWechat ? 'page' : undefined">环境概览</a>
        <a href="/wechat" :aria-current="isWechat ? 'page' : undefined">微信接入</a>
        <a href="https://github.com/jiuwen567/ai-paper-assistant/blob/main/docs/development.md">开发文档</a>
      </nav>
    </aside>
    <main>
      <div class="section-heading"><h1>{{ isWechat ? "微信接入" : "本地开发环境" }}</h1><NButton tag="a" href="/">返回工作台</NButton></div>
      <section class="status-panel" aria-live="polite">
        <div>
          <h2>{{ state }}</h2>
          <p v-if="error">{{ error }}</p>
          <small>最近检查：{{ checkedAt }}</small>
        </div>
        <NButton @click="refresh" :disabled="(loading)">
          {{ loading ? "检查中…" : "重新检查" }}
        </NButton>
      </section>

      <template v-if="!isWechat">
        <h2>基础服务</h2>
        <dl class="services">
          <div v-for="[key, name] in services" :key="key">
            <dt>{{ name }}</dt>
            <dd :class="{ ready: health?.checks[key] === 'ok' }">{{ serviceStatus(key) }}</dd>
          </div>
        </dl>
        <p class="notice">服务状态用于排查连接问题。论文与材料请在工作台中管理。</p>
      </template>
      <template v-else>
        <h2>微信小程序</h2>
        <p>小程序进入“我的论文”，微信登录后复制绑定码。在已登录的 Web 账号中展开“微信账号”，输入绑定码并确认；再回到小程序登录。</p>
        <p>绑定后可查看同一账号的项目和后台任务。解绑会使小程序登录立即失效，项目资料保留。</p>
        <h2>公众号</h2>
        <p>管理员可将公众号菜单配置为“小程序”入口，路径 pages/projects/projects；帮助菜单指向本站 /wechat。入口须在具备相应权限、已关联小程序的账号中验证。</p>
      </template>
    </main>
  </div>
</template>
