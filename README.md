# AI Paper Assistant

智能论文辅助写作系统。围绕作者的研究材料和原稿，提供文献理解、证据核验、原稿审阅与修订管理。

Web 用于阅读、写作和审阅；微信小程序用于收集资料、查看证据和处理待办；公众号提供入口和使用说明。

> 当前提供 M1 基础工程及 Web 登录、项目管理、成员权限、AI 辅助规则版本和可恢复的后台样例任务。微信绑定、项目与任务小程序入口已有实现，真实微信账号及公众号菜单仍待联调。材料上传、版本管理和后台解析已接入，Web 可按片段回查 PDF 页序、DOCX 段落及 CSV 记录，管理题录、证据与笔记，并使用项目内关键词和本地向量检索；小程序证据入口仍待真实微信验收。Pi 已接入有来源的阅读摘记与多篇比较，作者修订和核对状态单独保存；需要管理员配置生成模型。自制样例的本地模型测试发现摘要漏提和比较超时，结果仍需逐项核对。Web 已提供作者研究说明、章节与正文编辑、版本对照、恢复旧稿及 DOCX 正文导入；原稿诊断已提供固定位置的问题卡、作者判断与修改后复查；本地小模型实测存在误报和失败，不能替代作者核验。Web 与小程序已接入表达建议的接受、编辑后接受和拒绝，原稿与引用原子保存；真实微信验收仍待进行，本地小模型尚未生成可用表达建议。Web 可按项目回查 AI 调用、输出与实际采纳，编辑披露说明、补充系统外使用并保留核对历史。导师意见可由作者录入、拆成待确认候选，并关联修改位置和处理说明；作者完成与作者转录的导师回复分别记录。小程序修改待办入口已接入，真实微信验收仍待进行。Web 可登记作者核对的依据关系，双向回查正文、主张、证据与材料；Neo4j 从 PostgreSQL 事务事件重建，图滞后或不可用时不显示空结果。Web 可登记材料补充、更正与撤回，查询已登记的受影响正文、建议和待办，保留作者处理与复查历史；模型仅补充待核对位置，本地小模型实测仍会误报无关实验。Web 可预览并确认固定快照的 Word 导出，后台保存文件、保留下载记录并支持失败重试；目前提供自制示例排版规则，指定院系格式及实际 Word 打开验收仍待完成。

## 本地启动

需要 Python 3.12、GNU Make、Docker Engine / Docker Desktop（Linux 容器）和 Docker Compose v2。WSL 使用 Docker Desktop 时，先开启当前发行版的 WSL Integration，确认 `docker info` 能连接服务端。

```bash
git clone https://github.com/jiuwen567/ai-paper-assistant.git
cd ai-paper-assistant
python3 scripts/init_dev.py
make up
```

初始化脚本生成随机本地凭据，不覆盖已有 `.env`。`make up` 构建并启动应用、执行数据库迁移，再检查依赖和 Worker 任务往返。首次拉取镜像需要网络及数 GB 可用磁盘空间。

- Web：[http://localhost:5173](http://localhost:5173)
- 环境概览：[http://localhost:5173/environment](http://localhost:5173/environment)
- API 存活检查：[http://localhost:8000/api/v1/health/live/](http://localhost:8000/api/v1/health/live/)
- 依赖就绪检查：[http://localhost:8000/api/v1/health/ready/](http://localhost:8000/api/v1/health/ready/)（故障时返回 503）
- 公众号 H5 说明入口：[http://localhost:5173/wechat](http://localhost:5173/wechat)
- 微信开发者工具导入 `apps/miniapp`，配置自己的测试 AppID。操作见[开发说明](docs/development.md#微信小程序与公众号)。

`make down` 停止容器并保留数据卷。需要源码热更新时，使用[开发说明](docs/development.md)中的本机开发方式。该文档也记录检查命令和实际验证范围。

首次使用先按[账号与项目说明](docs/development.md#账号与项目)创建本地账号。新项目的 AI 辅助默认关闭；作者核对规则来源及版本后，才能选择允许的功能。

## 主要功能

- **材料与阅读**：管理文献和研究材料，整理有出处的摘记，比较多篇文献。
- **原稿审阅**：检查引用是否支持论述，定位材料与正文不一致、推理缺漏等问题。
- **修改与反馈**：对照表达建议，跟踪导师意见，保留作者决定和稿件版本。
- **依据与变更**：回查材料、证据和段落的关系，提示材料更正后需要复核的位置。
- **格式与交付**：按已登记模板版本导出 Word，附作者核实的 AI 使用说明；当前提供自制示例模板。
- **删除与清理**：预览并确认材料及派生数据或整个项目的永久删除，跟踪文件、向量和图关系清理，失败后可继续执行。

研究问题、核心论点、研究实施及实质性写作由作者完成。系统不提供论文代写、虚构数据或规避检测服务；AI 输出需要核对，并遵守适用的学校与课程要求。

## 技术方向

| 组件 | 用途 |
| --- | --- |
| Vue 3 + TypeScript + Vite | Web 工作台与公众号 H5 入口 |
| 微信原生 TypeScript + Skyline + glass-easel | 小程序 |
| Django 5.2 LTS + Django REST framework | 统一业务 API |
| Celery + Redis | 独立 Worker、任务消息与诊断结果 |
| Pi | 受限的模型与业务工具执行 |
| PostgreSQL + pgvector | 业务数据、版本、事务和资料检索 |
| Neo4j | 依据路径与变更影响查询 |
| SeaweedFS S3 | 原始资料、预览、模板和导出文件 |

JavaScript 使用 pnpm workspace，Python 使用 uv；依赖由锁文件固定。Pi Agent / AI SDK 锁定 1.5.0，由 Worker 启动固定 Node 执行器，不开放通用编码工具。组件版本和目录职责见[开发说明](docs/development.md)。

## 文档

- [产品需求](docs/requirements.md)
- [双端使用流程](docs/workflows.md)
- [技术架构](docs/architecture.md)
- [数据库设计](docs/database.md)
- [测试与验收](docs/testing.md)
- [开发计划](docs/roadmap.md)
- [开发说明](docs/development.md)
- [部署、恢复与升级](docs/deployment.md)
- [看板设置](docs/project-setup.md)
- [参与开发](CONTRIBUTING.md)

开发任务通过 [Issues](https://github.com/jiuwen567/ai-paper-assistant/issues) 跟踪，阶段成果见 [Milestones](https://github.com/jiuwen567/ai-paper-assistant/milestones)。每项任务写明范围、依赖和验收条件，完成验证后再关闭。

## 资料与权限

公开仓库仅保存代码、文档和可公开使用的测试样例。不提交真实论文、未公开研究资料、访谈记录、账号凭据或运行数据。

本仓库暂未选择开源许可证；公开访问不代表已授予使用、修改或分发许可。
