import { expect, test } from '@playwright/test';
import { fixture, launch } from './fixtures/workspace';

test('工作区 URL 支持刷新、前进后退和标签定位', async ({ page }) => {
  const state = await fixture(page);
  await launch(page, '阅读与文献矩阵');
  await expect(page).toHaveURL(/\/projects\/project-one\/materials\?tab=reading$/);
  await page.reload();
  await expect(page.getByRole('region', { name: '阅读摘记与比较', exact: true })).toBeVisible();
  await launch(page, '原稿写作');
  await expect(page).toHaveURL(/\/projects\/project-one\/writing$/);
  await page.goBack();
  await expect(page.getByRole('region', { name: '阅读摘记与比较', exact: true })).toBeVisible();
  await page.goForward();
  await expect(page.getByRole('region', { name: '作者原稿', exact: true })).toBeVisible();
  expect(state.errors).toEqual([]);
});

test('切换工作区保留草稿，返回项目列表可取消或确认', async ({ page }) => {
  const state = await fixture(page);
  await launch(page, '原稿写作');
  const editor = page.getByRole('textbox', { name: '正文块 2', exact: true });
  await editor.fill('尚未保存的作者原稿。');
  await launch(page, '项目设置');
  await launch(page, '原稿写作');
  await expect(editor).toHaveValue('尚未保存的作者原稿。');
  await launch(page, '项目设置');
  await page.getByRole('button', { name: '返回列表', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('未保存修改');
  await page.getByRole('button', { name: '继续编辑', exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await page.getByRole('button', { name: '返回列表', exact: true }).click();
  await page.getByRole('button', { name: '放弃修改', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('button', { name: /自制研究项目.*作者/ })).toBeVisible();
  expect(state.saves).toBe(0);
  expect(state.errors).toEqual([]);
});

test('项目设置草稿保护覆盖浏览器后退，非法工作区回到总览', async ({ page }) => {
  const state = await fixture(page);
  await launch(page, '项目设置');
  await page.getByRole('textbox', { name: '项目名称', exact: true }).fill('尚未保存的项目名');
  await page.goBack();
  await expect(page.getByRole('region', { name: '项目总览', exact: true })).toBeVisible();
  // 同项目内后退保留草稿；再后退才离开项目。
  const back = page.goBack();
  await expect(page.getByRole('dialog')).toContainText('未保存修改');
  await page.getByRole('button', { name: '继续编辑', exact: true }).click();
  await back;
  await launch(page, '项目设置');
  await expect(page.getByRole('textbox', { name: '项目名称', exact: true })).toHaveValue('尚未保存的项目名');
  await page.getByRole('button', { name: '返回列表', exact: true }).click();
  await page.getByRole('button', { name: '放弃修改', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  // 页面重载使用明确的测试导航，不以未保存草稿作为已保存数据。
  await page.goto('/projects/project-one/unknown');
  await expect(page).toHaveURL(/\/overview$/);
  await expect(page.getByRole('region', { name: '项目总览', exact: true })).toBeVisible();
  expect(state.errors).toEqual([]);
});
