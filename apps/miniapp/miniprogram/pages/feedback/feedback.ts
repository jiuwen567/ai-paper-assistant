import { request, RequestError } from "../../services/session";
type Project = { id: string; role: string; name: string };
type Location = { manuscript_version: number; block_id: string; position: number; text: string; stale: boolean };
type Task = { id: string; feedback_id: string; original_location: Location | null; current: { number: number; title: string; instruction: string; status: string; note: string; result_kind: string; location: Location | null; mentor_reports: { id: number; status: string; text: string; source_label: string }[] }; label?: string };
type Manuscript = { version: number; blocks: { id: string; text: string; version_id: string }[] };
const statuses = ["todo", "doing", "completed", "dropped"];
const labels = ["待处理", "处理中", "作者已完成", "不再处理"];
const results = ["pending", "modified", "no_change"];
const newKey = () => `mini-feedback-${Date.now()}-${Math.random().toString(36).slice(2)}`;
Component({
  data: { projectId: "", project: null as Project | null, tasks: [] as Task[], selected: null as Task | null,
    feedback: null as { text: string; source_label: string; source_chunk_id: string | null } | null,
    manuscript: null as Manuscript | null, page: 1, next: false, previous: false, filterIndex: 0,
    filterLabels: ["全部待办", ...labels], statusLabels: labels, statusIndex: 0,
    resultLabels: ["选择处理结果", "已修改原稿", "无需改稿（须说明原因）"], resultIndex: 0,
    blockLabels: ["选择最新正文块"], blockIndex: 0, linked: null as Location | null,
    note: "", dirty: false, version: 1, requestKey: "", loading: false, error: "", message: "", active: true,
  },
  methods: {
    onLoad(options: { project?: string }) { this.setData({ projectId: options.project || "", requestKey: newKey() }); this.refresh(); },
    onUnload() { this.setData({ active: false }); },
    markDirty(dirty: boolean) {
      this.setData({ dirty });
      if (dirty) wx.enableAlertBeforeUnload({ message: "处理说明尚未保存，确认离开？" });
      else wx.disableAlertBeforeUnload();
    },
    confirmLeave(action: () => void) {
      if (this.data.loading) return;
      if (this.data.dirty) wx.showModal({ title: "未保存修改", content: "处理说明尚未保存，确认放弃修改？", success: result => { if (result.confirm) action(); } });
      else action();
    },
    async perform(action: () => Promise<void>) {
      if (this.data.loading || !this.data.active) return;
      this.setData({ loading: true, error: "", message: "" });
      try { await action(); } catch (cause) {
        if (!this.data.active) return;
        this.setData({ error: cause instanceof Error ? cause.message : "请求失败，请重试。" });
        if (cause instanceof RequestError && [401, 403, 404].includes(cause.status)) { this.markDirty(false); this.setData({ project: null, tasks: [], selected: null, feedback: null, manuscript: null, note: "", linked: null, blockLabels: ["选择最新正文块"] }); }
      } finally { if (this.data.active) this.setData({ loading: false }); }
    },
    async load(number: number) {
      const project = await request<Project>(`projects/${this.data.projectId}/`);
      const status = this.data.filterIndex ? statuses[this.data.filterIndex - 1] : "";
      const value = await request<{ results: Task[]; next: string | null; previous: string | null }>(`projects/${this.data.projectId}/feedback-tasks/?page=${number}&status=${status}`);
      if (this.data.active) this.setData({ project, tasks: value.results.map(task => ({ ...task, label: labels[statuses.indexOf(task.current.status)] })), page: number, next: !!value.next, previous: !!value.previous });
    },
    refresh() { this.perform(() => this.load(this.data.page)); },
    nextPage() { this.perform(() => this.load(this.data.page + 1)); },
    previousPage() { this.perform(() => this.load(this.data.page - 1)); },
    changeFilter(event: WechatMiniprogram.PickerChange) { this.setData({ filterIndex: Number(event.detail.value) }); this.perform(() => this.load(1)); },
    async open(id: string) {
      const selected = await request<Task>(`projects/${this.data.projectId}/feedback-tasks/${id}/`);
      const feedback = await request<{ text: string; source_label: string; source_chunk_id: string | null }>(`projects/${this.data.projectId}/feedback/${selected.feedback_id}/`);
      const manuscript = await request<Manuscript>(`projects/${this.data.projectId}/manuscript/`);
      if (!this.data.active) return;
      this.setData({ selected, feedback, manuscript, version: selected.current.number, note: selected.current.note,
        dirty: false, statusIndex: statuses.indexOf(selected.current.status), resultIndex: results.indexOf(selected.current.result_kind), linked: selected.current.location,
        blockLabels: ["选择最新正文块", ...manuscript.blocks.map((block, i) => `块 ${i + 1}：${block.text.slice(0, 40)}`)], blockIndex: 0, requestKey: newKey() });
      this.markDirty(false);
    },
    select(event: WechatMiniprogram.TouchEvent) {
      const id = event.currentTarget.dataset.id;
      this.confirmLeave(() => this.perform(() => this.open(id)));
    },
    changeNote(event: WechatMiniprogram.Input) { this.markDirty(true); this.setData({ note: event.detail.value, requestKey: newKey() }); },
    changeStatus(event: WechatMiniprogram.PickerChange) { this.markDirty(true); this.setData({ statusIndex: Number(event.detail.value), requestKey: newKey() }); },
    changeResult(event: WechatMiniprogram.PickerChange) { this.markDirty(true); this.setData({ resultIndex: Number(event.detail.value), requestKey: newKey() }); },
    changeBlock(event: WechatMiniprogram.PickerChange) { this.setData({ blockIndex: Number(event.detail.value) }); },
    relink() { const block = this.data.manuscript?.blocks[this.data.blockIndex - 1]; if (block && this.data.manuscript) { this.markDirty(true); this.setData({ linked: { manuscript_version: this.data.manuscript.version, block_id: block.id, position: this.data.blockIndex, text: block.text, stale: false }, requestKey: newKey() }); } },
    unlink() { this.markDirty(true); this.setData({ linked: null, requestKey: newKey() }); },
    refreshSelected() { this.perform(async () => {
      const task = await request<Task>(`projects/${this.data.projectId}/feedback-tasks/${this.data.selected!.id}/`);
      const manuscript = await request<Manuscript>(`projects/${this.data.projectId}/manuscript/`);
      if (this.data.active) this.setData({ selected: task, manuscript, blockIndex: 0,
        blockLabels: ["选择最新正文块", ...manuscript.blocks.map((block, i) => `块 ${i + 1}：${block.text.slice(0, 40)}`)] });
    }); },
    adoptVersion() { if (this.data.selected) this.setData({ version: this.data.selected.current.number, requestKey: newKey() }); },
    save() { this.perform(async () => {
      const task = this.data.selected!;
      const value = await request<Task>(`projects/${this.data.projectId}/feedback-tasks/${task.id}/`, "POST", {
        request_key: this.data.requestKey, version: this.data.version, title: task.current.title, instruction: task.current.instruction,
        status: statuses[this.data.statusIndex], note: this.data.note,
        result_kind: statuses[this.data.statusIndex] === "completed" ? results[this.data.resultIndex] : "pending",
        manuscript_version: this.data.linked?.manuscript_version ?? null, block_id: this.data.linked?.block_id ?? null,
      });
      if (!this.data.active) return;
      this.setData({ selected: value, version: value.current.number, requestKey: newKey(), message: "作者处理记录已保存；不代表导师确认。" });
      this.markDirty(false);
      await this.load(this.data.page);
    }); },
    back() { this.confirmLeave(() => { this.markDirty(false); wx.navigateBack(); }); },
  },
});
