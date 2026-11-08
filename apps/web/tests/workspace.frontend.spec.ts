import { expect, test, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { fixture, launch } from './fixtures/workspace';

async function select(page: Page, name: string, value: string) {
  const field = page.getByLabel(name, { exact: true });
  await field.click();
  await page.locator(`[id="${await field.getAttribute('aria-controls')}"] [data-option-value="${value}"]`).click();
}
async function downloadedText(page: Page, action: () => Promise<unknown>) {
  const waiting = page.waitForEvent('download'); await action();
  const download = await waiting; return readFile((await download.path())!, 'utf8');
}

test('项目总览、部分失败、快捷搜索与手机布局', async ({ page }, info) => {
  const state = await fixture(page);
  const overview = page.getByRole('region', { name: '项目总览', exact: true });
  await expect(overview.getByRole('button', { name: '12 材料' })).toBeVisible();
  await expect(overview.getByRole('button', { name: '2 待处理修改' })).toBeVisible();
  await expect(overview).toContainText('不同条件如何影响结果？');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('overview.png'), fullPage: true });
  state.failMaterials = true;
  await overview.getByRole('button', { name: '刷新总览' }).click();
  await expect(overview.getByRole('alert')).toContainText('材料服务暂不可用');
  await expect(overview.getByRole('button', { name: '— 材料' })).toBeVisible();
  state.failMaterials = false;
  await overview.getByRole('button', { name: '刷新总览' }).click();
  await expect(overview.getByRole('button', { name: '12 材料' })).toBeVisible();
  await page.keyboard.press('Control+k');
  await page.getByRole('textbox', { name: '搜索工作区功能' }).fill('不存在的功能');
  await expect(page.getByRole('dialog')).toContainText('没有匹配功能');
  await page.getByRole('textbox', { name: '搜索工作区功能' }).fill('正文');
  await page.getByRole('textbox', { name: '搜索工作区功能' }).press('Enter');
  await expect(page.getByRole('region', { name: '作者原稿', exact: true })).toBeVisible();
  expect(state.errors).toEqual([]);
});

test('材料跨服务端分页筛选、排序与所选清单下载', async ({ page }, info) => {
  const state = await fixture(page);
  await launch(page, '上传与管理材料');
  const panel = page.getByRole('region', { name: '材料', exact: true });
  await expect(panel).toContainText('12 / 12 份材料');
  await page.getByRole('textbox', { name: '搜索材料', exact: true }).fill('跨页');
  await expect(panel.getByRole('button', { name: '跨页研究记录', exact: true })).toBeVisible();
  await expect(panel).toContainText('1 / 12 份材料');
  await panel.locator('tbody').getByRole('checkbox').check();
  const csv = await downloadedText(page, () => panel.getByRole('button', { name: '导出所选清单 CSV' }).click());
  expect(csv).toContain('跨页研究记录'); expect(csv).not.toContain('自制文献 1');
  await panel.getByRole('button', { name: '跨页研究记录', exact: true }).click();
  await expect(panel.getByRole('heading', { name: '跨页研究记录 · 版本记录' })).toBeVisible();
  await panel.getByRole('button', { name: '清除筛选' }).click();
  await panel.getByRole('columnheader', { name: '文件大小' }).click();
  await expect(panel.locator('tbody tr').first()).toContainText('跨页研究记录');
  await panel.getByRole('columnheader', { name: '文件大小' }).click();
  await expect(panel.locator('tbody tr').first()).toContainText('自制文献 1');
  await select(page, '筛选材料状态', 'withdrawn');
  await expect(panel.getByRole('button', { name: '自制文献 11', exact: true })).toBeVisible();
  await expect(panel).toContainText('1 / 12 份材料');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('heading', { name: '材料', exact: true }).click();
  await page.screenshot({ path: info.outputPath('materials.png'), fullPage: true });
  expect(state.errors).toEqual([]);
});

test('作者查找替换、撤销、章节骨架、预览、专注与保存冲突', async ({ page }, info) => {
  const state = await fixture(page);
  await launch(page, '原稿写作');
  const panel = page.getByRole('region', { name: '作者原稿', exact: true });
  await panel.getByText('查找替换与章节工具', { exact: true }).click();
  await page.getByRole('textbox', { name: '查找原稿文字' }).fill('A+B');
  await expect(panel).toContainText('2 处匹配');
  await page.getByRole('textbox', { name: '替换为', exact: true }).fill('$&');
  await panel.getByRole('button', { name: '全部替换', exact: true }).click();
  await page.getByRole('button', { name: '确认替换', exact: true }).click();
  await expect(panel.getByRole('textbox', { name: '正文块 2', exact: true })).toHaveValue('方法 $& 与 $& 需要核对。');
  await panel.getByRole('button', { name: '撤销工具操作', exact: true }).click();
  await expect(panel.getByRole('textbox', { name: '正文块 2', exact: true })).toHaveValue('方法 A+B 与 a+b 需要核对。');
  await panel.getByRole('button', { name: '追加章节标题', exact: true }).click();
  await expect(panel.getByRole('textbox', { name: '标题 9', exact: true })).toHaveValue('结论');
  await panel.getByRole('button', { name: '撤销工具操作', exact: true }).click();
  await panel.getByRole('textbox', { name: '正文块 2', exact: true }).fill('作者修改后的研究说明。');
  await panel.getByRole('button', { name: '阅读预览', exact: true }).click();
  await expect(panel.getByRole('textbox', { name: '正文块 2', exact: true })).toHaveCount(0);
  await expect(panel.locator('.document-paper')).toContainText('作者修改后的研究说明。');
  await panel.getByRole('button', { name: '返回编辑', exact: true }).click();
  await panel.getByRole('button', { name: '专注写作', exact: true }).click();
  await expect(page.locator('.page-header')).toBeHidden();
  await page.screenshot({ path: info.outputPath('writing-focus.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await expect(page.locator('.page-header')).toBeVisible();
  state.conflict = true;
  await panel.getByRole('button', { name: '保存原稿新版本', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('原稿已更新');
  await expect(panel.getByRole('textbox', { name: '正文块 2', exact: true })).toHaveValue('作者修改后的研究说明。');
  state.conflict = false;
  await page.keyboard.press('Control+s');
  await expect(panel.getByRole('heading', { name: '作者原稿 · v2', exact: true })).toBeVisible();
  expect(state.saves).toBe(2);
  expect(state.errors).toEqual([]);
});

test('阅读矩阵保留作者修订、来源、导出与未保存保护', async ({ page }) => {
  const state = await fixture(page);
  await launch(page, '阅读与文献矩阵');
  const panel = page.getByRole('region', { name: '阅读摘记与比较', exact: true });
  await panel.getByText('文献矩阵 · 本页已保存摘记', { exact: true }).click();
  await expect(panel.locator('.reading-matrix-scroll')).toContainText('作者核实的实验方法');
  const csv = await downloadedText(page, () => panel.getByRole('button', { name: '导出矩阵 CSV' }).click());
  expect(csv).toContain('作者核实的实验方法'); expect(csv).toContain('作者修订'); expect(csv).toContain('file-0 / chunk-1: 自制原文引句');
  await select(page, '矩阵核对状态', '来源已变化');
  await expect(panel.locator('.reading-matrix-scroll')).toContainText('暂无匹配摘记');
  await select(page, '矩阵核对状态', '');
  await panel.getByRole('button', { name: '自制阅读文献', exact: true }).click();
  await panel.getByRole('textbox', { name: '作者理解', exact: true }).fill('作者待保存的笔记');
  await panel.getByRole('button', { name: '重新加载结果' }).click();
  await page.getByRole('button', { name: '继续编辑', exact: true }).click();
  await expect(panel.getByRole('textbox', { name: '作者理解', exact: true })).toHaveValue('作者待保存的笔记');
  await page.getByRole('button', { name: '退出', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('仍有未保存修改');
  await page.getByRole('button', { name: '继续编辑', exact: true }).click();
  expect(state.errors).toEqual([]);
});

test('反馈看板按已保存进度分组并定位处理记录', async ({ page }, info) => {
  const state = await fixture(page);
  await launch(page, '导师反馈与修改看板');
  const board = page.getByRole('region', { name: '本页修改看板' });
  await expect(board).toContainText('作者完成不代表导师确认');
  await board.getByRole('textbox', { name: '查找本页待办' }).fill('引用');
  await expect(board.getByRole('button', { name: '补充样本条件' })).toHaveCount(0);
  await board.getByRole('button', { name: '核对引用位置', exact: true }).click();
  await expect(page.getByRole('article', { name: '修改待办：核对引用位置', exact: true })).toBeInViewport();
  await board.getByRole('textbox', { name: '查找本页待办' }).fill('');
  await page.screenshot({ path: info.outputPath('feedback.png'), fullPage: true });
  expect(state.errors).toEqual([]);
});

test('审阅者工具只读，撤权后清除项目内容', async ({ page }) => {
  const state = await fixture(page, true);
  await launch(page, '原稿写作');
  const panel = page.getByRole('region', { name: '作者原稿', exact: true });
  await panel.getByText('查找替换与章节工具', { exact: true }).click();
  await expect(panel.getByRole('button', { name: '全部替换', exact: true })).toHaveCount(0);
  await expect(panel.getByRole('button', { name: '追加章节标题', exact: true })).toHaveCount(0);
  await page.keyboard.press('Control+s');
  expect(state.saves).toBe(0);
  await launch(page, '项目总览');
  state.revoked = true;
  await page.getByRole('button', { name: '刷新总览' }).click();
  await expect(page.getByRole('region', { name: '项目总览', exact: true })).toHaveCount(0);
  await expect(page.getByRole('region', { name: '作者原稿', exact: true })).toHaveCount(0);
  await expect(page.getByRole('alert')).toContainText('访问权限已撤回');
  expect(state.errors).toEqual([]);
});


test('空项目提供可执行入口，章节标题不生成正文', async ({ page }) => {
  const state = await fixture(page, false, true);
  const overview = page.getByRole('region', { name: '项目总览', exact: true });
  await expect(overview.getByRole('button', { name: '0 材料' })).toBeVisible();
  await expect(overview).toContainText('尚未填写研究问题');
  await overview.getByRole('button', { name: '进入整理研究材料' }).click();
  await expect(page.getByRole('region', { name: '材料', exact: true })).toContainText('上传第一份文献或研究材料');
  await launch(page, '原稿写作');
  const panel = page.getByRole('region', { name: '作者原稿', exact: true });
  await expect(panel).toContainText('从一个章节或一段正文开始');
  await panel.getByText('查找替换与章节工具', { exact: true }).click();
  await panel.getByRole('button', { name: '追加章节标题', exact: true }).click();
  await expect(panel.locator('.document-paper textarea')).toHaveCount(7);
  await expect(panel.getByRole('textbox', { name: /^正文块 / })).toHaveCount(0);
  await panel.getByRole('textbox', { name: '标题 1', exact: true }).fill('作者自定标题');
  await expect(panel.getByRole('button', { name: '撤销工具操作' })).toBeDisabled();
  expect(state.errors).toEqual([]);
});
