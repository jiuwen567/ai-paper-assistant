<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";

type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
type Attempt = { generation: number; status: JobStatus; error_message: string };
type Job = {
  id: string; kind: string; status: JobStatus; progress: number; generation: number; retryable: boolean;
  error_code: string; error_message: string; created_at: string; attempts: Attempt[];
  output: { characters?: number; source_version?: number; chunks?: number; segments?: number } | null;
};
const props = defineProps<{ project: Project }>();
const emit = defineEmits<{ accessLost: [error: ApiError] }>();
const jobs = ref<Page<Job> | null>(null);
const page = ref(1);
const text = ref("");
const busy = ref(false);
const error = ref("");
let key = crypto.randomUUID();
let timer: ReturnType<typeof setTimeout> | undefined;
let mounted = true;
const labels: Record<JobStatus, string> = {
  queued: "等待执行", running: "执行中", succeeded: "成功", failed: "失败", cancelled: "已取消",
};
const path = () => `projects/${props.project.id}/jobs/`;
watch(text, () => { key = crypto.randomUUID(); });

async function perform(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try { await action(); }
  catch (cause) {
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "连接失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      jobs.value = null;
      emit("accessLost", cause);
    }
  } finally { busy.value = false; }
}
async function load(target = page.value) {
  const result = await request<Page<Job>>(`${path()}?page=${target}`);
  if (mounted) { jobs.value = result; page.value = target; }
}
async function create() {
  await request<Job>(path(), "POST", {
    kind: "sample", idempotency_key: key, policy_version: props.project.policy.version,
    input_snapshot: { text: text.value, source_version: 1, steps: 10 },
  });
  key = crypto.randomUUID();
  text.value = "";
  await load(1);
}
async function control(job: Job, action: "cancel" | "retry") {
  await request<Job>(`${path()}${job.id}/${action}/`, "POST", { generation: job.generation });
  await load();
}
async function poll() {
  if (!mounted) return;
  await perform(() => load());
  if (mounted) timer = setTimeout(poll, 3000);
}
onMounted(poll);
onUnmounted(() => { mounted = false; clearTimeout(timer); });
</script>

<template>
  <section aria-label="后台任务" :aria-busy="busy">
    <h2>后台任务</h2>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="!jobs && busy" role="status">加载任务…</p>
    <button :disabled="busy" @click="perform(() => load())">刷新任务</button>
    <p v-if="jobs?.count === 0">暂无任务。</p>
    <ul class="project-list">
      <li v-for="job in jobs?.results" :key="job.id">
        <details>
          <summary>{{ job.kind === "parse" ? "材料解析" : job.kind === "index" ? "检索索引" : "字数统计" }} · {{ labels[job.status] }} · {{ job.progress }}%</summary>
          <p>{{ new Date(job.created_at).toLocaleString("zh-CN") }}</p>
          <p v-if="job.error_message" role="status">{{ job.error_message }}（{{ job.error_code }}）</p>
          <p v-if="job.output && job.kind === 'sample'">{{ job.output.characters }} 字 · 输入版本 {{ job.output.source_version }}</p>
          <p v-if="job.output && job.kind === 'parse'">{{ job.output.chunks }} 个片段</p>
          <p v-if="job.output && job.kind === 'index'">{{ job.output.segments }} 个索引片段</p>
          <ul><li v-for="attempt in job.attempts" :key="attempt.generation">
            第 {{ attempt.generation }} 次 · {{ labels[attempt.status] }} {{ attempt.error_message }}
          </li></ul>
          <div v-if="project.role === 'author'" class="actions">
            <button v-if="['queued', 'running'].includes(job.status)" :disabled="busy" @click="perform(() => control(job, 'cancel'))">取消任务</button>
            <button v-if="job.status === 'failed' && job.retryable && job.generation < 3" :disabled="busy" @click="perform(() => control(job, 'retry'))">重试任务</button>
          </div>
        </details>
      </li>
    </ul>
    <div v-if="jobs && (jobs.previous || jobs.next)" class="actions" aria-label="任务分页">
      <button :disabled="busy || !jobs.previous" @click="perform(() => load(page - 1))">上一页任务</button>
      <button :disabled="busy || !jobs.next" @click="perform(() => load(page + 1))">下一页任务</button>
    </div>
    <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(create)">
      <fieldset :disabled="busy">
        <label>字数统计样例<textarea v-model="text" required maxlength="10000" rows="2" /></label>
        <button type="submit">开始统计</button>
      </fieldset>
    </form>
  </section>
</template>
