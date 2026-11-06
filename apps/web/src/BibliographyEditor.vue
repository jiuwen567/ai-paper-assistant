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
  <UiDisclosure class="bibliography-editor"><template #header>文献卡与作者笔记</template>
    <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="busy" role="status">加载中…</p>
    <NButton @click="perform(load)" :disabled="(busy)">重新加载题录</NButton>
    <form v-if="data" class="editor" @submit.prevent="perform(save)">
      <fieldset :disabled="busy || project.role !== 'author'">
        <label>文献标题<UiInput v-model="data.snapshot.title" required maxlength="300" :disabled="(busy || project.role !== 'author')" :aria-label="'文献标题'" /></label>
        <label>作者（逗号分隔）<UiInput v-model="authors" :disabled="(busy || project.role !== 'author')" :aria-label="'作者（逗号分隔）'" /></label>
        <label>年份<UiInput v-model="data.snapshot.year" maxlength="4" :disabled="(busy || project.role !== 'author')" :aria-label="'年份'" /></label>
        <label>DOI<UiInput v-model="data.snapshot.doi" maxlength="200" :disabled="(busy || project.role !== 'author')" :aria-label="'DOI'" /></label>
        <label>来源网址<UiInput v-model="data.snapshot.url" type="url" maxlength="500" :disabled="(busy || project.role !== 'author')" :aria-label="'来源网址'" /></label>
        <label>资料范围<UiSelect v-model="data.snapshot.source_scope" :disabled="(busy || project.role !== 'author')" :options="[...Object.entries(scopeLabels).map(([value, label]) => ({ value: value, label: String(label) }))]" :aria-label="'资料范围'" /></label>
        <label>题录摘要<UiInput v-model="data.snapshot.abstract" maxlength="10000" rows="3" :disabled="(busy || project.role !== 'author')" type="textarea" :aria-label="'题录摘要'" /></label>
        <label>文献笔记<UiInput v-model="data.snapshot.note" maxlength="10000" rows="3" :disabled="(busy || project.role !== 'author')" type="textarea" :aria-label="'文献笔记'" /></label>
        <label>文献标签（逗号分隔）<UiInput v-model="tags" maxlength="360" :disabled="(busy || project.role !== 'author')" :aria-label="'文献标签（逗号分隔）'" /></label>
        <NButton v-if="project.role === 'author'" attr-type="submit" :disabled="(busy || project.role !== 'author')" type="primary">保存题录</NButton>
      </fieldset>
    </form>
  </UiDisclosure>
</template>
