<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import AIResult, { type AIOutput } from "./AIResult.vue";

type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
type Attempt = { generation: number; status: JobStatus; error_message: string };
type Job = {
  id: string; kind: string; status: JobStatus; progress: number; generation: number; retryable: boolean;
  error_code: string; error_message: string; created_at: string; attempts: Attempt[];
  input_snapshot: { purpose?: string };
  output: ({ characters?: number; source_version?: number; chunks?: number; segments?: number } & Partial<AIOutput>) | null;
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
    <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert>
    <p v-if="!jobs && busy" role="status">加载任务…</p>
    <NButton @click="perform(() => load())" :disabled="(busy)">刷新任务</NButton>
    <p v-if="jobs?.count === 0">暂无任务。</p>
    <ul class="project-list">
      <li v-for="job in jobs?.results" :key="job.id">
        <UiDisclosure>
          <template #header>{{ job.kind === "export" ? "Word 导出" : job.kind === "parse" ? "材料解析" : job.kind === "index" ? "检索索引" : job.kind === "ai" ? job.input_snapshot.purpose === 'expression' ? '表达建议' : job.input_snapshot.purpose === 'review' ? '原稿诊断' : job.input_snapshot.purpose === 'comparison' ? '文献比较' : job.input_snapshot.purpose === 'reading' ? '文献阅读' : 'AI 摘记' : "字数统计" }} · {{ labels[job.status] }} · {{ job.progress }}%</template>
          <p>{{ new Date(job.created_at).toLocaleString("zh-CN") }}</p>
          <p v-if="job.error_message" role="status">{{ job.error_message }}（{{ job.error_code }}）</p>
          <p v-if="job.output && job.kind === 'sample'">{{ job.output.characters }} 字 · 输入版本 {{ job.output.source_version }}</p>
          <p v-if="job.output && job.kind === 'parse'">{{ job.output.chunks }} 个片段</p>
          <p v-if="job.output && job.kind === 'index'">{{ job.output.segments }} 个索引片段</p>
          <AIResult v-if="job.kind === 'ai'" :project="project" :job-id="job.id" :output="job.output" @access-lost="emit('accessLost', $event)" />
          <ul><li v-for="attempt in job.attempts" :key="attempt.generation">
            第 {{ attempt.generation }} 次 · {{ labels[attempt.status] }} {{ attempt.error_message }}
          </li></ul>
          <div v-if="project.role === 'author'" class="actions">
            <NButton v-if="['queued', 'running'].includes(job.status)" @click="perform(() => control(job, 'cancel'))" :disabled="(busy)">取消任务</NButton>
            <NButton v-if="job.status === 'failed' && job.retryable && job.generation < 3" @click="perform(() => control(job, 'retry'))" :disabled="(busy)">重试任务</NButton>
          </div>
        </UiDisclosure>
      </li>
    </ul>
    <div v-if="jobs && (jobs.previous || jobs.next)" class="actions" aria-label="任务分页">
      <NButton @click="perform(() => load(page - 1))" :disabled="(busy || !jobs.previous)">上一页任务</NButton>
      <NButton @click="perform(() => load(page + 1))" :disabled="(busy || !jobs.next)">下一页任务</NButton>
    </div>
    <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(create)">
      <fieldset :disabled="busy">
        <label>字数统计样例<UiInput v-model="text" required maxlength="10000" rows="2" :disabled="(busy)" type="textarea" :aria-label="'字数统计样例'" /></label>
        <NButton attr-type="submit" :disabled="(busy)" type="primary">开始统计</NButton>
      </fieldset>
    </form>
  </section>
</template>
