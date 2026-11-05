<script setup lang="ts">
import { onMounted, ref } from "vue";
import { request, type Project } from "./projects-api";
import { scopeLabels } from "./sources";
type Metadata = { title: string; authors: string[]; year: string; doi: string; url: string; source_scope: string; abstract: string; note: string; tags: string[] };
const props = defineProps<{ project: Project; versionId: string }>();
const data = ref<{ version: number; snapshot: Metadata } | null>(null);
const authors = ref("");
const tags = ref("");
const busy = ref(false);
const error = ref("");
const message = ref("");
const path = () => `projects/${props.project.id}/files/${props.versionId}/bibliography/`;
async function perform(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = ""; message.value = "";
  try { await action(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "请求失败，请重试。"; }
  finally { busy.value = false; }
}
async function load() {
  data.value = await request(path());
  authors.value = data.value!.snapshot.authors.join(", "); tags.value = data.value!.snapshot.tags.join(", ");
}
const split = (text: string) => text.split(/[,，]/).map(value => value.trim()).filter(Boolean);
async function save() {
  data.value!.snapshot.authors = split(authors.value); data.value!.snapshot.tags = split(tags.value);
  data.value = await request(path(), "PUT", data.value);
  message.value = "题录已保存。";
}
onMounted(() => perform(load));
</script>

<template>
  <details class="bibliography-editor"><summary>文献卡与作者笔记</summary>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="busy" role="status">加载中…</p>
    <button :disabled="busy" @click="perform(load)">重新加载题录</button>
    <form v-if="data" class="editor" @submit.prevent="perform(save)">
      <fieldset :disabled="busy || project.role !== 'author'">
        <label>文献标题<input v-model="data.snapshot.title" required maxlength="300" /></label>
        <label>作者（逗号分隔）<input v-model="authors" /></label>
        <label>年份<input v-model="data.snapshot.year" maxlength="4" /></label>
        <label>DOI<input v-model="data.snapshot.doi" maxlength="200" /></label>
        <label>来源网址<input v-model="data.snapshot.url" type="url" maxlength="500" /></label>
        <label>资料范围<select v-model="data.snapshot.source_scope"><option v-for="(label, value) in scopeLabels" :key="value" :value="value">{{ label }}</option></select></label>
        <label>题录摘要<textarea v-model="data.snapshot.abstract" maxlength="10000" rows="3" /></label>
        <label>文献笔记<textarea v-model="data.snapshot.note" maxlength="10000" rows="3" /></label>
        <label>文献标签（逗号分隔）<input v-model="tags" maxlength="360" /></label>
        <button v-if="project.role === 'author'" type="submit">保存题录</button>
      </fieldset>
    </form>
  </details>
</template>
