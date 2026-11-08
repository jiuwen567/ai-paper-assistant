import { expect, type Page } from '@playwright/test';
import type { Manuscript } from '@/features/manuscripts/types';
import type { FeedbackTask } from '@/features/feedback/types';
import type { ReadingRecord } from '@/features/reading/types';

// 全部内容为自制测试数据，接口由浏览器拦截，不调用模型或业务后端。
const listing = <T>(results: T[]) => ({ count: results.length, results, next: null, previous: null });
export async function fixture(page: Page, reviewer = false, empty = false) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const project = { id: 'project-one', name: '自制研究项目', paper_type: '课程论文', requirements: '核对来源与研究条件。', template: '', version: 1, role: reviewer ? 'reviewer' : 'author', is_owner: !reviewer, owner_name: 'test-author', policy: { id: 1, version: 1, source: '', source_version: '', notes: '', verified: false, allowed_actions: [], created_by: 'test-author', created_at: '2026-11-06T00:00:00Z' } };
  let manuscript: Manuscript = { version: 1, current_version: 1, research: { question: '不同条件如何影响结果？', method: '', result: '' }, blocks: [{ id: 'heading-1', text: '研究方法', heading_level: 1 }, { id: 'body-1', text: '方法 A+B 与 a+b 需要核对。', heading_level: 0 }], origin: 'edit', source: {}, created_at: '2026-11-06T00:00:00Z', created_by: 1 };
  if (empty) manuscript = { ...manuscript, version: 0, current_version: 0, blocks: [], research: { question: '', method: '', result: '' } };
  const tasks: FeedbackTask[] = ['todo', 'doing', 'completed'].map((status, index) => ({ id: `task-${index}`, feedback_id: 'feedback-1', candidate_id: null, original_location: null, current: { number: 1, title: ['补充样本条件', '核对引用位置', '说明研究限制'][index]!, instruction: '对照原始材料并记录理由。', status: status as 'todo', note: '', result_kind: 'pending', location: null, mentor_reports: [], created_by: 1, created_at: '2026-11-06T00:00:00Z' } }));
  const materials = Array.from({ length: 12 }, (_, i) => ({ id: `material-${i}`, title: i === 11 ? '跨页研究记录' : `自制文献 ${i + 1}`, category: i === 11 ? 'research' : 'literature', revision: 1, access_state: i === 10 ? 'withdrawn' : 'active', state_version: 1, latest_version: { id: `file-${i}`, material_id: `material-${i}`, number: 1, file_name: `sample-${i}.txt`, size: 1024 * (i + 1), sha256: '', status: 'available', usage_state: 'active', created_by: 1, error_message: '' } }));
  const record: ReadingRecord = { id: 'reading-1', job_id: 'job-1', purpose: 'reading', question: '核对方法', revision: 1, sources_changed: false, model_output: { documents: [{ version_id: 'file-0', title: '自制阅读文献', file_name: 'sample-0.txt', source_number: 1, source_scope: 'full_text', fields: Object.fromEntries(['subject', 'method', 'result', 'limitations', 'conditions', 'applicability'].map(field => [field, { status: 'found', text: field === 'method' ? '模型方法待核对' : '自制摘记', citations: [{ chunk_id: 'chunk-1', source_version_id: 'file-0', quote: '自制原文引句' }] }])) as ReadingRecord['model_output']['documents'][number]['fields'] }], comparison: null }, author_revision: { number: 1, edits: [{ version_id: 'file-0', field: 'method', text: '作者核实的实验方法' }], note: '', verified: true } };
  const state = { failMaterials: false, revoked: false, conflict: false, saves: 0, errors, record, project };
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname.replace('/api/v1/', ''), method = route.request().method();
    const reply = (json: unknown, status = 200) => route.fulfill({ status, json });
    if (path === 'auth/session/') return reply({ user: { id: 1, username: 'test-author' }, csrf_token: 'fixture-csrf' });
    if (path === 'auth/wechat/binding/') return reply({ bound: false });
    if (path === 'projects/') return reply(listing(state.revoked ? [] : [project]));
    if (path.startsWith('projects/project-one/') && state.revoked) return reply({ detail: '访问权限已撤回。' }, 403);
    if (path === 'projects/project-one/') return reply(project);
    const suffix = path.replace('projects/project-one/', '');
    if (suffix === 'manuscript/') {
      if (method === 'PUT') {
        state.saves++;
        if (state.conflict) return reply({ detail: '原稿已更新，请核对版本。' }, 409);
        const payload = route.request().postDataJSON();
        expect(payload.version).toBe(manuscript.version);
        expect(payload.request_key).toBeTruthy();
        manuscript = { ...manuscript, blocks: payload.blocks, research: payload.research, version: manuscript.version + 1, current_version: manuscript.version + 1 };
      }
      return reply(manuscript);
    }
    if (suffix === 'materials/') {
      if (empty) return reply(listing([]));
      if (state.failMaterials) return reply({ detail: '材料服务暂不可用。' }, 503);
      const number = Number(url.searchParams.get('page') || 1);
      return reply({ count: 12, results: materials.slice((number - 1) * 10, number * 10), next: number === 1 ? '?page=2' : null, previous: number > 1 ? '?page=1' : null });
    }
    if (/materials\/material-\d+\/versions\/$/.test(suffix)) return reply(listing([materials.find(item => suffix.includes(item.id + '/'))!.latest_version]));
    if (suffix === 'feedback-tasks/') return reply(listing((empty ? [] : tasks).filter(task => !url.searchParams.get('status') || task.current.status === url.searchParams.get('status'))));
    if (/^feedback-tasks\/task-\d+\/$/.test(suffix)) return reply(tasks.find(task => suffix.includes(task.id)));
    if (suffix === 'reading/') return reply(listing(empty ? [] : [record]));
    if (suffix === 'reading/reading-1/') return reply(record);
    if (suffix === 'export-templates/') return reply([]);
    if (suffix === 'disclosure/') return reply({ summary: {}, purposes: {}, manuscript_version: 1, facts_token: 'fixture', draft: '', current: null, stale: false });
    if (suffix === 'graph/paths/') return reply({ ...listing([]), revision: 0, applied_revision: 0, pending_events: 0, error_code: '', status: 'synced', page: 1 });
    return reply(listing([]));
  });
  await page.goto('/');
  await page.getByRole('button', { name: /自制研究项目.*作者|自制研究项目.*审阅者/ }).click();
  await expect(page.getByRole('region', { name: '项目总览', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '刷新总览' })).toBeEnabled();
  return state;
}
export async function launch(page: Page, name: string) {
  await page.getByRole('button', { name: '快速跳转', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name, exact: true }).click();
  await expect(page.locator('.workspace-launcher')).toBeHidden();
}
