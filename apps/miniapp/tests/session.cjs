const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { test } = require('node:test');

function moduleWithWx(wx) {
  const source = fs.readFileSync(path.join(__dirname, '../miniprogram/services/session.ts'), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const context = { exports: {}, wx, require: () => ({ API_BASE_URL: 'https://self-authored.test' }) };
  vm.runInNewContext(compiled, context);
  return context.exports;
}
function environment() {
  let saved;
  const requests = [];
  const wx = {
    getStorageSync: () => saved,
    removeStorageSync: () => { saved = undefined; },
    setStorageSync: (_, value) => { saved = value; },
    login: options => options.success({ code: 'self-authored-code' }),
    request: options => { requests.push(options); },
  };
  return { api: moduleWithWx(wx), requests, wx };
}

test('绑定前不保存会话；绑定后请求附带 token', async () => {
  const { api, requests } = environment();
  let login = api.login();
  await Promise.resolve();
  requests.shift().success({ statusCode: 200, data: {
    bound: false, binding_code: 'A'.repeat(24), expires_at: new Date(Date.now() + 300000).toISOString(),
  }});
  assert.equal((await login).bound, false);
  assert.equal(api.savedSession(), null);
  login = api.login();
  await Promise.resolve();
  requests.shift().success({ statusCode: 200, data: {
    bound: true, token: 'self-authored-token', expires_at: new Date(Date.now() + 300000).toISOString(),
    user: { id: 1, username: 'test' },
  }});
  await login;
  const pending = api.request('projects/');
  const request = requests.shift();
  assert.equal(request.header.Authorization, 'Bearer self-authored-token');
  request.success({ statusCode: 200, data: { results: [] } });
  await pending;
});

test('过期或撤销清除会话，网络失败可重新请求', async () => {
  const { api, requests, wx } = environment();
  wx.setStorageSync('', { token: 'expired', expires_at: '2000-01-01' });
  assert.equal(api.savedSession(), null);
  wx.setStorageSync('', { token: 'invalid', expires_at: 'invalid' });
  assert.equal(api.savedSession(), null);
  const pending = api.request('projects/');
  requests.shift().success({ statusCode: 403, data: { detail: '请重新登录' } });
  await assert.rejects(pending, /请重新登录/);
  assert.equal(api.savedSession(), null);
  const retry = api.request('projects/');
  requests.shift().fail();
  await assert.rejects(retry, /连接失败/);
});

test('上传携带会话且失败不伪装为成功', async () => {
  const { api, wx } = environment();
  wx.setStorageSync('', { token: 'upload-token', expires_at: new Date(Date.now() + 60000).toISOString() });
  let upload;
  wx.uploadFile = options => { upload = options; };
  const pending = api.uploadFile('projects/test/uploads/test/', '/self-authored.txt');
  assert.equal(upload.header.Authorization, 'Bearer upload-token');
  upload.success({ statusCode: 503, data: JSON.stringify({ detail: '存储暂不可用' }) });
  await assert.rejects(pending, /存储暂不可用/);
  const retry = api.uploadFile('projects/test/uploads/test/', '/self-authored.txt');
  upload.success({ statusCode: 200, data: JSON.stringify({ status: 'available' }) });
  assert.equal((await retry).status, 'available');
});
