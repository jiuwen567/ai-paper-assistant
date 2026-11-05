<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import LibraryPanel from "./LibraryPanel.vue";
import ReadingPanel from "./ReadingPanel.vue";
import ReviewPanel from "./ReviewPanel.vue";
import ExpressionPanel from "./ExpressionPanel.vue";
import ManuscriptPanel from "./ManuscriptPanel.vue";
import JobsPanel from "./JobsPanel.vue";
import MaterialsPanel from "./MaterialsPanel.vue";
import WechatBindingPanel from "./WechatBindingPanel.vue";
import {
  aiActions, ApiError, logout, request, session,
  type AIAction, type Member, type Page, type Policy, type Project, type ProjectFields, type User,
} from "./projects-api";

const user = ref<User | null>(null);
const initialized = ref(false);
const busy = ref(false);
const error = ref("");
const message = ref("");
const username = ref("");
const password = ref("");
const projects = ref<Page<Project> | null>(null);
const projectPage = ref(1);
const selected = ref<Project | null>(null);
const manuscriptDirty = ref(false);
const creating = ref(false);
const members = ref<Page<Member> | null>(null);
const memberPage = ref(1);
const history = ref<Page<Policy> | null>(null);
const historyPage = ref(1);
const memberName = ref("");
const memberRole = ref<Member["role"]>("reviewer");
const fields = reactive<ProjectFields>({ name: "", paper_type: "", requirements: "", template: "" });
const policy = reactive({ source: "", source_version: "", notes: "", verified: false, allowed_actions: [] as AIAction[] });
const canEdit = computed(() => creating.value || selected.value?.role === "author");
const basePath = () => `projects/${selected.value!.id}/`;
const roleName = (role: string) => role === "author" ? "作者" : "审阅者";

async function perform(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  message.value = "";
  try { await action(); }
  catch (cause) {
    error.value = cause instanceof Error ? cause.message : "连接失败，请重试。";
    if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
      creating.value = false;
      selected.value = null;
      members.value = null;
      history.value = null;
      projects.value = null;
      // 撤权或会话失效后清除旧数据，并重新确认身份。
      try { user.value = (await session()).user; } catch { user.value = null; }
    }
  } finally { busy.value = false; }
}

async function loadProjects(page = 1) {
  projects.value = await request<Page<Project>>(`projects/?page=${page}`);
  projectPage.value = page;
}
function setProject(project: Project) {
  selected.value = project;
  creating.value = false;
  Object.assign(fields, {
    name: project.name, paper_type: project.paper_type,
    requirements: project.requirements, template: project.template,
  });
  Object.assign(policy, {
    source: project.policy.source, source_version: project.policy.source_version,
    notes: project.policy.notes, verified: project.policy.verified,
    allowed_actions: [...project.policy.allowed_actions],
  });
}
async function loadMembers(page = 1) {
  members.value = await request<Page<Member>>(`${basePath()}members/?page=${page}`);
  memberPage.value = page;
}
async function loadHistory(page = 1) {
  history.value = await request<Page<Policy>>(`${basePath()}policies/?page=${page}`);
  historyPage.value = page;
}
async function openProject(id: string) {
  const project = await request<Project>(`projects/${id}/`);
  setProject(project);
  members.value = null;
  history.value = null;
  await loadMembers();
  await loadHistory();
}
function startCreate() {
  creating.value = true;
  selected.value = null;
  error.value = "";
  message.value = "";
  Object.assign(fields, { name: "", paper_type: "", requirements: "", template: "" });
}
async function saveProject() {
  const project = await request<Project>(
    creating.value ? "projects/" : basePath(), creating.value ? "POST" : "PATCH",
    { ...fields, ...(selected.value ? { version: selected.value.version } : {}) },
  );
  if (creating.value) setProject(project);
  else selected.value = project;
  await loadProjects();
  await loadMembers();
  await loadHistory();
  message.value = "项目已保存。";
}
async function savePolicy() {
  const project = await request<Project>(`${basePath()}policies/`, "POST", {
    ...policy, allowed_actions: policy.verified ? policy.allowed_actions : [], version: selected.value!.version,
  });
  selected.value = project;
  policy.allowed_actions = [...project.policy.allowed_actions];
  await loadHistory();
  message.value = "规则已保存为新版本。";
}
async function saveMember() {
  const project = await request<Project>(`${basePath()}members/`, "POST", {
    username: memberName.value, role: memberRole.value, version: selected.value!.version,
  });
  selected.value = project;
  memberName.value = "";
  await loadMembers();
  message.value = "成员权限已保存。";
}
async function removeMember(member: Member) {
  selected.value = await request<Project>(`${basePath()}members/${member.user_id}/`, "DELETE", {
    version: selected.value!.version,
  });
  await loadMembers();
  message.value = "成员访问权限已移除。";
}
async function initialize() {
  user.value = (await session()).user;
  initialized.value = true;
  if (user.value) await loadProjects();
}
async function signIn() {
  try { user.value = (await session("POST", { username: username.value, password: password.value })).user; }
  finally { password.value = ""; }
  await loadProjects();
}
async function signOut() {
  if (manuscriptDirty.value && !window.confirm("原稿仍有未保存修改，确认退出？")) return;
  await logout();
  user.value = null;
  selected.value = null;
  projects.value = null;
  members.value = null;
  history.value = null;
  creating.value = false;
}
async function returnToList() {
  if (manuscriptDirty.value && !window.confirm("放弃当前未保存的原稿修改并返回列表？")) return;
  selected.value = null; creating.value = false;
  await loadProjects();
}
onMounted(() => perform(initialize));
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <a class="brand" href="/">Paper Assistant</a>
      <nav aria-label="主导航">
        <a href="/" aria-current="page">我的论文</a>
        <a href="/environment">环境概览</a>
        <a href="/wechat">微信接入</a>
      </nav>
    </aside>
    <main :aria-busy="busy">
      <header class="page-header">
        <h1>我的论文</h1>
        <div v-if="user" class="actions">
          <span>{{ user.username }}</span>
          <button :disabled="busy" @click="perform(signOut)">退出</button>
        </div>
      </header>
      <WechatBindingPanel v-if="user" :key="user.id" @access-lost="cause => perform(async () => { throw cause; })" />
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="message" role="status">{{ message }}</p>
      <p v-if="busy" role="status">处理中…</p>
      <button v-if="!initialized" :disabled="busy" @click="perform(initialize)">重新连接</button>
      <form v-else-if="!user" class="editor login-form" @submit.prevent="perform(signIn)">
        <h2>登录</h2>
        <label>用户名<input v-model="username" autocomplete="username" required maxlength="150" /></label>
        <label>密码<input v-model="password" type="password" autocomplete="current-password" required maxlength="1024" /></label>
        <button :disabled="busy" type="submit">登录</button>
      </form>
      <template v-else-if="!selected && !creating">
        <div class="actions">
          <button :disabled="busy" @click="startCreate">创建项目</button>
          <button :disabled="busy" @click="perform(() => loadProjects())">刷新列表</button>
        </div>
        <p v-if="projects?.count === 0">还没有论文项目。</p>
        <ul class="project-list">
          <li v-for="project in projects?.results" :key="project.id">
            <button :disabled="busy" @click="perform(() => openProject(project.id))">
              <strong>{{ project.name }}</strong><span>{{ roleName(project.role) }}</span>
            </button>
          </li>
        </ul>
        <div v-if="projects && (projects.next || projects.previous)" class="actions" aria-label="项目分页">
          <button :disabled="busy || !projects.previous" @click="perform(() => loadProjects(projectPage - 1))">上一页</button>
          <span>{{ projectPage }}</span>
          <button :disabled="busy || !projects.next" @click="perform(() => loadProjects(projectPage + 1))">下一页</button>
        </div>
      </template>
      <template v-else>
        <div class="actions">
          <button :disabled="busy" @click="perform(returnToList)">返回列表</button>
          <button v-if="selected" :disabled="busy" @click="perform(() => openProject(selected!.id))">重新加载</button>
          <span v-if="selected">{{ roleName(selected.role) }}</span>
        </div>
        <form class="editor" @submit.prevent="perform(saveProject)">
          <h2>{{ creating ? "创建项目" : "项目设置" }}</h2>
          <fieldset :disabled="busy || !canEdit">
            <label>项目名称<input v-model="fields.name" required maxlength="120" /></label>
            <label>论文类型<input v-model="fields.paper_type" maxlength="80" /></label>
            <label>写作要求<textarea v-model="fields.requirements" rows="4" maxlength="20000" /></label>
            <label>模板<select v-model="fields.template"><option value="">暂不选择</option><option value="department-default">院系模板</option></select></label>
            <button v-if="canEdit" type="submit">{{ creating ? "创建" : "保存项目" }}</button>
          </fieldset>
        </form>
        <template v-if="selected">
          <MaterialsPanel :key="selected.id" :project="selected" :user-id="user!.id" @access-lost="cause => perform(async () => { throw cause; })" />
          <LibraryPanel :key="selected.id" :project="selected" @access-lost="cause => perform(async () => { throw cause; })" />
          <ReadingPanel :key="selected.id" :project="selected" @access-lost="cause => perform(async () => { throw cause; })" />
          <ManuscriptPanel :key="selected.id" :project="selected" @dirty-change="manuscriptDirty = $event" @access-lost="cause => perform(async () => { throw cause; })" />
          <ReviewPanel :key="selected.id" :project="selected" @access-lost="cause => perform(async () => { throw cause; })" />
          <ExpressionPanel :key="selected.id" :project="selected" @access-lost="cause => perform(async () => { throw cause; })" />
          <JobsPanel :key="selected.id" :project="selected" @access-lost="cause => perform(async () => { throw cause; })" />
          <form class="editor" @submit.prevent="perform(savePolicy)">
            <h2>AI 辅助规则 · v{{ selected.policy.version }}</h2>
            <fieldset :disabled="busy || !canEdit">
              <label>规则来源<input v-model="policy.source" maxlength="500" :required="policy.verified" /></label>
              <label>来源版本<input v-model="policy.source_version" maxlength="120" :required="policy.verified" /></label>
              <label>使用要求<textarea v-model="policy.notes" rows="3" maxlength="20000" /></label>
              <label class="check-label"><input v-model="policy.verified" type="checkbox" @change="policy.allowed_actions = []" />已核对学校或课程规则</label>
              <div class="action-options">
                <label v-for="(label, action) in aiActions" :key="action" class="check-label">
                  <input v-model="policy.allowed_actions" type="checkbox" :value="action" :disabled="!policy.verified" />{{ label }}
                </label>
              </div>
              <p v-if="!policy.verified" class="notice">{{ selected.policy.verified ? "保存后将关闭 AI 辅助。" : "规则未核对，AI 辅助已关闭。" }}</p>
              <button v-if="canEdit" type="submit">保存规则新版本</button>
            </fieldset>
          </form>
          <section>
            <h2>规则历史</h2>
            <details v-for="item in history?.results" :key="item.id" class="history-item">
              <summary>v{{ item.version }} · {{ item.verified ? "已核对" : "未核对" }} · {{ item.created_by }} · {{ new Date(item.created_at).toLocaleString("zh-CN") }}</summary>
              <p>来源：{{ item.source || "未填写" }} {{ item.source_version }}</p>
              <p class="preserve-lines">{{ item.notes || "未填写使用要求" }}</p>
              <p>允许：{{ item.allowed_actions.map(action => aiActions[action]).join("、") || "无" }}</p>
            </details>
            <div v-if="history && (history.next || history.previous)" class="actions" aria-label="规则分页">
              <button :disabled="busy || !history.previous" @click="perform(() => loadHistory(historyPage - 1))">上一页规则</button>
              <button :disabled="busy || !history.next" @click="perform(() => loadHistory(historyPage + 1))">下一页规则</button>
            </div>
          </section>
          <section>
            <h2>项目成员</h2>
            <p>{{ selected.owner_name }} · 创建者 / 作者</p>
            <ul class="member-list">
              <li v-for="member in members?.results" :key="member.user_id">
                <span>{{ member.username }} · {{ roleName(member.role) }}</span>
                <button v-if="selected.is_owner" :disabled="busy" :aria-label="`移除 ${member.username}`" @click="perform(() => removeMember(member))">移除</button>
              </li>
            </ul>
            <div v-if="members && (members.next || members.previous)" class="actions" aria-label="成员分页">
              <button :disabled="busy || !members.previous" @click="perform(() => loadMembers(memberPage - 1))">上一页成员</button>
              <button :disabled="busy || !members.next" @click="perform(() => loadMembers(memberPage + 1))">下一页成员</button>
            </div>
            <form v-if="selected.is_owner" class="editor" @submit.prevent="perform(saveMember)">
              <fieldset :disabled="busy">
                <label>成员用户名<input v-model="memberName" required maxlength="150" /></label>
                <label>成员角色<select v-model="memberRole"><option value="reviewer">审阅者（只读）</option><option value="author">作者（可编辑项目与规则）</option></select></label>
                <button type="submit">添加或更新成员</button>
              </fieldset>
            </form>
          </section>
        </template>
      </template>
    </main>
  </div>
</template>
