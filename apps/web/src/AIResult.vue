<script lang="ts">
export type AIOutput = {
  status: "pending";
  proposals: { kind: "note" | "suggestion"; text: string; sources: { chunk_id: string; source_scope: string }[] }[];
};
</script>
<script setup lang="ts">
import { onUnmounted, ref } from "vue";
import { ApiError, request, type Project } from "./projects-api";
import SourceContext from "./SourceContext.vue";
import type { SourceLocation } from "./sources";
const props = defineProps<{ project: Project; jobId: string; output: Partial<AIOutput> | null }>();
const emit = defineEmits<{ accessLost: [error: ApiError] }>();
type Trace = { calls: { generation: number; number: number; model: string; prompt_version: string; status: string; usage: { input: number; output: number; cache_read: number; cache_write: number } | null; elapsed_ms: number | null; error_code: string }[] };
const trace = ref<Trace | null>(null);
const location = ref<SourceLocation | null>(null);
const busy = ref(false);
const error = ref("");
let mounted = true;
onUnmounted(() => { mounted = false; });
async function load(chunkId?: string) {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try {
    const base = `projects/${props.project.id}/`;
    if (chunkId) {
      const result = await request<SourceLocation>(`${base}chunks/${chunkId}/`);
      if (mounted) location.value = result;
    } else {
      const result = await request<Trace>(`${base}ai-tasks/${props.jobId}/trace/`);
      if (mounted) trace.value = result;
    }
  } catch (cause) {
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      trace.value = null; location.value = null;
      emit("accessLost", cause);
    }
  } finally { busy.value = false; }
}
</script>

<template>
  <div :aria-busy="busy">
    <p v-if="output?.proposals?.length">待核对</p>
    <ul v-if="output?.proposals?.length" class="source-chunks">
      <li v-for="(proposal, index) in output.proposals" :key="index">
        <p class="chunk-excerpt">{{ proposal.text }}</p>
        <div class="actions"><button v-for="(source, number) in proposal.sources" :key="source.chunk_id" :disabled="busy" @click="load(source.chunk_id)">
          来源 {{ number + 1 }} · {{ { unknown: '范围未核实', abstract: '仅摘要', full_text: '全文', research: '研究材料' }[source.source_scope] || source.source_scope }}
        </button></div>
      </li>
    </ul>
    <button :disabled="busy" @click="load()">调用记录</button>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="busy" role="status">加载中…</p>
    <p v-if="trace?.calls.length === 0">尚未调用模型。</p>
    <ul v-if="trace"><li v-for="call in trace.calls" :key="`${call.generation}-${call.number}`">
      第 {{ call.generation }} 次执行 / 调用 {{ call.number }} · {{ call.model }} · {{ call.prompt_version }} ·
      {{ { running: '执行中', succeeded: '成功', failed: '失败', cancelled: '已取消' }[call.status] || call.status }}
      <span v-if="call.elapsed_ms !== null"> · {{ call.elapsed_ms }} ms</span>
      <span v-if="call.usage"> · 输入 {{ call.usage.input }} / 输出 {{ call.usage.output }} token</span>
      <span v-else> · 用量未返回</span>
      <span v-if="call.error_code"> · {{ call.error_code }}</span>
    </li></ul>
    <SourceContext v-if="location" :key="location.chunk.id" :project="project" :location="location" />
  </div>
</template>
