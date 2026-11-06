<script setup lang="ts">
import { onMounted, ref } from "vue";
import { NUpload, NUploadDragger, type UploadFileInfo } from "naive-ui";
import { Upload } from "@lucide/vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import { usageLabels } from "./impact";
import SourceReader from "./SourceReader.vue";
type Version = {
  id: string; material_id: string; created_by: number; number: number; file_name: string;
  size: number; sha256: string; status: string; usage_state: string; error_message: string;
};
type Material = { id: string; title: string; category: string; revision: number; access_state: string; state_version: number; latest_version: Version };
const props = defineProps<{ project: Project; userId: number }>();
const emit = defineEmits<{ accessLost: [error: ApiError] }>();
const materials = ref<Page<Material> | null>(null);
const selected = ref<Material | null>(null);
const reading = ref<Version | null>(null);
const versions = ref<Page<Version> | null>(null);
const page = ref(1);
const versionPage = ref(1);
const busy = ref(false);
const error = ref("");
const message = ref("");
const title = ref("");
const category = ref("literature");
const file = ref<File | null>(null);
const inputKey = ref(0);
const uploadTarget = ref<Version | null>(null);
let requestKey = crypto.randomUUID();
const categories: Record<string, string> = { literature: "文献", research: "研究材料", manuscript: "作者原稿" };
const states: Record<string, string> = { uploading: "等待上传", validating: "上传校验中", available: "可用", failed: "失败" };
const base = () => `projects/${props.project.id}/`;
async function perform(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = ""; message.value = "";
  try { await action(); }
  catch (cause) {
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      materials.value = null; selected.value = null; versions.value = null; reading.value = null;
      emit("accessLost", cause);
    }
  } finally { busy.value = false; }
}
async function load(target = page.value) {
  materials.value = await request<Page<Material>>(`${base()}materials/?page=${target}`);
  page.value = target;
  if (selected.value) selected.value = materials.value.results.find(m => m.id === selected.value!.id) ?? selected.value;
}
async function refresh() { await load(); if (selected.value) await history(selected.value, versionPage.value); }
async function history(material: Material, target = 1) {
  versions.value = await request<Page<Version>>(`${base()}materials/${material.id}/versions/?page=${target}`);
  selected.value = material; versionPage.value = target;
}
function resetFile() { file.value = null; inputKey.value++; uploadTarget.value = null; requestKey = crypto.randomUUID(); }
function newMaterial() { reading.value = null; selected.value = null; versions.value = null; title.value = ""; resetFile(); }
function chooseFile(data: { fileList: UploadFileInfo[] }) { file.value = data.fileList[0]?.file ?? null; }
async function openMaterial(material: Material) { reading.value = null; resetFile(); await history(material); }
async function changeState() {
  const material = selected.value!;
  const state = await request<{ access_state: string; version: number }>(`${base()}materials/${material.id}/state/`, "PATCH", { version: material.state_version, access_state: material.access_state === "active" ? "withdrawn" : "active" });
  material.access_state = state.access_state; material.state_version = state.version;
  reading.value = null; await refresh();
}
function retry(version: Version) { resetFile(); uploadTarget.value = version; message.value = `请重新选择 ${version.file_name}。`; }
async function upload() {
  if (!file.value) throw new Error("请选择文件。");
  if (file.value.size > 20 * 1024 * 1024) throw new Error("文件不能超过 20 MB。");
  if (!uploadTarget.value) {
    uploadTarget.value = await request<Version>(`${base()}uploads/`, "POST", {
      request_key: requestKey, title: selected.value?.title ?? title.value,
      category: selected.value?.category ?? category.value, file_name: file.value.name, size: file.value.size,
      ...(selected.value ? { material_id: selected.value.id, base_revision: selected.value.revision } : {}),
    });
  }
  const form = new FormData(); form.append("file", file.value);
  const result = await request<Version>(`${base()}uploads/${uploadTarget.value.id}/`, "POST", form);
  resetFile(); await load(1);
  const material = materials.value!.results.find(m => m.id === result.material_id) ?? selected.value;
  if (material) await history(material);
  message.value = "材料版本已保存。";
}
onMounted(() => perform(() => load()));
</script>

<template>
  <section aria-label="材料" :aria-busy="busy">
    <h2>材料</h2>
    <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="busy" role="status">处理中…</p>
    <div class="actions">
      <NButton @click="perform(refresh)" :disabled="(busy)">刷新材料</NButton>
      <NButton v-if="project.role === 'author'" @click="newMaterial" :disabled="(busy)" type="primary">新增材料</NButton>
    </div>
    <p v-if="materials?.count === 0">暂无材料。</p>
    <ul class="project-list"><li v-for="material in materials?.results" :key="material.id">
      <NButton @click="perform(() => openMaterial(material))" :disabled="(busy)">
        {{ material.title }} · {{ categories[material.category] }} · {{ material.access_state === "withdrawn" ? "已撤回" : states[material.latest_version.status] }}
      </NButton>
    </li></ul>
    <div v-if="materials && (materials.next || materials.previous)" class="actions">
      <NButton @click="perform(() => load(page - 1))" :disabled="(busy || !materials.previous)">上一页材料</NButton>
      <NButton @click="perform(() => load(page + 1))" :disabled="(busy || !materials.next)">下一页材料</NButton>
    </div>
    <template v-if="selected">
      <h3>{{ selected.title }} · 版本记录</h3>
      <NButton v-if="project.role === 'author'" @click="perform(changeState)" :disabled="(busy)">{{ selected.access_state === "active" ? "从检索和新任务撤回材料" : "恢复材料使用" }}</NButton>
      <ul><li v-for="version in versions?.results" :key="version.id">
        <span>v{{ version.number }} · {{ version.file_name }} · {{ states[version.status] }} · {{ usageLabels[version.usage_state] }}</span>
        <a v-if="version.status === 'available'" :href="`/api/v1/${base()}files/${version.id}/`">下载 v{{ version.number }}</a>
        <NButton v-else-if="project.role === 'author' && version.created_by === userId" @click="retry(version)" :disabled="(busy)">重试上传 v{{ version.number }}</NButton>
        <NButton v-if="version.status === 'available'" @click="reading = version" :disabled="(busy)">查看原文 v{{ version.number }}</NButton>
        <p v-if="version.error_message">{{ version.error_message }}</p>
      </li></ul>
      <div v-if="versions && (versions.next || versions.previous)" class="actions">
        <NButton @click="perform(() => history(selected!, versionPage - 1))" :disabled="(busy || !versions.previous)">较新版本</NButton>
        <NButton @click="perform(() => history(selected!, versionPage + 1))" :disabled="(busy || !versions.next)">较旧版本</NButton>
      </div>
    </template>
    <SourceReader v-if="reading" :key="reading.id" :project="project" :version="reading" @access-lost="emit('accessLost', $event)" />
    <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(upload)">
      <fieldset :disabled="busy">
        <template v-if="!selected">
          <label>材料名称<UiInput v-model="title" required maxlength="200" :disabled="(busy) || (!!uploadTarget)" :aria-label="'材料名称'" /></label>
          <label>材料分类<UiSelect v-model="category" :disabled="(busy) || (!!uploadTarget)" :options="[...Object.entries(categories).map(([value, label]) => ({ value: value, label: String(label) }))]" :aria-label="'材料分类'" /></label>
        </template>
        <div class="upload-field"><NUpload :key="inputKey" :default-upload="false" :max="1" accept=".pdf,.docx,.csv,.txt" :disabled="busy" @change="chooseFile"><NUploadDragger><Upload :size="24" :stroke-width="1.5" /><p><NButton :disabled="busy">选择文件</NButton></p><small>或将文件拖放到这里</small><br /><small>PDF、DOCX、CSV、TXT · 最多 20 MB</small></NUploadDragger></NUpload></div>
        <NButton attr-type="submit" :disabled="busy || !file" type="primary">{{ uploadTarget ? '重试上传' : selected ? '上传新版本' : '上传材料' }}</NButton>
      </fieldset>
    </form>
  </section>
</template>
