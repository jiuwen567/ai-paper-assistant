# 看板设置

Issues 保存任务内容，Milestones 管阶段，Projects 展示进度。看板中引用已有 Issue，不重复建立同名草稿任务。

## 创建与关联

在个人账号的 Projects 页面新建 Board，名称为“智能论文辅助写作系统”，设置为 Public。关联 `jiuwen567/ai-paper-assistant`，并将仓库设为默认任务来源。

从仓库 Issue 列表勾选 #1–#20，批量加入这个 Project。仓库公开与看板公开分别设置。

## 字段与视图

Status 使用以下五项：

| 状态 | 含义 |
| --- | --- |
| Backlog | 已确定要做，尚未安排 |
| Ready | 前置条件具备，可以开始 |
| In progress | 正在实现 |
| Review | 实现已提交，正在验收 |
| Done | 验收通过，代码已合并 |

初始将 #1 放在 Ready，其他任务放在 Backlog。负责人和日期根据实际分工填写，不默认全部指派给仓库所有者。

优先级先使用 Issue 的 `P0`、`P1` 标签，避免重复维护。P0 优先形成核心流程，P1 仍属于本期交付。领域使用 `web`、`miniapp`、`backend`、`ai`、`database` 标签；遇到阻塞时加 `blocked` 并说明原因。

保留两个视图即可：按 Status 分列的开发看板，以及按 Milestone 分组的阶段清单。

## 自动化

可以开启新条目进入 Backlog、Issue 关闭进入 Done。新增任务自动加入本仓库的 Project；既有任务首次手动批量导入。

仓库中的 `Initialize issue tracking` 工作流只初始化五个里程碑并分类现有的 20 条任务，可从 Actions 手动重跑。它保留任务状态、负责人、已有标签和人工设置的里程碑，不创建 Projects 看板，也不运行应用测试。

## 提交与完成

PR 写明关联任务和验证结果。全部验收完成时使用 `Closes #编号`；部分完成使用 `Refs #编号`，不要提前关闭任务。

阶段与任务入口见 [开发计划](roadmap.md)。

## GitHub 文档

- [创建 Project](https://docs.github.com/en/issues/planning-and-tracking-with-projects/creating-projects/creating-a-project)
- [添加 Issue](https://docs.github.com/en/issues/planning-and-tracking-with-projects/managing-items-in-your-project/adding-items-to-your-project)
- [内置自动化](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations)
