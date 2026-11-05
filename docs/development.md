# 开发说明

本工程对应 [Issue #1](https://github.com/jiuwen567/ai-paper-assistant/issues/1)，提供客户端、API、Worker 和本地基础设施，不包含论文业务实现。

## 技术栈与版本

| 部分 | 选择 | 版本依据 |
| --- | --- | --- |
| JavaScript 运行时 / 包管理 | Node.js 24、pnpm 10.32.1 | `.node-version`、根 `package.json` |
| Web / 公众号 H5 | Vue 3.5.44、Vite 8.3.5、TypeScript 5.9.3 | `apps/web/package.json`、`pnpm-lock.yaml` |
| 小程序 | 微信原生 TypeScript、Skyline、glass-easel | 微信开发者工具 2.02.2609240，基础库 3.17.6，类型库 `miniprogram-api-typings` 5.2.3 |
| Python / 包管理 | Python 3.12、uv 0.9.26 | `.python-version`、`uv.lock` |
| API | Django 5.2.19 LTS、DRF 3.18.3 | `pyproject.toml` 声明兼容范围，`uv.lock` 固定完整依赖 |
| Worker / 消息代理 | Celery 5.6.3、Redis 8.2.3 | `uv.lock`、`compose.yaml` |
| 业务数据库 / 向量 | PostgreSQL 17、pgvector 0.8.7 | `pgvector/pgvector:0.8.7-pg17-trixie` |
| 图投影 | Neo4j 5.26.27 Community LTS | `compose.yaml` |
| 文件存储 | SeaweedFS 4.52，S3 兼容接口 | `compose.yaml` |

Web 与小程序使用已锁定的 TypeScript 5.9，避免编辑器和小程序编译器同步升级问题。Django 选择维护中的 LTS 系列；不因初始化任务额外引入 UI 组件库或业务状态管理。公众号共用 Web 的响应式 H5，服务端接入后续复用 Django。

`apps/miniapp/project.config.json` 固定模拟器验收使用的基础库版本。升级基础库时同步修改 `libVersion`，并重跑小程序验收。

参考：[Django 支持版本](https://www.djangoproject.com/download/)、[DRF 兼容要求](https://www.django-rest-framework.org/)、[微信官方示例与 TypeScript 配置](https://github.com/wechat-miniprogram/miniprogram-demo)、[Celery 文档](https://docs.celeryq.dev/en/stable/getting-started/introduction.html)、[pgvector](https://github.com/pgvector/pgvector)、[SeaweedFS](https://github.com/seaweedfs/seaweedfs)。

## 工程结构

```text
apps/
  web/                         Vue 3 工作台；/wechat 为公众号说明入口
  miniapp/                     可由微信开发者工具导入的原生工程
services/backend/
  config/                      Django 配置、URL、WSGI
  core/                        健康检查、初始化迁移、管理命令、测试
  worker/                      独立 Celery 进程及诊断任务
infra/seaweedfs/filer.toml      Filer 元数据持久化配置
infra/seaweedfs/master.toml     本地 Volume 按需分配配置
scripts/init_dev.py            生成本地凭据及 S3 配置
compose.yaml                   基础服务与可选应用容器
```

API 与 Worker 共用 Python 依赖和镜像，但分别启动进程。Redis 只承担任务传输与短期结果，不替代 PostgreSQL 的业务事实源。当前没有实现业务任务状态机、重试、取消或 outbox；这些由后续 Issue 承接。

## 方式一：全部使用容器

前置条件：Python 3.12（仅用于生成配置）、GNU Make、Docker Engine / Docker Desktop Linux 容器、Compose v2（支持 `--wait`）。建议至少提供 4 GB 可用容器内存。Windows 推荐在 WSL 中运行这些命令，微信开发者工具运行在 Windows。

```bash
python3 scripts/init_dev.py
docker info
make up
```

`make up` 包含构建、拉起、迁移、依赖检查、真实 Worker 诊断任务。应用通过 Compose 服务名访问基础服务，宿主机端口仅绑定 `127.0.0.1`。启动顺序为 PostgreSQL 就绪 → 一次性 migrate → API / Worker；Worker 同时等待 Redis。Web 等待 API 存活。最终 `check_services` 会检查所有依赖是否真正可用。

没有 Make 时等价命令：

```bash
docker compose --profile app up -d --build --wait
docker compose exec api python manage.py check_services
docker compose exec api python manage.py check_worker
```

打开 `http://localhost:5173`。本地镜像中的 Web 使用 Vite 开发服务器；这份 Compose 用于开发，不是生产部署配置。源代码没有绑定进容器，修改后重新执行 `make up` 构建；需要热更新时用方式二。

```bash
docker compose --profile app ps
docker compose --profile app logs --tail=100 api worker
make down
```

`make down` 保留所有数据卷。不要为处理启动问题随手执行 `down -v`；它会删除该 Compose 项目的本地数据。CI 只对临时测试项目执行数据卷清理。

## 方式二：基础服务容器化，应用在本机运行

除 Docker 外，需要 Node.js 24、pnpm 10.32.1、Python 3.12、uv 0.9.26。先停止方式一的应用，避免 8000 / 5173 端口占用。

```bash
make init
make install
make infra
make migrate
```

`make install` 分别运行 `uv sync --locked`、`pnpm install --frozen-lockfile`。不要混用 npm / yarn 产生其他锁文件，也不要在启动过程中自动升级依赖。

然后在三个终端分别运行：

```bash
make api
```

```bash
make worker
```

```bash
make web
```

另一终端运行 `make health`。Web 的 `/api` 由 Vite 代理至 `http://127.0.0.1:8000`，不需要放开 CORS。容器模式通过 `API_PROXY_TARGET=http://api:8000` 覆盖代理目标。健康响应仅提供状态，不包含连接地址、凭据或底层异常正文。

没有容器时仍可以执行单元测试、类型检查和构建。若只验证 Web → API 及依赖故障展示，可以用下列命令代替 `make api`：

```bash
uv run --directory services/backend gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2
```

此时存活接口返回 200，就绪接口应返回 503。不能把该模式算作完整环境启动或数据库验收通过。`runserver` 启动时检查迁移，数据库未启动时会失败，属于预期行为。

## 配置与持久化

`.env.example` 只包含占位值和公共本地地址。直接运行 `scripts/init_dev.py` 会从示例生成随机开发凭据，并生成 `.local/seaweedfs/s3.json`。脚本只使用 Python 标准库，重复执行不会覆盖已有 `.env`。如果手动复制了示例文件，先填写随机值，或移走这份占位副本再运行脚本；包含占位值时脚本会拒绝启动配置生成。

配置由 `config/settings.py` 从仓库根目录加载；进程环境变量优先。不要在小程序、`VITE_*` 或客户端代码中放 AppSecret、数据库密码、模型密钥。尚未接入的微信或 Pi 能力不要求填入真实凭据。

| 服务 | 宿主机地址 | 数据卷 |
| --- | --- | --- |
| PostgreSQL | `127.0.0.1:5432` | `postgres_data` |
| Neo4j | Browser `7474`、Bolt `7687` | `neo4j_data`、`neo4j_logs` |
| SeaweedFS S3 | `127.0.0.1:8333` | `seaweedfs_data`（包含 Filer LevelDB 元数据和文件卷） |
| Redis | `127.0.0.1:6379`（可由 `REDIS_PORT` 修改） | `redis_data` |

SeaweedFS 加载本地生成的 S3 凭据，Filer 与 Master 不发布宿主机端口。Redis 只暴露本机端口，本地开发未另设密码。Neo4j 用户固定为 `neo4j`；PostgreSQL 数据库名与用户名可在首次初始化前修改。

SeaweedFS 按需每次分配 1 个 Volume，单节点最多 32 个，每个上限 128 MB，适用于本地开发。容器健康检查同时确认 Master 已成为 Leader、存储节点有可分配容量和 Filer 可访问，避免重启选举期间提前宣告就绪。只启用本阶段需要的 S3 接口，未启用额外的 IAM、Iceberg 和 Lance 服务。

首次迁移安装 `vector` 扩展，并应用 Django 自带的 auth、contenttypes、sessions 迁移。当前没有业务表，也不会创建用户或演示论文。初始化数据库用户有安装扩展权限；生产应另外设计最小权限和迁移角色。

数据库密码保存在已有数据卷内，修改 `.env` 不会自动更改 PostgreSQL / Neo4j 已初始化的密码。应通过数据库管理命令同步修改；修改 S3 凭据后重跑初始化脚本并重启 SeaweedFS。

`.env`、`.local/`、虚拟环境、node_modules、构建产物、浏览器测试结果、真实资料和运行数据均由 `.gitignore` 排除，构建上下文也通过 `.dockerignore` 排除。不要提交这些文件。

## 微信小程序与公众号

1. 安装当前稳定版微信开发者工具，导入 `apps/miniapp`，而非 `miniprogram` 子目录。
2. `project.config.json` 已设置 TypeScript 编译、Skyline 和 glass-easel。`touristappid` 只是占位符，官方自动化接口会对它返回 `APPID_ERROR`；编译验收必须配置当前登录账号有开发权限的真实测试 AppID，不需要 AppSecret。
3. 在工具中按工程配置选择基础库 3.17.6 并编译。`pnpm check` 执行 TypeScript 检查，微信开发者工具执行小程序编译和预览。
4. API 默认地址位于 `miniprogram/config/api.ts`。Windows 工具访问 WSL 服务时，先在 Windows 浏览器确认 `http://127.0.0.1:8000/api/v1/health/live/` 可达。
5. 在模拟器点击“检查 API 连接”，确认界面显示“API 已连接”。若请求报合法域名校验错误，可在该项目的本地调试设置中处理，公共工程配置保留 `urlCheck: true`。
6. 真机的 `127.0.0.1` 指向手机本身。真机调试改用可达 HTTPS API，配置 request 合法域名，恢复域名校验；不要向客户端添加服务端密钥。

小程序只展示 API 存活结果，依赖就绪状态在 Web 工作台查看。微信账号绑定、上传、证据卡和待办没有接入。

### 开发者工具自动验收

工程已提供 `miniprogram-automator` 0.13.0 自动化脚本。先由开发者本人完成工具登录，并在“设置 → 安全设置”开启服务端口；保持 API 正常运行。以下命令在 Windows PowerShell、仓库根目录执行，将工具路径替换为实际安装位置：

```powershell
& 'C:\实际安装目录\cli.bat' auto --project "$((Resolve-Path apps/miniapp).Path)" --auto-port 9420
```

工具打开该项目并启用自动化后，在另一个终端执行：

```bash
pnpm --filter @paper/miniapp test:e2e
```

脚本默认连接 `ws://127.0.0.1:9420`，可用 `MINIAPP_WS_ENDPOINT` 指定可达的本地自动化端口。测试终端必须能访问工具实际监听的端口。

Windows 工具 2.02.2609240 的自动化接口拒绝 WSL UNC 项目路径（`local path is invalid or not allowed`）。仓库位于 WSL 时，先在 Windows 本地目录建立仅含小程序源码的验收副本；示例在 Windows PowerShell 中执行，将源路径替换为本机目录：

```powershell
$miniSource = '\\wsl.localhost\Ubuntu\你的仓库目录\apps\miniapp'
$miniTarget = Join-Path $env:LOCALAPPDATA 'PaperAssistant\miniapp-acceptance'
New-Item -ItemType Directory -Force $miniTarget | Out-Null
Copy-Item "$miniSource\project.config.json" $miniTarget -Force
Copy-Item "$miniSource\miniprogram" $miniTarget -Recurse -Force
```

在验收副本的 `project.config.json` 配置自己的测试 AppID，再将 `--project` 指向 `$miniTarget`。不要复制仓库根目录的 `.env`、服务端配置或真实资料。源代码修改仍在仓库内进行，验收前重新同步副本；工具中的本地配置不回写为公共凭据。

WSL 使用 NAT 时，Windows 和 WSL 的 `127.0.0.1` 可能指向不同的自动化端口。此时在 Windows 侧运行 Node 测试。在已有 Windows 本地仓库时使用上面的 pnpm 命令；仅有 WSL 仓库时，可将测试和对应版本的 SDK 放入 Windows 验收副本，在 PowerShell 中执行以下命令。

```powershell
Copy-Item "$miniSource\tests" $miniTarget -Recurse -Force
npm install --prefix $miniTarget --no-save --package-lock=false --ignore-scripts miniprogram-automator@0.13.0
node "$miniTarget\tests\acceptance.cjs"
```

测试检查首页初始状态、真实 API 成功反馈、模拟网络失败与加载反馈、模拟 HTTP 503、恢复真实请求后的重试结果；正常路径不替换 `wx.request`。成功截图和结果保存到 `apps/miniapp/test-results/`，不会进入 Git。模拟结果只用于界面失败场景，不替代真实连接验收。脚本结束会解除请求模拟并断开自动化连接，保留工具窗口。

公众号本地入口为 `/wechat`，提供响应式说明页；公众号认证、网页 OAuth、JS-SDK、菜单配置、消息签名校验和回调均未接入，属于 Issue #4。部署并验证公众号配置前，不宣称已提供公众号服务。

## 检查与测试

```bash
make check          # Django 系统检查、Python 编译、Web / 小程序类型检查
make test           # 无外部依赖的后端单元测试 + Web 协议测试
make build          # Vue 类型检查与生产构建
```

完成基础服务启动、迁移及 Worker 启动后：

```bash
make health
make integration
uv run python services/backend/manage.py makemigrations --check --dry-run
```

真实集成测试在单独的 `test_paper_assistant` 数据库中从空库执行迁移，并测试 vector 查询、Neo4j 连接、S3 自制文本写入读取删除、错误 S3 凭据返回 403 和 Worker 消息往返。S3 测试只创建随机命名的 `paper-test-*` 临时桶并清理，不操作已有资料。集成测试缺少服务时失败，不伪装成跳过或成功。

浏览器测试（自动启动 Django WSGI 和 Vite，也可复用已启动的本地服务）：

```bash
pnpm --filter @paper/web exec playwright install chromium
pnpm --filter @paper/web test:e2e
```

覆盖桌面与手机尺寸、真实 API 代理、503 依赖故障展示、断网重试恢复、`/wechat` 直接访问与横向溢出检查。依赖未启动时可以验证真实 503 路径，但不代替成功路径的多服务联调。测试截图和失败追踪在 `apps/web/test-results/`，不进入 Git。

GitHub Actions 的 `Engineering checks` 工作流包含上述检查、真实 Docker 基础服务、空库迁移、集成测试、浏览器测试及完整容器启动检查。工作流尚未在远端执行时，不应把它记作通过。

## 当前验证记录（2026-11-04）

- 已执行：依赖安装与锁定、Django 系统检查、Web / 小程序 TypeScript 检查、Vue 生产构建。
- 已执行：后端 12 项单元测试、Web 6 项协议测试。
- 已执行：桌面 / 手机浏览器 4 项测试；分别验证无依赖时的真实 503 和完整容器环境的真实 200；请求失败和重试恢复通过。
- 已执行：Compose 配置语法校验、公开镜像标签存在性检查。
- 已执行：完整容器构建启动、PostgreSQL 空库迁移和重复迁移，`makemigrations --check --dry-run` 无遗漏；五项依赖检查全部返回 `ok`。
- 已执行：5 项真实集成测试全部通过；覆盖 pgvector 查询、Neo4j / Redis 连接、S3 读写删除与错误凭据、Worker 任务往返。
- 已执行：使用独立 Compose 项目和全新数据卷再次验证 S3 首次读写与错误凭据；专用测试容器和数据卷已清理，主开发环境保留。
- 已执行：停止真实 Worker 后 API 返回 503，且仅 Worker 标记不可用；恢复 Worker 后健康检查及任务往返通过。
- 本机调整：Windows 无法绑定 Redis 默认端口，`.env` 使用 `REDIS_PORT=16379` 和对应 `REDIS_URL`；示例保留可配置的默认端口 6379。
- 远端 CI 结果见关联 PR 的 Checks。

## 小程序模拟器验收（2026-11-05）

微信开发者工具 2.02.2609240 已打开本项目的 Windows 本地验收副本。账号 AppID 仅配置在该副本。以下五项由 `tests/acceptance.cjs` 在基础库 3.17.6 的模拟器中验证。

| 验收项 | 实际结果 |
| --- | --- |
| 打开项目并编译首页 | 首页路由为 `pages/index/index`，初始状态为“尚未连接”，检查按钮可用 |
| 点击按钮请求真实 API | `wx.request` 收到容器内 Django 存活接口的成功响应，页面显示“API 已连接” |
| 模拟网络中断 | 请求期间显示加载状态，随后提示“连接失败”并结束加载 |
| 模拟 HTTP 503 | 页面显示“API 返回异常”和 HTTP 503 |
| 解除模拟后重试 | 再次点击按钮，真实请求恢复成功 |

报告和截图位于执行测试的小程序目录下的 `test-results/acceptance.json` 和 `test-results/connected.png`。本次范围为开发者工具模拟器，真机预览和发布尚未执行。

## 常见问题

- **WSL 提示找不到 Docker / Windows 提示 Linux Engine pipe 不存在**：启动 Docker Desktop 的 Linux 容器引擎，在 Resources → WSL Integration 开启当前发行版，重新打开终端，确认 `docker info` 显示服务端信息。
- **端口占用 / Windows 拒绝绑定**：停止本项目另一种启动方式；只停止确认属于当前项目的进程。PostgreSQL 宿主机端口可用 `.env` 中的 `POSTGRES_PORT` 调整。Redis 可设置 `REDIS_PORT=16379`，并将本机应用使用的 `REDIS_URL` 同步改为 `redis://127.0.0.1:16379/0`；容器内部仍使用 `redis:6379`。宿主机端口映射以 `docker compose ps` 为准。
- **Web 显示 API 连接失败**：确认 API 进程在运行、Vite 的代理目标可达；不要用静态文件服务器替代配置了 `/api` 代理的 Vite。
- **就绪检查返回 503**：按 `checks` 中的故障服务查看日志。PostgreSQL 已连接但缺 `vector` 扩展或仍有迁移未应用，也会判定未就绪。只有 Redis 可达时才继续检查 Worker。
- **Worker 没有响应**：确认 API 与 Worker 使用相同 `REDIS_URL`，运行 `check_worker` 验证真实任务消费。`system.ping` 只用于工程诊断，不是论文业务任务。
