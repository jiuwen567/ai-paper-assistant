import { request, RequestError } from "../../services/session";
type Project = { id: string; name: string; role: string; policy: { version: number; allowed_actions: string[] } };
type DiffPart = { kind: string; before: string; after: string };
type Suggestion = {
  id: string; manuscript_version: number; manuscript_text: string; input_changed: boolean;
  model_output: { quote: string; start: number; end: number; replacement: string; reason: string; kind: string; guard_reasons: string[]; citations: { chunk_id: string; quote: string; source_scope: string }[] };
  diff: DiffPart[];
  decision: { action: string; text: string; reason: string; manuscript_version: number | null } | null;
  label?: string;
};
type Result = { results: Suggestion[]; next: string | null; previous: string | null };
type Context = { chunk: { text: string; anchor: { kind: string; page?: number; paragraph?: number; record?: number; line?: number } }; context: { id: string; text: string }[] };
const labels: Record<string, string> = { accepted: "已接受", edited: "编辑后接受", rejected: "已拒绝" };
const states = ["", "pending", "accepted", "edited", "rejected"];
const newKey = () => `mini-expression-${Date.now()}-${Math.random().toString(36).slice(2)}`;
Component({
  data: {
    projectId: "", project: null as Project | null, suggestions: [] as Suggestion[], selected: null as Suggestion | null,
    page: 1, next: false, previous: false, stateIndex: 0, stateLabels: ["全部建议", "待审阅", "已接受", "编辑后接受", "已拒绝"],
    loading: false, error: "", message: "", editing: false, text: "", reason: "", confirmed: false,
    preview: null as { text: string; diff: DiffPart[]; guard_reasons: string[] } | null,
    context: null as Context | null, contextPosition: "", originalBefore: "", originalAfter: "",
    canAccept: false, requestKey: "", active: true,
  },
  methods: {
    onLoad(options: { project?: string }) { this.setData({ projectId: options.project ?? "", requestKey: newKey() }); this.refresh(); },
    onUnload() { this.setData({ active: false }); },
    async perform(action: () => Promise<void>) {
      if (this.data.loading || !this.data.active) return;
      this.setData({ loading: true, error: "", message: "" });
      try { await action(); }
      catch (cause) {
        if (!this.data.active) return;
        this.setData({ error: cause instanceof Error ? cause.message : "请求失败，请重试。" });
        if (cause instanceof RequestError && [401, 403, 404].includes(cause.status)) {
          this.setData({ project: null, selected: null, suggestions: [], context: null, text: "", reason: "", confirmed: false, preview: null, canAccept: false });
        }
      } finally { if (this.data.active) this.setData({ loading: false }); }
    },
    async load(page: number) {
      const project = await request<Project>(`projects/${this.data.projectId}/`);
      const result = await request<Result>(`projects/${this.data.projectId}/suggestions/?page=${page}&state=${states[this.data.stateIndex]}`);
      if (!this.data.active) return;
      const policyChanged = this.data.project && this.data.project.policy.version !== project.policy.version;
      this.setData({ project, suggestions: result.results.map(item => ({ ...item, label: item.decision ? labels[item.decision.action] : "待审阅" })), page, next: !!result.next, previous: !!result.previous, ...(policyChanged ? { confirmed: false } : {}) });
      this.updateAllowed();
    },
    updateAllowed() {
      const item = this.data.selected, project = this.data.project;
      this.setData({ canAccept: !!(item && project?.role === "author" && project.policy.allowed_actions.includes("expression") && !item.input_changed && !item.decision && item.model_output.kind === "expression") });
    },
    refresh() { this.perform(() => this.load(1)); },
    nextPage() { this.perform(() => this.load(this.data.page + 1)); },
    previousPage() { this.perform(() => this.load(this.data.page - 1)); },
    changeState(event: WechatMiniprogram.PickerChange) { this.setData({ stateIndex: Number(event.detail.value) }); this.refresh(); },
    show(item: Suggestion) {
      const chars = Array.from(item.manuscript_text);
      this.setData({ selected: { ...item, label: item.decision ? labels[item.decision.action] : "待审阅" }, text: item.model_output.replacement,
        editing: false, confirmed: false, reason: "", preview: null, context: null,
        originalBefore: chars.slice(0, item.model_output.start).join(""), originalAfter: chars.slice(item.model_output.end).join(""), requestKey: newKey() });
      this.updateAllowed();
    },
    async open(id: string) {
      const item = await request<Suggestion>(`projects/${this.data.projectId}/suggestions/${id}/`);
      if (this.data.active) this.show(item);
    },
    select(event: WechatMiniprogram.TouchEvent) { this.perform(() => this.open(event.currentTarget.dataset.id)); },
    reload() { if (this.data.selected) this.perform(async () => { await this.load(this.data.page); await this.open(this.data.selected!.id); }); },
    toggleEdit() { this.setData({ editing: !this.data.editing, confirmed: false, requestKey: newKey() }); },
    changeText(event: WechatMiniprogram.Input) { this.setData({ text: event.detail.value, confirmed: false, preview: null, requestKey: newKey() }); },
    changeReason(event: WechatMiniprogram.Input) { this.setData({ reason: event.detail.value, requestKey: newKey() }); },
    changeConfirmed(event: WechatMiniprogram.CheckboxGroupChange) { this.setData({ confirmed: event.detail.value.includes("confirmed"), requestKey: newKey() }); },
    previewEdit() { this.perform(async () => {
      const text = this.data.text;
      const result = await request<{ diff: DiffPart[]; guard_reasons: string[] }>(`projects/${this.data.projectId}/suggestions/${this.data.selected!.id}/preview/`, "POST", { text });
      if (this.data.active && text === this.data.text) this.setData({ preview: { text, ...result } });
    }); },
    decide(event: WechatMiniprogram.TouchEvent) {
      const action = event.currentTarget.dataset.action as string;
      this.perform(async () => {
        const result = await request<Suggestion>(`projects/${this.data.projectId}/suggestions/${this.data.selected!.id}/decision/`, "POST", {
          request_key: this.data.requestKey, manuscript_version: this.data.selected!.manuscript_version,
          policy_version: this.data.project!.policy.version, action, reason: this.data.reason,
          meaning_confirmed: action !== "rejected" && this.data.confirmed,
          ...(action === "edited" ? { text: this.data.text } : {}),
        });
        if (!this.data.active) return;
        this.show(result);
        await this.load(this.data.page);
        if (this.data.active) this.setData({ message: result.decision?.manuscript_version ? `已保存原稿 v${result.decision.manuscript_version}，Web 加载最新原稿即可查看。` : "已拒绝，原稿未修改。" });
      });
    },
    locate(event: WechatMiniprogram.TouchEvent) { this.perform(async () => {
      const context = await request<Context>(`projects/${this.data.projectId}/chunks/${event.currentTarget.dataset.id}/`);
      const anchor = context.chunk.anchor;
      const position = anchor.kind === "pdf" ? `文件第 ${anchor.page} 页` : anchor.kind === "docx" ? `第 ${anchor.paragraph} 段` : anchor.kind === "csv" ? `第 ${anchor.record} 条记录` : `第 ${anchor.line} 行`;
      if (this.data.active) this.setData({ context, contextPosition: position });
    }); },
    back() { wx.navigateBack(); },
  },
});
