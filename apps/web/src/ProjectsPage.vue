<script setup lang="ts">
import { useConfirm } from "./ui/confirm";
const confirmDiscard = useConfirm();
import { computed, h, nextTick, onMounted, reactive, ref } from "vue";
import { NMenu, NDrawer, NDrawerContent } from "naive-ui";
import { BookOpen, FilePenLine, Files, MessageSquare, Network, Download, Settings, ListTodo, PanelLeft, ArrowLeft, FolderOpen, LogOut } from "@lucide/vue";
import UiTabs from "./ui/UiTabs.vue";
import LibraryPanel from "./LibraryPanel.vue";
import ReadingPanel from "./ReadingPanel.vue";
import ReviewPanel from "./ReviewPanel.vue";
import ExpressionPanel from "./ExpressionPanel.vue";
import DisclosurePanel from "./DisclosurePanel.vue";
import ExportPanel from "./ExportPanel.vue";
import CleanupPanel from "./CleanupPanel.vue";
import FeedbackPanel from "./FeedbackPanel.vue";
import ImpactPanel from "./ImpactPanel.vue";
import GraphPanel from "./GraphPanel.vue";
import ManuscriptPanel from "./ManuscriptPanel.vue";
import JobsPanel from "./JobsPanel.vue";
import MaterialsPanel from "./MaterialsPanel.vue";
import WechatBindingPanel from "./WechatBindingPanel.vue";
import {
  aiActions, ApiError, logout, request, session,
  type AIAction, type Member, type Page, type Policy, type Project, type ProjectFields, type User,
} from "./projects-api";

const workspace = ref('writing');
const mobileMenu = ref(false);
const workspaceItems = [
  { key: 'writing', label: '原稿写作', icon: FilePenLine },
  { key: 'materials', label: '材料与阅读', icon: Files },
  { key: 'review', label: '审阅与修订', icon: BookOpen },
  { key: 'feedback', label: '导师反馈', icon: MessageSquare },
  { key: 'evidence', label: '依据与变更', icon: Network },
  { key: 'delivery', label: '导出与披露', icon: Download },
  { key: 'jobs', label: '后台任务', icon: ListTodo },
  { key: 'settings', label: '项目设置', icon: Settings },
];
const menuOptions = workspaceItems.map(item => ({ ...item, icon: () => h(item.icon, { size: 18, strokeWidth: 1.6 }) }));
const workspaceTitle = computed(() => workspaceItems.find(item => item.key === workspace.value)?.label);
const materialTab = ref('files'), reviewTab = ref('diagnosis'), evidenceTab = ref('graph'), deliveryTab = ref('export');
function navigate(key: string) { workspace.value = key; mobileMenu.value = false; window.scrollTo({ top: 0 }); }
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
const disclosureDirty = ref(false);
const feedbackDirty = ref(false);
const graphDirty = ref(false);
const impactDirty = ref(false);
const exportDirty = ref(false);
const cleanupBusy = ref(false);
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
async function openProject(id: string, target = "writing") {
  const project = await request<Project>(`projects/${id}/`);
  setProject(project);
  navigate(target);
  members.value = null;
  history.value = null;
  await loadMembers();
  await loadHistory();
}
function startCreate() {
  navigate('settings');
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
  if ((manuscriptDirty.value || disclosureDirty.value || feedbackDirty.value || graphDirty.value || impactDirty.value || exportDirty.value) && !(await confirmDiscard("仍有未保存修改，确认退出？"))) return;
  await logout();
  user.value = null;
  selected.value = null;
  projects.value = null;
  members.value = null;
  history.value = null;
  creating.value = false;
}
async function afterCleanup(scope: string, id: string) {
  if (selected.value?.id !== id) { await loadProjects(); return; }
  selected.value = null; members.value = null; history.value = null;
  await nextTick();
  await loadProjects();
  if (scope === "material" && id) await openProject(id, "settings");
}
async function returnToList() {
  if ((manuscriptDirty.value || disclosureDirty.value || feedbackDirty.value || graphDirty.value || impactDirty.value || exportDirty.value) && !(await confirmDiscard("放弃当前未保存修改并返回列表？"))) return;
  selected.value = null; creating.value = false;
  await loadProjects();
}
onMounted(() => perform(initialize));
</script>

<template>
  <div class="shell">
    <aside class="sidebar desktop-sidebar">
      <a class="brand" href="/"><BookOpen :size="22" :stroke-width="1.6" /><span>Paper Assistant<small>论文工作台</small></span></a>
      <template v-if="selected">
        <NButton class="project-back" @click="perform(returnToList)" :disabled="(busy || cleanupBusy)"><ArrowLeft :size="16" />我的论文</NButton>
        <div class="sidebar-project">{{ selected.name }}<small>{{ roleName(selected.role) }}</small></div>
        <NMenu :value="workspace" :options="menuOptions" :disabled="cleanupBusy" :indent="16" aria-label="工作区导航" @update:value="navigate" />
      </template>
      <nav v-else aria-label="主导航"><a href="/" aria-current="page"><FolderOpen :size="18" />我的论文</a></nav>
      <div class="sidebar-footer"><a href="/wechat">微信接入</a><a href="/environment">环境概览</a><span v-if="user">{{ user.username }}</span></div>
    </aside>
    <NDrawer v-model:show="mobileMenu" placement="left" :width="280"><NDrawerContent title="论文工作台" closable><NMenu v-if="selected" :value="workspace" :options="menuOptions" :disabled="cleanupBusy" @update:value="navigate" /><NButton v-if="selected" @click="mobileMenu = false; perform(returnToList)">返回列表</NButton><nav><a href="/wechat">微信接入</a><a href="/environment">环境概览</a></nav></NDrawerContent></NDrawer>
    <main :aria-busy="busy" :class="{ 'writing-workspace': selected && workspace === 'writing', 'login-workspace': !user }">
      <header class="page-header">
        <div class="header-title"><NButton class="mobile-menu" aria-label="打开导航" @click="mobileMenu = true"><PanelLeft :size="20" /></NButton><span>{{ selected ? selected.name : '我的论文' }}</span><span v-if="selected" class="breadcrumb-divider">/</span><h1>{{ selected ? workspaceTitle : creating ? '创建项目' : '项目' }}</h1></div>
        <div v-if="user" class="actions"><NTag v-if="selected" size="small" :bordered="false">{{ roleName(selected.role) }}</NTag><NButton @click="perform(signOut)" :disabled="(busy || cleanupBusy)"><LogOut :size="15" />退出</NButton></div>
      </header>
      <div class="workspace-content">
      <NAlert type="error" :show-icon="false" v-if="error" role="alert">{{ error }}</NAlert>
      <p v-if="message" role="status">{{ message }}</p>
      <p v-if="busy" role="status">处理中…</p>
      <NButton v-if="!initialized" @click="perform(initialize)" :disabled="(busy || cleanupBusy)">重新连接</NButton>
      <form v-else-if="!user" class="editor login-form" @submit.prevent="perform(signIn)">
        <BookOpen :size="28" :stroke-width="1.5" /><h2>登录论文工作台</h2><p class="notice">继续你的研究与写作。</p>
        <label>用户名<UiInput v-model="username" autocomplete="username" required maxlength="150" :aria-label="'用户名'" /></label>
        <label>密码<UiInput v-model="password" type="password" autocomplete="current-password" required maxlength="1024" :aria-label="'密码'" /></label>
        <NButton attr-type="submit" :disabled="(busy || cleanupBusy)" type="primary">登录</NButton>
      </form>
      <template v-else-if="!selected && !creating">
        <div class="section-heading"><div><h2>我的论文</h2><p class="notice">从资料整理到原稿修订。</p></div><div class="actions">
          <NButton @click="startCreate" :disabled="(busy || cleanupBusy)" type="primary">创建项目</NButton>
          <NButton @click="perform(() => loadProjects())" :disabled="(busy || cleanupBusy)">刷新列表</NButton>
        </div></div>
        <p v-if="projects?.count === 0">还没有论文项目。</p>
        <ul class="project-list">
          <li v-for="project in projects?.results" :key="project.id">
            <NButton @click="perform(() => openProject(project.id))" :disabled="(busy || cleanupBusy)">
              <FolderOpen :size="22" :stroke-width="1.5" /><div class="project-list-title"><strong>{{ project.name }}</strong><small>{{ project.paper_type || "论文项目" }}</small></div><NTag size="small" :bordered="false">{{ roleName(project.role) }}</NTag>
            </NButton>
          </li>
        </ul>
        <div v-if="projects && (projects.next || projects.previous)" class="actions" aria-label="项目分页">
          <NButton @click="perform(() => loadProjects(projectPage - 1))" :disabled="(busy || !projects.previous)">上一页</NButton>
          <span>{{ projectPage }}</span>
          <NButton @click="perform(() => loadProjects(projectPage + 1))" :disabled="(busy || !projects.next)">下一页</NButton>
        </div>
      </template>
      <template v-else>
        <div v-show="workspace === 'settings'" class="actions">
          <NButton @click="perform(returnToList)" :disabled="(busy || cleanupBusy)">返回列表</NButton>
          <NButton v-if="selected" @click="perform(() => openProject(selected!.id, workspace))" :disabled="(busy || cleanupBusy)">重新加载</NButton>
          <span v-if="selected">{{ roleName(selected.role) }}</span>
        </div>
        <form v-show="creating || workspace === 'settings'" class="editor settings-form" @submit.prevent="perform(saveProject)">
          <h2>{{ creating ? "创建项目" : "项目设置" }}</h2>
          <fieldset :disabled="busy || cleanupBusy || !canEdit">
            <label>项目名称<UiInput v-model="fields.name" required maxlength="120" :disabled="(busy || cleanupBusy || !canEdit)" :aria-label="'项目名称'" /></label>
            <label>论文类型<UiInput v-model="fields.paper_type" maxlength="80" :disabled="(busy || cleanupBusy || !canEdit)" :aria-label="'论文类型'" /></label>
            <label>写作要求<UiInput v-model="fields.requirements" rows="4" maxlength="20000" :disabled="(busy || cleanupBusy || !canEdit)" type="textarea" :aria-label="'写作要求'" /></label>
            <label>模板<UiSelect v-model="fields.template" :disabled="(busy || cleanupBusy || !canEdit)" :options="[({ value: '', label: '暂不选择' }), ({ value: 'department-default', label: '中文论文示例模板（自制）' })]" :aria-label="'模板'" /></label>
            <NButton v-if="canEdit" attr-type="submit" :disabled="(busy || cleanupBusy || !canEdit)" type="primary">{{ creating ? "创建" : "保存项目" }}</NButton>
          </fieldset>
        </form>
        <div v-if="selected" :inert="cleanupBusy">
          <div v-show="workspace === 'materials'" class="workspace-panel">
            <UiTabs class="workspace-tabs" v-model="materialTab" :options="[{ value: 'files', label: '文件材料' }, { value: 'library', label: '检索与证据卡' }, { value: 'reading', label: 'AI 阅读' }]" />
          <MaterialsPanel v-show="materialTab === 'files'" :key="selected.id" :project="selected" :user-id="user!.id" @access-lost="cause => perform(async () => { throw cause; })" />
          <LibraryPanel v-show="materialTab === 'library'" :key="selected.id" :project="selected" @access-lost="cause => perform(async () => { throw cause; })" />
          <ReadingPanel v-show="materialTab === 'reading'" :key="selected.id" :project="selected" @access-lost="cause => perform(async () => { throw cause; })" />
          </div>
          <div v-show="workspace === 'review'" class="workspace-panel">
            <UiTabs class="workspace-tabs" v-model="reviewTab" :options="[{ value: 'diagnosis', label: '原稿诊断' }, { value: 'expression', label: '表达建议' }]" />
          <ReviewPanel v-show="reviewTab === 'diagnosis'" :key="selected.id" :project="selected" @access-lost="cause => perform(async () => { throw cause; })" />
          <ExpressionPanel v-show="reviewTab === 'expression'" :key="selected.id" :project="selected" @access-lost="cause => perform(async () => { throw cause; })" />
          </div>
          <div v-show="workspace === 'evidence'" class="workspace-panel">
            <UiTabs class="workspace-tabs" v-model="evidenceTab" :options="[{ value: 'graph', label: '依据关系' }, { value: 'impact', label: '变更影响' }]" />
          <GraphPanel v-show="evidenceTab === 'graph'" :key="selected.id" :project="selected" @dirty-change="graphDirty = $event" @access-lost="cause => perform(async () => { throw cause; })" />
          <ImpactPanel v-show="evidenceTab === 'impact'" :key="selected.id" :project="selected" @dirty-change="impactDirty = $event" @access-lost="cause => perform(async () => { throw cause; })" />
          </div>
          <div v-show="workspace === 'delivery'" class="workspace-panel">
            <UiTabs class="workspace-tabs" v-model="deliveryTab" :options="[{ value: 'export', label: '导出文档' }, { value: 'disclosure', label: 'AI 使用说明' }]" />
          <ExportPanel v-show="deliveryTab === 'export'" :key="selected.id" :project="selected" :manuscript-dirty="manuscriptDirty" :disclosure-dirty="disclosureDirty" @dirty-change="exportDirty = $event" @access-lost="cause => perform(async () => { throw cause; })" />
          <DisclosurePanel v-show="deliveryTab === 'disclosure'" :key="selected.id" :project="selected" @dirty-change="disclosureDirty = $event" @access-lost="cause => perform(async () => { throw cause; })" />
          </div>
          <ManuscriptPanel v-show="workspace === 'writing'" :key="selected.id" :project="selected" @dirty-change="manuscriptDirty = $event" @access-lost="cause => perform(async () => { throw cause; })" />
          <FeedbackPanel v-show="workspace === 'feedback'" :key="selected.id" :project="selected" @dirty-change="feedbackDirty = $event" @access-lost="cause => perform(async () => { throw cause; })" />
          <JobsPanel v-show="workspace === 'jobs'" :key="selected.id" :project="selected" @access-lost="cause => perform(async () => { throw cause; })" />
          <div v-show="workspace === 'settings'" class="settings-content">
          <form class="editor" @submit.prevent="perform(savePolicy)">
            <h2>AI 辅助规则 · v{{ selected.policy.version }}</h2>
            <fieldset :disabled="busy || cleanupBusy || !canEdit">
              <label>规则来源<UiInput v-model="policy.source" maxlength="500" :required="policy.verified" :disabled="(busy || cleanupBusy || !canEdit)" :aria-label="'规则来源'" /></label>
              <label>来源版本<UiInput v-model="policy.source_version" maxlength="120" :required="policy.verified" :disabled="(busy || cleanupBusy || !canEdit)" :aria-label="'来源版本'" /></label>
              <label>使用要求<UiInput v-model="policy.notes" rows="3" maxlength="20000" :disabled="(busy || cleanupBusy || !canEdit)" type="textarea" :aria-label="'使用要求'" /></label>
              <UiCheckbox v-model="policy.verified" @change="policy.allowed_actions = []" :disabled="(busy || cleanupBusy || !canEdit)" :aria-label="'已核对学校或课程规则'" class="check-label">已核对学校或课程规则</UiCheckbox>
              <div class="action-options">
                <UiCheckbox v-model="policy.allowed_actions" :value="action" :disabled="(busy || cleanupBusy || !canEdit) || (!policy.verified)" :aria-label="String(label)" v-for="(label, action) in aiActions" :key="action" class="check-label">{{ label }}</UiCheckbox>
              </div>
              <p v-if="!policy.verified" class="notice">{{ selected.policy.verified ? "保存后将关闭 AI 辅助。" : "规则未核对，AI 辅助已关闭。" }}</p>
              <NButton v-if="canEdit" attr-type="submit" :disabled="(busy || cleanupBusy || !canEdit)" type="primary">保存规则新版本</NButton>
            </fieldset>
          </form>
          <section>
            <h2>规则历史</h2>
            <UiDisclosure v-for="item in history?.results" :key="item.id" class="history-item">
              <template #header>v{{ item.version }} · {{ item.verified ? "已核对" : "未核对" }} · {{ item.created_by }} · {{ new Date(item.created_at).toLocaleString("zh-CN") }}</template>
              <p>来源：{{ item.source || "未填写" }} {{ item.source_version }}</p>
              <p class="preserve-lines">{{ item.notes || "未填写使用要求" }}</p>
              <p>允许：{{ item.allowed_actions.map(action => aiActions[action]).join("、") || "无" }}</p>
            </UiDisclosure>
            <div v-if="history && (history.next || history.previous)" class="actions" aria-label="规则分页">
              <NButton @click="perform(() => loadHistory(historyPage - 1))" :disabled="(busy || !history.previous)">上一页规则</NButton>
              <NButton @click="perform(() => loadHistory(historyPage + 1))" :disabled="(busy || !history.next)">下一页规则</NButton>
            </div>
          </section>
          <section>
            <h2>项目成员</h2>
            <p>{{ selected.owner_name }} · 创建者 / 作者</p>
            <ul class="member-list">
              <li v-for="member in members?.results" :key="member.user_id">
                <span>{{ member.username }} · {{ roleName(member.role) }}</span>
                <NButton v-if="selected.is_owner" :aria-label="`移除 ${member.username}`" @click="perform(() => removeMember(member))" :disabled="(busy || cleanupBusy)">移除</NButton>
              </li>
            </ul>
            <div v-if="members && (members.next || members.previous)" class="actions" aria-label="成员分页">
              <NButton @click="perform(() => loadMembers(memberPage - 1))" :disabled="(busy || !members.previous)">上一页成员</NButton>
              <NButton @click="perform(() => loadMembers(memberPage + 1))" :disabled="(busy || !members.next)">下一页成员</NButton>
            </div>
            <form v-if="selected.is_owner" class="editor" @submit.prevent="perform(saveMember)">
              <fieldset :disabled="busy || cleanupBusy">
                <label>成员用户名<UiInput v-model="memberName" required maxlength="150" :disabled="(busy || cleanupBusy)" :aria-label="'成员用户名'" /></label>
                <label>成员角色<UiSelect v-model="memberRole" :disabled="(busy || cleanupBusy)" :options="[({ value: 'reviewer', label: '审阅者（只读）' }), ({ value: 'author', label: '作者（可编辑项目与规则）' })]" :aria-label="'成员角色'" /></label>
                <NButton attr-type="submit" :disabled="(busy || cleanupBusy)" type="primary">添加或更新成员</NButton>
              </fieldset>
            </form>
          </section>
          </div>
        </div>
      </template>
      <div v-show="!selected || workspace === 'settings'" class="account-settings"><WechatBindingPanel v-if="user" :key="user.id" @access-lost="cause => perform(async () => { throw cause; })" /><CleanupPanel v-if="user && !creating" :key="user.id" :project="selected" :disabled="busy" :has-draft="manuscriptDirty || disclosureDirty || feedbackDirty || graphDirty || impactDirty || exportDirty" @deleting="cleanupBusy = $event" @deleted="(scope, id) => perform(() => afterCleanup(scope, id))" @access-lost="cause => perform(async () => { throw cause; })" />
      </div>
      </div>
    </main>
  </div>
</template>
