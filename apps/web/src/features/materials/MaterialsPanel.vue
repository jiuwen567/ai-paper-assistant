<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref } from "vue";
import { NButton, NDataTable, NTag, NUpload, NUploadDragger, type DataTableColumns, type UploadFileInfo } from "naive-ui";
import { Upload } from "@lucide/vue";
import { ApiError, request } from "@/api/client";
import { type Page } from "@/api/types";
import { type Project } from "@/features/projects/types";
import { usageLabels } from "@/features/impacts/types";
import { csvContent, downloadText } from "@/utils/download";
import SourceReader from "@/features/materials/SourceReader.vue";
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
const query = ref(''), categoryFilter = ref(''), stateFilter = ref('');
const checked = ref<string[]>([]);
let mounted = true;
const filtered = computed(() => (materials.value?.results ?? []).filter(item =>
  (!query.value.trim() || `${item.title} ${item.latest_version.file_name}`.toLowerCase().includes(query.value.trim().toLowerCase())) &&
  (!categoryFilter.value || item.category === categoryFilter.value) &&
  (!stateFilter.value || (stateFilter.value === 'withdrawn' ? item.access_state === 'withdrawn' : item.access_state === 'active' && item.latest_version.status === stateFilter.value))
));
const columns: DataTableColumns<Material> = [
  { type: 'selection' },
  { title: '材料名称', key: 'title', minWidth: 220, sorter: (a, b) => a.title.localeCompare(b.title, 'zh-CN'), render: item => h(NButton, { text: true, disabled: busy.value, onClick: () => perform(() => openMaterial(item)) }, { default: () => item.title }) },
  { title: '分类', key: 'category', width: 110, render: item => categories[item.category] },
  { title: '状态', key: 'status', width: 120, render: item => h(NTag, { size: 'small', bordered: false, type: item.access_state === 'withdrawn' ? 'warning' : item.latest_version.status === 'failed' ? 'error' : 'default' }, { default: () => item.access_state === 'withdrawn' ? '已撤回' : states[item.latest_version.status] }) },
  { title: '版本', key: 'revision', width: 80, render: item => `v${item.latest_version.number}` },
  { title: '文件大小', key: 'size', width: 110, sorter: (a, b) => a.latest_version.size - b.latest_version.size, render: item => `${(item.latest_version.size / 1024).toFixed(1)} KB` },
];
function exportList() {
  const rows = filtered.value.filter(item => checked.value.includes(item.id));
  downloadText('材料清单.csv', csvContent([['材料名称', '分类', '文件', '版本', '状态'], ...rows.map(item => [item.title, categories[item.category]!, item.latest_version.file_name, item.latest_version.number, item.access_state === 'withdrawn' ? '已撤回' : states[item.latest_version.status]!])]), 'text/csv;charset=utf-8');
  message.value = `已导出 ${rows.length} 项材料清单。`;
}
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
    if (!mounted) return;
    error.value = cause instanceof Error ? cause.message : "请求失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      materials.value = null; selected.value = null; versions.value = null; reading.value = null;
      emit("accessLost", cause);
    }
  } finally { busy.value = false; }
}
async function load() {
  const rows: Material[] = [];
  let target = 1, result: Page<Material>;
  do {
    result = await request<Page<Material>>(`${base()}materials/?page=${target++}`);
    if (!mounted) return;
    rows.push(...result.results);
  } while (result.next);
  const unique = [...new Map(rows.map(item => [item.id, item])).values()];
  materials.value = { count: unique.length, results: unique, next: null, previous: null };
  checked.value = checked.value.filter(id => rows.some(item => item.id === id));
  if (selected.value) {
    selected.value = unique.find(m => m.id === selected.value!.id) ?? null;
    if (!selected.value) { versions.value = null; reading.value = null; }
  }
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
  resetFile(); await load();
  const material = materials.value!.results.find(m => m.id === result.material_id) ?? selected.value;
  if (material) await history(material);
  message.value = "材料版本已保存。";
}
onMounted(() => perform(() => load()));
onUnmounted(() => { mounted = false; });
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
    <div class="collection-filters">
      <label>搜索材料<UiInput v-model="query" aria-label="搜索材料" placeholder="材料名称或文件名" /></label>
      <label>筛选分类<UiSelect v-model="categoryFilter" aria-label="筛选材料分类" :options="[{ value: '', label: '全部分类' }, ...Object.entries(categories).map(([value, label]) => ({ value, label }))]" /></label>
      <label>筛选状态<UiSelect v-model="stateFilter" aria-label="筛选材料状态" :options="[{ value: '', label: '全部状态' }, { value: 'available', label: '可用' }, { value: 'failed', label: '失败' }, { value: 'withdrawn', label: '已撤回' }]" /></label>
    </div>
    <div class="actions"><span role="status">{{ filtered.length }} / {{ materials?.count ?? 0 }} 份材料</span><NButton @click="query = ''; categoryFilter = ''; stateFilter = ''">清除筛选</NButton><NButton :disabled="busy || !filtered.some(item => checked.includes(item.id))" @click="exportList">导出所选清单 CSV</NButton></div>
    <NDataTable class="material-table" :columns="columns" :data="filtered" :row-key="(row: Material) => row.id" v-model:checked-row-keys="checked" :pagination="{ pageSize: 10 }" :scroll-x="660" :loading="busy" :row-props="(row: Material) => ({ 'aria-selected': selected?.id === row.id })"><template #empty><NEmpty :description="materials?.count ? '没有匹配材料，请调整筛选' : '上传第一份文献或研究材料'" /></template></NDataTable>
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
