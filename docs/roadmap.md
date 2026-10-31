# 开发计划

本期按五个阶段推进，共 20 项开发任务。不安排需求调研任务，不预填负责人和截止日期。

## 阶段

| 阶段 | 交付内容 | 任务 |
| --- | --- | --- |
| M1 基础工程与双端接入 | 工程、账号、后台任务和微信接入 | #1–#4 |
| M2 材料管理与 AI 阅读 | 上传、解析、检索、Pi 和文献阅读 | #5–#9 |
| M3 原稿审阅与修订 | 编辑、诊断、表达建议、披露和反馈 | #10–#14 |
| M4 依据关系与规范交付 | 图关系、影响分析、Word 导出和清理 | #15–#18 |
| M5 测试部署与验收 | 完整流程、效果评测、部署与演示 | #19–#20 |

## 任务入口

| Issue | 内容 | 优先级 |
| --- | --- | --- |
| [#1](https://github.com/jiuwen567/ai-paper-assistant/issues/1) | 初始化工程与本地开发环境 | P0 |
| [#2](https://github.com/jiuwen567/ai-paper-assistant/issues/2) | 用户、项目和权限 | P0 |
| [#3](https://github.com/jiuwen567/ai-paper-assistant/issues/3) | 后台任务与恢复 | P0 |
| [#4](https://github.com/jiuwen567/ai-paper-assistant/issues/4) | 小程序绑定与公众号入口 | P0 |
| [#5](https://github.com/jiuwen567/ai-paper-assistant/issues/5) | 双端上传与材料版本 | P0 |
| [#6](https://github.com/jiuwen567/ai-paper-assistant/issues/6) | 解析与原文定位 | P0 |
| [#7](https://github.com/jiuwen567/ai-paper-assistant/issues/7) | 文献卡、证据卡与检索 | P0 |
| [#8](https://github.com/jiuwen567/ai-paper-assistant/issues/8) | Pi 受限执行 | P0 |
| [#9](https://github.com/jiuwen567/ai-paper-assistant/issues/9) | AI 阅读与文献比较 | P0 |
| [#10](https://github.com/jiuwen567/ai-paper-assistant/issues/10) | 作者编辑与版本对照 | P0 |
| [#11](https://github.com/jiuwen567/ai-paper-assistant/issues/11) | 证据核验与论证诊断 | P0 |
| [#12](https://github.com/jiuwen567/ai-paper-assistant/issues/12) | 双端建议审阅与采纳 | P0 |
| [#13](https://github.com/jiuwen567/ai-paper-assistant/issues/13) | AI 使用记录与披露 | P1 |
| [#14](https://github.com/jiuwen567/ai-paper-assistant/issues/14) | 导师反馈与修改待办 | P1 |
| [#15](https://github.com/jiuwen567/ai-paper-assistant/issues/15) | Neo4j 依据路径 | P1 |
| [#16](https://github.com/jiuwen567/ai-paper-assistant/issues/16) | 材料更正影响分析 | P1 |
| [#17](https://github.com/jiuwen567/ai-paper-assistant/issues/17) | 固定快照 Word 导出 | P1 |
| [#18](https://github.com/jiuwen567/ai-paper-assistant/issues/18) | 删除与派生数据清理 | P1 |
| [#19](https://github.com/jiuwen567/ai-paper-assistant/issues/19) | 测试与 AI 效果评测 | P1 |
| [#20](https://github.com/jiuwen567/ai-paper-assistant/issues/20) | 部署文档与课程演示 | P1 |

P0 先形成可用的核心流程；P1 也属于本期交付，并非可省略功能。

## 执行顺序

从 #1 开始。#2 完成后，#3、#4 和 #10 可以并行。材料上传、解析和检索逐步接入 Pi，再与原稿编辑汇合，形成审阅与修订流程。图关系、导出和清理随后接入。

每条 Issue 已列依赖。里程碑不是串行锁：接口明确后可分段开发，但关闭任务前必须完成相关联调。

## 看板约定

计划使用 Backlog、Ready、In progress、Review、Done 五种状态。初始仅 #1 可进入 Ready，其余先留 Backlog；阻塞通过 `blocked` 标签和一条具体说明记录。

负责人和日期由实际分工确定。完成功能并通过验收后再关闭 Issue，不因文档或骨架存在就标记完成。
