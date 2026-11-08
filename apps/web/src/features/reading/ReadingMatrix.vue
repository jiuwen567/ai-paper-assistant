<script setup lang="ts">
import { computed, ref } from 'vue';
import { NTable } from 'naive-ui';
import { readingFields, type ReadingDocument, type ReadingField, type ReadingRecord } from '@/features/reading/types';
import { scopeLabels } from '@/features/materials/types';
import { csvContent, downloadText } from "@/utils/download";
const props = defineProps<{ records: ReadingRecord[]; busy: boolean }>();
const emit = defineEmits<{ open: [id: string] }>();
const query = ref(''), state = ref(''), fields = ref<ReadingField[]>(['subject', 'method', 'result', 'limitations']);
const message = ref('');
type Row = { key: string; record: ReadingRecord; document: ReadingDocument };
const status = (record: ReadingRecord) => record.sources_changed ? '来源已变化' : record.author_revision?.verified ? '作者已核对' : '待核对';
function value(row: Row, field: ReadingField) {
  const edit = row.record.author_revision?.edits.find(edit => edit.version_id === row.document.version_id && edit.field === field);
  return { text: edit?.text ?? row.document.fields[field].text, origin: edit ? '作者修订' : '模型提取' };
}
const rows = computed<Row[]>(() => props.records.flatMap(record => record.model_output.documents.map(document => ({ key: `${record.id}:${document.version_id}`, record, document }))).filter(row =>
  (!state.value || status(row.record) === state.value) && (!query.value.trim() || [row.document.title, ...Object.keys(readingFields).map(field => value(row, field as ReadingField).text)].join(' ').toLowerCase().includes(query.value.trim().toLowerCase()))
));
function exportRows() {
  const header = ['文献', '文件', '来源版本 ID', '版本', '资料范围', '核对状态', '阅读记录 ID', ...fields.value.flatMap(field => [readingFields[field], `${readingFields[field]}内容来源`, `${readingFields[field]}原文依据`])];
  const data = rows.value.map(row => [row.document.title, row.document.file_name, row.document.version_id, row.document.source_number, scopeLabels[row.document.source_scope] ?? row.document.source_scope, status(row.record), row.record.id, ...fields.value.flatMap(field => [value(row, field).text, value(row, field).origin, row.document.fields[field].citations.map(c => `${c.source_version_id} / ${c.chunk_id}: ${c.quote}`).join('\n')])]);
  downloadText('文献阅读矩阵.csv', csvContent([header, ...data]), 'text/csv;charset=utf-8');
  message.value = `已导出 ${rows.value.length} 行已保存摘记。`;
}
</script>
<template>
  <UiDisclosure><template #header>文献矩阵 · 本页已保存摘记</template>
    <div class="collection-filters"><label>检索矩阵<UiInput v-model="query" aria-label="检索阅读矩阵" placeholder="文献、方法或结论" /></label><label>核对状态<UiSelect v-model="state" aria-label="矩阵核对状态" :options="[{ value: '', label: '全部状态' }, ...['待核对', '作者已核对', '来源已变化'].map(value => ({ value, label: value }))]" /></label></div>
    <div class="actions"><UiCheckbox v-for="(label, field) in readingFields" :key="field" v-model="fields" :value="field" :aria-label="`矩阵列：${label}`">{{ label }}</UiCheckbox><NButton :disabled="busy || !rows.length" @click="exportRows">导出矩阵 CSV</NButton></div>
    <div class="reading-matrix-scroll" tabindex="0" aria-label="文献阅读矩阵表格">
      <NTable v-if="rows.length" size="small" :single-line="false" :style="{ minWidth: `${230 + fields.length * 240}px` }"><thead><tr><th scope="col">文献 / 来源</th><th v-for="field in fields" :key="field" scope="col">{{ readingFields[field] }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.key"><td><NButton text :disabled="busy" @click="emit('open', row.record.id)">{{ row.document.title }}</NButton><p>v{{ row.document.source_number }} · {{ scopeLabels[row.document.source_scope] }} · {{ status(row.record) }}</p></td><td v-for="field in fields" :key="field"><p class="preserve-lines">{{ value(row, field).text || '未提取' }}</p><small>{{ value(row, field).origin }} · {{ row.document.fields[field].citations.length }} 处原文依据</small></td></tr></tbody></NTable>
      <NEmpty v-else description="暂无匹配摘记，先完成阅读或调整筛选" />
    </div>
    <p class="notice">点击文献回查原文与作者修订。同一文献的不同阅读记录分别保留。</p><p v-if="message" role="status">{{ message }}</p>
  </UiDisclosure>
</template>
