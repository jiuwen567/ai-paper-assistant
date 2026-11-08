import { expect, test } from '@playwright/test';
import { fixture, launch } from './fixtures/workspace';

test('成员保存更新版本，不覆盖其他设置组件的草稿', async ({ page }) => {
  const state = await fixture(page);
  await launch(page, '项目设置');
  await page.getByRole('textbox', { name: '项目名称', exact: true }).fill('待保存项目名');
  await page.getByRole('textbox', { name: '使用要求', exact: true }).fill('待核对规则说明');
  await page.route('**/api/v1/projects/project-one/members/', async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    expect(route.request().postDataJSON().version).toBe(1);
    await route.fulfill({ json: { ...state.project, version: 2 } });
  });
  await page.getByRole('textbox', { name: '成员用户名', exact: true }).fill('test-reviewer');
  await page.getByRole('button', { name: '添加或更新成员', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '成员权限已保存' })).toBeVisible();
  await expect(page.getByRole('textbox', { name: '项目名称', exact: true })).toHaveValue('待保存项目名');
  await expect(page.getByRole('textbox', { name: '使用要求', exact: true })).toHaveValue('待核对规则说明');
  await page.route('**/api/v1/projects/project-one/', async route => {
    if (route.request().method() !== 'PATCH') return route.fallback();
    expect(route.request().postDataJSON().version).toBe(2);
    await route.fulfill({ status: 409, json: { detail: '项目版本冲突，请重新核对。' } });
  });
  await page.getByRole('button', { name: '保存项目', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('项目版本冲突');
  await expect(page.getByRole('textbox', { name: '项目名称', exact: true })).toHaveValue('待保存项目名');
  expect(state.errors).toEqual([]);
});

test('新建项目使用独立表单，保存后进入有 URL 的项目设置', async ({ page }, info) => {
  const state = await fixture(page);
  await launch(page, '项目设置');
  await page.getByRole('button', { name: '返回列表', exact: true }).click();
  const created = { ...state.project, id: 'created-project', name: '作者新项目' };
  await page.route('**/api/v1/projects/', async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    expect(route.request().postDataJSON()).toEqual({
      name: '作者新项目', paper_type: '', requirements: '', template: '',
    });
    await route.fulfill({ status: 201, json: created });
  });
  await page.route('**/api/v1/projects/created-project/**', route => {
    const url = route.request().url();
    if (url.endsWith('/created-project/')) return route.fulfill({ json: created });
    return route.fallback({ url: url.replace('/created-project/', '/project-one/') });
  });
  await page.getByRole('button', { name: '创建项目', exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/new$/);
  await page.getByRole('textbox', { name: '项目名称', exact: true }).fill('作者新项目');
  await page.getByRole('button', { name: '创建', exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/created-project\/settings$/);
  await expect(page.getByRole('textbox', { name: '项目名称', exact: true })).toHaveValue('作者新项目');
  await expect(page.getByRole('heading', { name: 'AI 辅助规则 · v1', exact: true })).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: '项目已保存。' })).toBeVisible();
  await page.screenshot({ path: info.outputPath('project-settings.png'), fullPage: true });
  expect(state.errors).toEqual([]);
});

test('重新加载项目发现撤权后返回列表并保留错误提示', async ({ page }) => {
  const state = await fixture(page);
  await launch(page, '项目设置');
  state.revoked = true;
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('alert')).toContainText('访问权限已撤回');
  await expect(page.getByRole('textbox', { name: '项目名称', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '刷新列表', exact: true }).click();
  await expect(page.getByText('还没有论文项目。')).toBeVisible();
  expect(state.errors).toEqual([]);
});

test('刷新项目列表期间导航呈现禁用状态，结束后可正常切换', async ({ page }) => {
  const state = await fixture(page);
  await launch(page, '项目设置');
  let release!: () => void;
  const refreshed = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/v1/projects/?page=1', async route => {
    await refreshed;
    await route.fulfill({ json: { count: 1, results: [state.project], next: null, previous: null } });
  });
  await page.route('**/api/v1/projects/project-one/', route => route.fulfill({ json: { ...state.project, version: 2 } }));
  await page.getByRole('button', { name: '保存项目', exact: true }).click();
  const mobile = page.getByRole('button', { name: '打开导航' });
  if (await mobile.isVisible()) await mobile.click();
  const menu = page.getByRole('menuitem', { name: '导出与披露', exact: true }).filter({ visible: true });
  try {
    await expect(menu).toHaveAttribute('aria-disabled', 'true');
  } finally {
    release();
  }
  await expect(menu).toHaveAttribute('aria-disabled', 'false');
  await menu.click();
  await expect(page.getByRole('heading', { name: '导出与披露', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'AI 使用说明', exact: true }).click();
  await expect(page.getByRole('region', { name: 'AI 使用与披露', exact: true })).toBeVisible();
  expect(state.errors).toEqual([]);
});
