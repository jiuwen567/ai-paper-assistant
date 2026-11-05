<script setup lang="ts">
import type { ExportContent } from "./export";
defineProps<{ content: ExportContent }>();
</script>
<template>
  <article aria-label="导出内容">
    <h3>{{ content.title }}</h3><p v-if="content.author">{{ content.author }}</p>
    <p>稿件 v{{ content.manuscript_version }} · {{ content.template.name }} v{{ content.template.number }} · 披露 v{{ content.disclosure.number }}</p>
    <p v-for="warning in content.warnings" :key="warning" role="status">{{ warning }}</p>
    <details><summary>正文与引用</summary>
      <div v-for="block in content.blocks" :key="block.id" class="export-block">
        <strong v-if="block.heading_level">{{ block.text }}</strong>
        <span v-else><template v-if="block.caption">{{ `${block.caption.kind === 'figure' ? '图' : '表'} ${block.caption.number} ` }}</template>{{ block.text }}</span>
        <sup v-for="number in [...new Set(block.references.map(item => item.number))]" :key="number">[{{ number }}]</sup>
      </div>
      <h4 v-if="content.references.length">参考文献</h4>
      <p v-for="reference in content.references" :key="reference.number">[{{ reference.number }}] {{ reference.text }}（题录 v{{ reference.bibliography_number }}）</p>
    </details>
    <details><summary>AI 使用说明</summary><p class="export-block">{{ content.disclosure.text }}</p>
      <p v-for="(item, i) in content.disclosure.external_uses" :key="i">{{ item.tool }} · {{ item.purpose }} · {{ item.scope }} · {{ item.used_at }} · {{ item.note }}</p>
    </details>
  </article>
</template>
<style scoped>article { overflow-wrap: anywhere; } .export-block { white-space: pre-wrap; overflow-wrap: anywhere; margin: .8rem 0; }</style>
