import { clearSession, downloadDocument, login, request, RequestError, savedSession, uploadFile, type User } from "../../services/session";

type Project = { id: string; name: string; paper_type: string; requirements: string; role: string };
type Material = { id: string; title: string; category: string; revision: number };
type Version = { id: string; material_id: string; created_by: number; number: number; file_name: string; status: string; error_message: string; canOpen?: boolean; label?: string };
type Job = { id: string; status: string; progress: number; error_message: string };
type PageResult<T> = { results: T[]; next: string | null; previous: string | null };
const statusLabels: Record<string, string> = {
  queued: "等待执行", running: "执行中", succeeded: "成功", failed: "失败", cancelled: "已取消",
};
Component({
  data: {
    user: null as User | null, loading: false, error: "", bindingCode: "", expiresAt: "",
    projects: [] as Project[], project: null as Project | null, jobs: [] as Job[],
    materials: [] as Material[], material: null as Material | null, versions: [] as Version[],
    materialPage: 1, materialNext: false, materialPrevious: false,
    versionPage: 1, versionNext: false, versionPrevious: false,
    categoryIndex: 0, categories: ["文献", "研究材料", "作者原稿"],
    pendingIntent: null as { payload: Record<string, unknown>; filePath: string } | null,
    pendingUpload: null as { versionId: string; filePath: string } | null,
    page: 1, hasNext: false, hasPrevious: false, jobPage: 1, jobNext: false, jobPrevious: false,
  },
  lifetimes: {
    attached() {
      const session = savedSession();
      this.setData({ user: session?.user ?? null });
      if (session) this.refresh();
    },
  },
  pageLifetimes: {
    show() {
      if (!savedSession()) {
        if (this.data.user) this.reset();
      } else if (this.data.project) this.refreshJobs();
      else this.refresh();
    },
  },
  methods: {
    async perform(action: () => Promise<void>) {
      if (this.data.loading) return;
      this.setData({ loading: true, error: "" });
      try { await action(); }
      catch (error) {
        this.setData({ error: error instanceof Error ? error.message : "请求失败，请重试。" });
        if (error instanceof RequestError && [401, 403].includes(error.status)) this.reset();
        if (error instanceof RequestError && error.status === 404) this.setData({ project: null, jobs: [], projects: [], materials: [], material: null, versions: [], pendingUpload: null, pendingIntent: null });
      } finally { this.setData({ loading: false }); }
    },
    reset() {
      clearSession();
      this.setData({ user: null, projects: [], project: null, jobs: [], materials: [], material: null, versions: [], pendingUpload: null, pendingIntent: null, bindingCode: "", expiresAt: "" });
    },
    signIn() {
      this.perform(async () => {
        this.reset();
        const result = await login();
        if (result.bound) {
          this.setData({ user: result.user!, bindingCode: "", expiresAt: "" });
          await this.loadProjects(1);
        } else {
          this.setData({ bindingCode: result.binding_code!, expiresAt: result.expires_at });
        }
      });
    },
    copyCode() { wx.setClipboardData({ data: this.data.bindingCode }); },
    async loadProjects(page: number) {
      const result = await request<PageResult<Project>>(`projects/?page=${page}`);
      this.setData({ projects: result.results, page, hasNext: !!result.next, hasPrevious: !!result.previous });
    },
    refresh() { this.perform(() => this.loadProjects(this.data.page)); },
    nextPage() { this.perform(() => this.loadProjects(this.data.page + 1)); },
    previousPage() { this.perform(() => this.loadProjects(this.data.page - 1)); },
    selectProject(event: WechatMiniprogram.TouchEvent) {
      this.perform(async () => {
        const project = await request<Project>(`projects/${event.currentTarget.dataset.id}/`);
        this.setData({ project, jobs: [], materials: [], material: null, versions: [], pendingUpload: null, pendingIntent: null });
        await this.loadJobs(1);
        await this.loadMaterials(1);
      });
    },
    async loadJobs(page: number) {
      const result = await request<PageResult<Job>>(`projects/${this.data.project!.id}/jobs/?page=${page}`);
      this.setData({ jobs: result.results.map(job => ({ ...job, status: statusLabels[job.status] || job.status })),
        jobPage: page, jobNext: !!result.next, jobPrevious: !!result.previous });
    },
    refreshJobs() { this.perform(() => this.loadJobs(this.data.jobPage)); },
    nextJobs() { this.perform(() => this.loadJobs(this.data.jobPage + 1)); },
    previousJobs() { this.perform(() => this.loadJobs(this.data.jobPage - 1)); },
    async loadMaterials(page: number) {
      const result = await request<PageResult<Material>>(`projects/${this.data.project!.id}/materials/?page=${page}`);
      const updated = result.results.find(item => item.id === this.data.material?.id);
      this.setData({ materials: result.results, materialPage: page, materialNext: !!result.next,
        materialPrevious: !!result.previous, ...(updated ? { material: updated } : {}) });
    },
    refreshMaterials() { this.perform(() => this.loadMaterials(this.data.materialPage)); },
    nextMaterials() { this.perform(() => this.loadMaterials(this.data.materialPage + 1)); },
    previousMaterials() { this.perform(() => this.loadMaterials(this.data.materialPage - 1)); },
    async loadVersions(page = 1) {
      const result = await request<PageResult<Version>>(`projects/${this.data.project!.id}/materials/${this.data.material!.id}/versions/?page=${page}`);
      const labels: Record<string, string> = { uploading: "等待上传", validating: "上传校验中", available: "可用", failed: "失败" };
      this.setData({ versions: result.results.map(item => ({ ...item, label: labels[item.status],
        canOpen: /\.(pdf|docx)$/i.test(item.file_name) })),
        versionPage: page, versionNext: !!result.next, versionPrevious: !!result.previous });
    },
    selectMaterial(event: WechatMiniprogram.TouchEvent) {
      const material = this.data.materials.find(item => item.id === event.currentTarget.dataset.id);
      if (material) { this.setData({ material, versions: [], pendingUpload: null, pendingIntent: null }); this.perform(() => this.loadVersions()); }
    },
    nextVersions() { this.perform(() => this.loadVersions(this.data.versionPage + 1)); },
    previousVersions() { this.perform(() => this.loadVersions(this.data.versionPage - 1)); },
    newMaterial() { this.setData({ material: null, versions: [], pendingUpload: null, pendingIntent: null }); },
    changeCategory(event: WechatMiniprogram.PickerChange) { this.setData({ categoryIndex: Number(event.detail.value) }); },
    uploadMaterial(event: WechatMiniprogram.TouchEvent) {
      this.perform(async () => {
        const chosen = await new Promise<{ name: string; size: number; path: string } | null>((resolve, reject) => wx.chooseMessageFile({
          count: 1, type: "file", extension: ["pdf", "docx", "csv", "txt"],
          success: result => resolve(result.tempFiles[0] ?? null),
          fail: result => result.errMsg.includes("cancel") ? resolve(null) : reject(new Error("选择文件失败。")),
        }));
        if (!chosen) return;
        if (!chosen.size || chosen.size > 20 * 1024 * 1024) throw new Error("文件不能为空且不能超过 20 MB。");
        const versionId = event.currentTarget.dataset.version as string | undefined;
        if (!versionId) {
          const payload: Record<string, unknown> = {
            request_key: `mini-${Date.now()}-${Math.random().toString(36).slice(2)}`,
            title: this.data.material?.title ?? chosen.name.slice(0, 200),
            category: this.data.material?.category ?? ["literature", "research", "manuscript"][this.data.categoryIndex],
            file_name: chosen.name, size: chosen.size,
            ...(this.data.material ? { material_id: this.data.material.id, base_revision: this.data.material.revision } : {}),
          };
          this.setData({ pendingIntent: { payload, filePath: chosen.path }, pendingUpload: null });
        } else this.setData({ pendingUpload: { versionId, filePath: chosen.path }, pendingIntent: null });
        await this.sendUpload();
      });
    },
    async sendUpload() {
      if (this.data.pendingIntent) {
        const intent = this.data.pendingIntent;
        const version = await request<Version>(`projects/${this.data.project!.id}/uploads/`, "POST", intent.payload);
        this.setData({ pendingUpload: { versionId: version.id, filePath: intent.filePath }, pendingIntent: null });
      }
      const upload = this.data.pendingUpload!;
      const result = await uploadFile<Version>(`projects/${this.data.project!.id}/uploads/${upload.versionId}/`, upload.filePath);
      this.setData({ pendingUpload: null, pendingIntent: null });
      await this.loadMaterials(1);
      const material = this.data.materials.find(item => item.id === result.material_id) ?? this.data.material;
      if (material) { this.setData({ material }); await this.loadVersions(); }
      wx.showToast({ title: "版本已保存", icon: "success" });
    },
    retryUpload() { this.perform(() => this.sendUpload()); },
    download(event: WechatMiniprogram.TouchEvent) {
      const version = this.data.versions.find(item => item.id === event.currentTarget.dataset.id);
      if (version?.canOpen) this.perform(() => downloadDocument(
        `projects/${this.data.project!.id}/files/${version.id}/`,
        version.file_name.toLowerCase().endsWith(".pdf") ? "pdf" : "docx",
      ));
    },
    back() { this.setData({ project: null, jobs: [], material: null, materials: [], versions: [], pendingUpload: null, pendingIntent: null }); this.refresh(); },
    signOut() {
      this.perform(async () => {
        await request("auth/wechat/logout/", "POST");
        this.reset();
      });
    },
    unbind() {
      wx.showModal({
        title: "解除微信绑定", content: "解绑后小程序登录立即失效，项目资料保留。",
        success: result => { if (result.confirm) this.perform(async () => {
          await request("auth/wechat/unbind/", "POST"); this.reset();
        }); },
      });
    },
  },
});
