import type { Block } from '@/features/manuscripts/types';

export const outlineTemplates: Record<string, string[]> = {
  research: ['摘要', '引言', '相关研究', '研究方法', '研究结果', '讨论', '结论'],
  review: ['摘要', '引言', '文献选择与范围', '主题梳理', '研究分歧与不足', '讨论与展望', '结论'],
  engineering: ['摘要', '绪论', '需求分析', '系统设计', '实现与测试', '讨论', '总结'],
};
export function characterCount(text: string) { return Array.from(text.replace(/\s/gu, '')).length; }
function literalPattern(query: string, matchCase: boolean) {
  return new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), matchCase ? 'gu' : 'giu');
}
export function findInBlocks(blocks: Block[], query: string, matchCase = false) {
  if (!query) return [];
  return blocks.flatMap((block, index) => {
    const count = [...block.text.matchAll(literalPattern(query, matchCase))].length;
    return count ? [{ id: block.id, index, count, text: block.text }] : [];
  });
}
export function replaceInBlocks(blocks: Block[], query: string, replacement: string, matchCase = false): Block[] {
  if (!query) return blocks.map(block => ({ ...block }));
  const pattern = literalPattern(query, matchCase);
  return blocks.map(block => ({ ...block, text: block.text.replace(pattern, () => replacement) }));
}
