import { createRouter, createWebHistory } from "vue-router";
import ProjectsPage from "@/features/projects/ProjectsPage.vue";
import { workspaces, workspaceTabs } from "./workspaces";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "projects", component: ProjectsPage },
    { path: "/projects/new", name: "project-new", component: ProjectsPage },
    { path: "/projects/:projectId/:workspace?", name: "project", component: ProjectsPage },
    {
      path: "/environment",
      alias: "/wechat",
      name: "environment",
      component: () => import("@/features/environment/EnvironmentPage.vue"),
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
  scrollBehavior: () => ({ top: 0 }),
});
router.beforeEach((to) => {
  if (to.name !== "project") return;
  const workspace = String(to.params.workspace || "overview");
  if (!workspaces.some((item) => item.key === workspace)) {
    return {
      name: "project",
      params: { projectId: to.params.projectId, workspace: "overview" },
      replace: true,
    };
  }
  if (to.query.tab && !workspaceTabs[workspace]?.includes(String(to.query.tab))) {
    return { ...to, query: {}, replace: true };
  }
});
