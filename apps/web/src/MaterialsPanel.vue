<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ApiError, request, type Page, type Project } from "./projects-api";
import SourceReader from "./SourceReader.vue";
type Version = {
  id: string; material_id: string; created_by: number; number: number; file_name: string;
  size: number; sha256: string; status: string; error_message: string;
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
function chooseFile(event: Event) { file.value = (event.target as HTMLInputElement).files?.[0] ?? null; }
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
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="busy" role="status">处理中…</p>
    <div class="actions">
      <button :disabled="busy" @click="perform(refresh)">刷新材料</button>
      <button v-if="project.role === 'author'" :disabled="busy" @click="newMaterial">新增材料</button>
    </div>
    <p v-if="materials?.count === 0">暂无材料。</p>
    <ul class="project-list"><li v-for="material in materials?.results" :key="material.id">
      <button :disabled="busy" @click="perform(() => openMaterial(material))">
        {{ material.title }} · {{ categories[material.category] }} · {{ material.access_state === "withdrawn" ? "已撤回" : states[material.latest_version.status] }}
      </button>
    </li></ul>
    <div v-if="materials && (materials.next || materials.previous)" class="actions">
      <button :disabled="busy || !materials.previous" @click="perform(() => load(page - 1))">上一页材料</button>
      <button :disabled="busy || !materials.next" @click="perform(() => load(page + 1))">下一页材料</button>
    </div>
    <template v-if="selected">
      <h3>{{ selected.title }} · 版本记录</h3>
      <button v-if="project.role === 'author'" :disabled="busy" @click="perform(changeState)">{{ selected.access_state === "active" ? "从检索和新任务撤回材料" : "恢复材料使用" }}</button>
      <ul><li v-for="version in versions?.results" :key="version.id">
        <span>v{{ version.number }} · {{ version.file_name }} · {{ states[version.status] }}</span>
        <a v-if="version.status === 'available'" :href="`/api/v1/${base()}files/${version.id}/`">下载 v{{ version.number }}</a>
        <button v-else-if="project.role === 'author' && version.created_by === userId" :disabled="busy" @click="retry(version)">重试上传 v{{ version.number }}</button>
        <button v-if="version.status === 'available'" :disabled="busy" @click="reading = version">查看原文 v{{ version.number }}</button>
        <p v-if="version.error_message">{{ version.error_message }}</p>
      </li></ul>
      <div v-if="versions && (versions.next || versions.previous)" class="actions">
        <button :disabled="busy || !versions.previous" @click="perform(() => history(selected!, versionPage - 1))">较新版本</button>
        <button :disabled="busy || !versions.next" @click="perform(() => history(selected!, versionPage + 1))">较旧版本</button>
      </div>
    </template>
    <SourceReader v-if="reading" :key="reading.id" :project="project" :version="reading" @access-lost="emit('accessLost', $event)" />
    <form v-if="project.role === 'author'" class="editor" @submit.prevent="perform(upload)">
      <fieldset :disabled="busy">
        <template v-if="!selected">
          <label>材料名称<input v-model="title" required maxlength="200" :disabled="!!uploadTarget" /></label>
          <label>材料分类<select v-model="category" :disabled="!!uploadTarget"><option v-for="(label, value) in categories" :key="value" :value="value">{{ label }}</option></select></label>
        </template>
        <label>文件（PDF、DOCX、CSV、TXT，最多 20 MB）<input :key="inputKey" type="file" accept=".pdf,.docx,.csv,.txt" required @change="chooseFile" /></label>
        <button type="submit">{{ uploadTarget ? '重试上传' : selected ? '上传新版本' : '上传材料' }}</button>
      </fieldset>
    </form>
  </section>
</template>
