import {
  BookOpen,
  FilePenLine,
  Files,
  MessageSquare,
  Network,
  Download,
  Settings,
  ListTodo,
  LayoutDashboard,
} from "@lucide/vue";

export const workspaces = [
  { key: "overview", label: "项目总览", icon: LayoutDashboard },
  { key: "writing", label: "原稿写作", icon: FilePenLine },
  { key: "materials", label: "材料与阅读", icon: Files },
  { key: "review", label: "审阅与修订", icon: BookOpen },
  { key: "feedback", label: "导师反馈", icon: MessageSquare },
  { key: "evidence", label: "依据与变更", icon: Network },
  { key: "delivery", label: "导出与披露", icon: Download },
  { key: "jobs", label: "后台任务", icon: ListTodo },
  { key: "settings", label: "项目设置", icon: Settings },
];
export const workspaceTabs: Record<string, string[]> = {
  materials: ["files", "library", "reading"],
  review: ["diagnosis", "expression"],
  evidence: ["graph", "impact"],
  delivery: ["export", "disclosure"],
};
export const roleName = (role: string) => (role === "author" ? "作者" : "审阅者");
