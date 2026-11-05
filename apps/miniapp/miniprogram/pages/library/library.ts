import { downloadDocument, request, RequestError } from "../../services/session";

type Project = { id: string; name: string; role: string };
type Evidence = { id: string; chunk: string; quote: string; revision: number; bibliography: { title: string; source_scope: string }; source: { id: string; number: number; file_name: string; access_state: string }; note: { text: string; tags: string[] }; scopeLabel?: string };
type PageResult = { results: Evidence[]; next: string | null; previous: string | null };
type Context = { chunk: { text: string; anchor: Record<string, string | number> }; context: { id: string; text: string }[] };
const scopes: Record<string, string> = { unknown: "范围未核对", abstract: "仅摘要", full_text: "全文（作者标记）", research: "研究记录" };
Component({
  data: {
    projectId: "", project: null as Project | null, cards: [] as Evidence[],
    selected: null as Evidence | null, context: null as Context | null,
    note: "", query: "", tag: "", page: 1, next: false, previous: false,
    loading: false, error: "", message: "", canDownload: false,
  },
  methods: {
    onLoad(options: { project?: string }) {
      this.setData({ projectId: options.project ?? "" });
      this.refresh();
    },
    async perform(action: () => Promise<void>) {
      if (this.data.loading) return;
      this.setData({ loading: true, error: "", message: "" });
      try { await action(); }
      catch (cause) {
        this.setData({ error: cause instanceof Error ? cause.message : "请求失败，请重试。" });
        if (cause instanceof RequestError && [401, 403, 404].includes(cause.status)) {
          this.setData({ project: null, cards: [], selected: null, context: null, note: "" });
        }
      } finally { this.setData({ loading: false }); }
    },
    async load(page: number) {
      const project = await request<Project>(`projects/${this.data.projectId}/`);
      const result = await request<PageResult>(`projects/${project.id}/evidence/?page=${page}&q=${encodeURIComponent(this.data.query)}&tag=${encodeURIComponent(this.data.tag)}`);
      this.setData({ project, cards: result.results.map(card => ({ ...card, scopeLabel: scopes[card.bibliography.source_scope] })), page, next: !!result.next, previous: !!result.previous });
    },
    refresh() { this.perform(() => this.load(1)); },
    nextPage() { this.perform(() => this.load(this.data.page + 1)); },
    previousPage() { this.perform(() => this.load(this.data.page - 1)); },
    changeQuery(event: WechatMiniprogram.Input) { this.setData({ query: event.detail.value }); },
    changeTag(event: WechatMiniprogram.Input) { this.setData({ tag: event.detail.value }); },
    changeNote(event: WechatMiniprogram.Input) { this.setData({ note: event.detail.value }); },
    async open(id: string) {
      const card = await request<Evidence>(`projects/${this.data.projectId}/evidence/${id}/`);
      card.scopeLabel = scopes[card.bibliography.source_scope];
      this.setData({ selected: card, note: card.note.text, context: null, canDownload: /\.(pdf|docx)$/i.test(card.source.file_name) });
    },
    select(event: WechatMiniprogram.TouchEvent) { this.perform(() => this.open(event.currentTarget.dataset.id)); },
    reload() { if (this.data.selected) this.perform(() => this.open(this.data.selected!.id)); },
    save() {
      this.perform(async () => {
        const card = this.data.selected!;
        const updated = await request<Evidence>(`projects/${this.data.projectId}/evidence/${card.id}/`, "PUT", { version: card.revision, note: this.data.note, tags: card.note.tags });
        updated.scopeLabel = scopes[updated.bibliography.source_scope];
        this.setData({ selected: updated, message: "笔记已保存。" });
        await this.load(this.data.page);
      });
    },
    locate() {
      this.perform(async () => {
        const result = await request<Context>(`projects/${this.data.projectId}/chunks/${this.data.selected!.chunk}/`);
        this.setData({ context: result });
      });
    },
    download() {
      this.perform(async () => { await downloadDocument(`projects/${this.data.projectId}/files/${this.data.selected!.source.id}/`, this.data.selected!.source.file_name.toLowerCase().endsWith(".pdf") ? "pdf" : "docx"); });
    },
    back() { wx.navigateBack(); },
  },
});
