import { describe, expect, it } from 'vitest';
import { characterCount, findInBlocks, replaceInBlocks } from "@/features/manuscripts/tools";
import { csvContent } from "@/utils/download";
const blocks = [{ id: 'heading', text: '研究 A+B', heading_level: 1 }, { id: 'body', text: 'a+b 与 A+B，$& 不是占位符。', heading_level: 0 }];
describe('作者草稿工具', () => {
  it('中文和补充平面字符按字符统计，排除空白', () => { expect(characterCount('研究 𠀀\nA\t')).toBe(4); });
  it('按字面查找特殊字符，计数与大小写替换范围一致', () => {
    expect(findInBlocks(blocks, 'A+B').map(item => item.count)).toEqual([1, 2]);
    expect(findInBlocks(blocks, 'A+B', true).map(item => item.count)).toEqual([1, 1]);
    const replaced = replaceInBlocks(blocks, 'A+B', '$&');
    expect(replaced[0]!.text).toBe('研究 $&');
    expect(replaced[1]!.text).toBe('$& 与 $&，$& 不是占位符。');
    expect(blocks[0]!.text).toBe('研究 A+B');
    expect(replaced.map(({ id, heading_level }) => ({ id, heading_level }))).toEqual(blocks.map(({ id, heading_level }) => ({ id, heading_level })));
  });
  it('空查询不改稿，替换支持删除与非重叠匹配', () => {
    expect(findInBlocks(blocks, '')).toEqual([]);
    expect(replaceInBlocks(blocks, '', '文字')).toEqual(blocks);
    expect(replaceInBlocks(blocks, 'A+B', '')[0]!.text).toBe('研究 ');
    expect(findInBlocks([{ id: 'one', text: 'aaaa', heading_level: 0 }], 'aa')[0]!.count).toBe(2);
  });
  it('Unicode 大小写匹配与替换采用相同规则', () => {
    const value = [{ id: 'one', text: 'ſ S s', heading_level: 0 }];
    expect(findInBlocks(value, 's')[0]!.count).toBe(3);
    expect(replaceInBlocks(value, 's', 'X')[0]!.text).toBe('X X X');
  });
});
describe('清单 CSV', () => {
  it('保留中文、逗号、换行和引号，阻止单元格公式执行', () => {
    expect(csvContent([['文献,标题', '原文\n"摘录"', '=1+1', '  @SUM(A1)', '\t公式', '-2', 3]])).toBe('\uFEFF"文献,标题","原文\n""摘录""","\'=1+1","\'  @SUM(A1)","\'\t公式","\'-2","3"');
  });
});
