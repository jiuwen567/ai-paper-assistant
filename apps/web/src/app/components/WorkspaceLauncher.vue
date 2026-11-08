<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { NModal, NInput, type InputInst } from 'naive-ui';
import { Search, ArrowRight } from '@lucide/vue';
const props = defineProps<{ disabled?: boolean }>();
const emit = defineEmits<{ navigate: [workspace: string, tab?: string] }>();
const show = ref(false), query = ref(''), input = ref<InputInst | null>(null);
const entries = [
  ['overview', '项目总览', '进度 工作台'], ['writing', '原稿写作', '正文 章节 查找 替换'],
  ['materials', '上传与管理材料', '文件 PDF DOCX', 'files'], ['materials', '检索与证据卡', '引用 标签 笔记', 'library'],
  ['materials', '阅读与文献矩阵', 'AI 比较 提取', 'reading'], ['review', '原稿诊断', '问题 核验', 'diagnosis'],
  ['review', '表达建议', '修订 接受 拒绝', 'expression'], ['feedback', '导师反馈与修改看板', '意见 待办'],
  ['evidence', '依据关系', '图谱 主张', 'graph'], ['evidence', '变更影响', '撤回 更正', 'impact'],
  ['delivery', '导出 Word', '交付 模板', 'export'], ['delivery', 'AI 使用说明', '披露 核对', 'disclosure'],
  ['jobs', '后台任务', '失败 重试 进度'], ['settings', '项目设置', '规则 权限 成员'],
];
const matches = computed(() => entries.filter(entry => entry.join(' ').toLowerCase().includes(query.value.trim().toLowerCase())));
function open() { if (!props.disabled) { query.value = ''; show.value = true; } }
function choose(entry: string[]) { if (props.disabled) return; show.value = false; emit('navigate', entry[0]!, entry[3]); }
function keydown(event: KeyboardEvent) { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && !props.disabled) { event.preventDefault(); open(); } }
onMounted(() => window.addEventListener('keydown', keydown));
onUnmounted(() => window.removeEventListener('keydown', keydown));
</script>
<template>
  <NButton :disabled="disabled" aria-label="快速跳转" title="快速跳转 Ctrl / ⌘ K" @click="open"><Search :size="16" /><span class="launcher-label">快速跳转</span></NButton>
  <NModal v-model:show="show" preset="card" title="快速跳转" class="workspace-launcher" :style="{ width: 'min(560px, calc(100vw - 32px))' }" @after-enter="input?.focus()">
    <NInput ref="input" v-model:value="query" placeholder="搜索功能，例如：文献、导出、待办" :input-props="{ 'aria-label': '搜索工作区功能' }" @keydown.enter.prevent="matches[0] && choose(matches[0])" />
    <div class="launcher-results"><NButton v-for="entry in matches" :key="entry[1]" :disabled="disabled" @click="choose(entry)">{{ entry[1] }}<ArrowRight :size="16" /></NButton><NEmpty v-if="!matches.length" description="没有匹配功能，换个关键词试试" /></div>
    <small>Enter 打开首项 · Tab 选择 · Esc 关闭</small>
  </NModal>
</template>
