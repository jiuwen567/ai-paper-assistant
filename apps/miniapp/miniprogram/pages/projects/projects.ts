import { clearSession, login, request, RequestError, savedSession, type User } from "../../services/session";

type Project = { id: string; name: string; paper_type: string; requirements: string; role: string };
type Job = { id: string; status: string; progress: number; error_message: string };
type PageResult<T> = { results: T[]; next: string | null; previous: string | null };
const statusLabels: Record<string, string> = {
  queued: "等待执行", running: "执行中", succeeded: "成功", failed: "失败", cancelled: "已取消",
};
Component({
  data: {
    user: null as User | null, loading: false, error: "", bindingCode: "", expiresAt: "",
    projects: [] as Project[], project: null as Project | null, jobs: [] as Job[],
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
        if (error instanceof RequestError && error.status === 404) this.setData({ project: null, jobs: [], projects: [] });
      } finally { this.setData({ loading: false }); }
    },
    reset() {
      clearSession();
      this.setData({ user: null, projects: [], project: null, jobs: [], bindingCode: "", expiresAt: "" });
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
        this.setData({ project, jobs: [] });
        await this.loadJobs(1);
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
    back() { this.setData({ project: null, jobs: [] }); this.refresh(); },
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
