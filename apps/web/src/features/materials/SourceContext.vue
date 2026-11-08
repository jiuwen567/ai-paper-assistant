<script setup lang="ts">
import { ref, watch } from "vue";
import { request } from "@/api/client";
import { type Project } from "@/features/projects/types";
import { anchorLabel, type SourceLocation } from "@/features/materials/types";
import PdfPreview from "@/features/materials/PdfPreview.vue";
const props = defineProps<{ project: Project; location: SourceLocation }>();
const note = ref("");
const tags = ref("");
const busy = ref(false);
const error = ref("");
const message = ref("");
let key = crypto.randomUUID();
watch([note, tags], () => { key = crypto.randomUUID(); message.value = ""; });
async function save() {
  if (busy.value) return;
  busy.value = true; error.value = ""; message.value = "";
  try {
    await request(`projects/${props.project.id}/evidence/`, "POST", { chunk_id: props.location.chunk.id, request_key: key, note: note.value, tags: tags.value.split(/[,，]/).map(v => v.trim()).filter(Boolean) });
    message.value = "证据卡已保存。";
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "保存失败，请重试。"; }
  finally { busy.value = false; }
}
</script>

<template>
  <section aria-label="原文上下文">
    <h4>{{ location.source_version.file_name }} · v{{ location.source_version.number }} · {{ anchorLabel(location.chunk.anchor) }}</h4>
    <article v-for="chunk in location.context" :key="chunk.id" :class="{ 'located-chunk': chunk.id === location.chunk.id }">
      <p>{{ anchorLabel(chunk.anchor) }}</p><pre class="source-text">{{ chunk.text }}</pre>
    </article>
    <template v-if="location.preview_url">
      <a :href="location.preview_url" target="_blank" rel="noopener">打开 PDF 定位页</a>
      <PdfPreview :key="location.preview_url" :url="location.preview_url" :page="location.chunk.anchor.page!" />
    </template>
    <form v-if="project.role === 'author'" class="editor" @submit.prevent="save">
      <fieldset :disabled="busy">
        <label>作者笔记<UiInput v-model="note" maxlength="10000" rows="3" :disabled="(busy)" type="textarea" :aria-label="'作者笔记'" /></label>
        <label>标签（逗号分隔）<UiInput v-model="tags" maxlength="360" :disabled="(busy)" :aria-label="'标签（逗号分隔）'" /></label>
        <NButton attr-type="submit" :disabled="(busy)" type="primary">保存当前片段为证据卡</NButton>
      </fieldset>
      <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert>
      <p v-if="message" role="status">{{ message }}</p>
    </form>
  </section>
</template>
