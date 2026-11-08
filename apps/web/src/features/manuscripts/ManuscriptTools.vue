<script setup lang="ts">
import { computed, ref } from 'vue';
import type { Block } from '@/features/manuscripts/types';
import { characterCount, findInBlocks, outlineTemplates, replaceInBlocks } from "@/features/manuscripts/tools";
import { downloadText } from "@/utils/download";
import { useConfirm } from '@/ui/confirm';
const props = defineProps<{ blocks: Block[]; disabled: boolean; canEdit: boolean }>();
const emit = defineEmits<{ 'update:blocks': [blocks: Block[]] }>();
const confirm = useConfirm();
const query = ref(''), replacement = ref(''), matchCase = ref(false), template = ref('research'), message = ref('');
const undo = ref<{ before: Block[]; after: string } | null>(null);
const matches = computed(() => findInBlocks(props.blocks, query.value, matchCase.value));
const count = computed(() => matches.value.reduce((total, item) => total + item.count, 0));
const characters = computed(() => props.blocks.reduce((total, block) => total + characterCount(block.text), 0));
const canUndo = computed(() => undo.value && undo.value.after === JSON.stringify(props.blocks));
function update(blocks: Block[], notice: string) {
  undo.value = { before: props.blocks.map(block => ({ ...block })), after: JSON.stringify(blocks) };
  emit('update:blocks', blocks); message.value = notice;
}
async function replaceAll() {
  if (props.disabled || !props.canEdit || !count.value) return;
  const before = JSON.stringify(props.blocks), total = count.value;
  const result = replaceInBlocks(props.blocks, query.value, replacement.value, matchCase.value);
  if (result.some(block => block.text.length > 20000)) { message.value = '替换后有正文块超过 20000 字符，请缩小替换范围。'; return; }
  if (await confirm(`将替换 ${total} 处文字（包含标题），保存前可撤销本次操作。继续？`, { title: '确认批量替换', positiveText: '确认替换', negativeText: '取消' })) {
    if (props.disabled || !props.canEdit || before !== JSON.stringify(props.blocks)) { message.value = '原稿已变化，请重新检查替换范围。'; return; }
    update(result, `已替换 ${total} 处，请核对并保存原稿。`);
  }
}
function insertOutline() {
  if (props.disabled || !props.canEdit) return;
  const titles = outlineTemplates[template.value]!;
  if (props.blocks.length + titles.length > 500) { message.value = '章节插入后将超过 500 块上限。'; return; }
  update([...props.blocks, ...titles.map(text => ({ id: crypto.randomUUID(), text, heading_level: 1 }))], '章节标题已追加到草稿末尾，请按研究需要调整。');
}
function restore() {
  if (props.disabled || !props.canEdit || !canUndo.value || !undo.value) return;
  emit('update:blocks', undo.value.before); undo.value = null; message.value = '已撤销本次工具操作。';
}
function exportDraft() {
  downloadText('作者原稿草稿.md', props.blocks.map(block => `${block.heading_level ? '#'.repeat(Math.min(block.heading_level, 6)) + ' ' : ''}${block.text}`).join('\n\n'), 'text/markdown;charset=utf-8');
  message.value = '已下载当前草稿 Markdown，未改变已保存版本。';
}
</script>
<template>
  <div class="writing-tools">
    <div class="actions writing-statistics"><span>{{ characters }} 字符（不含空白）</span><span>{{ blocks.filter(block => block.heading_level).length }} 个标题</span><span>{{ blocks.filter(block => !block.heading_level).length }} 个正文块</span><NButton size="small" :disabled="disabled || !blocks.length" @click="exportDraft">下载草稿 Markdown</NButton></div>
    <UiDisclosure><template #header>查找替换与章节工具</template>
      <div class="collection-filters"><label>查找文字<UiInput v-model="query" aria-label="查找原稿文字" maxlength="200" /></label><label v-if="canEdit">替换为<UiInput v-model="replacement" aria-label="替换为" maxlength="2000" :disabled="disabled" /></label></div>
      <div class="actions"><UiCheckbox v-model="matchCase" aria-label="区分大小写">区分大小写</UiCheckbox><span role="status">{{ count }} 处匹配 · {{ matches.length }} 个正文块或标题</span><NButton v-if="canEdit" :disabled="disabled || !count" @click="replaceAll">全部替换</NButton><NButton v-if="canEdit" :disabled="disabled || !canUndo" @click="restore">撤销工具操作</NButton></div>
      <ul v-if="matches.length" class="find-results"><li v-for="item in matches" :key="item.id"><a :href="`#block-${item.id}`">块 {{ item.index + 1 }} · {{ item.count }} 处：{{ item.text.slice(0, 100) }}</a></li></ul>
      <div v-if="canEdit" class="outline-tools"><label>章节骨架<UiSelect v-model="template" aria-label="章节骨架" :options="[{ value: 'research', label: '实证研究' }, { value: 'review', label: '文献综述' }, { value: 'engineering', label: '设计与实现' }]" :disabled="disabled" /></label><p class="notice">{{ outlineTemplates[template]!.join(' / ') }}</p><NButton :disabled="disabled" @click="insertOutline">追加章节标题</NButton><small>仅添加标题，正文由作者撰写。</small></div>
      <p v-if="message" role="status">{{ message }}</p>
    </UiDisclosure>
  </div>
</template>
