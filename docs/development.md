# 开发说明

本工程提供 [Issue #1](https://github.com/jiuwen567/ai-paper-assistant/issues/1) 的基础设施，以及 [Issue #2](https://github.com/jiuwen567/ai-paper-assistant/issues/2) 的账号、项目和权限实现。Issue #3 提供持久后台任务与字数统计样例；Issue #5 提供材料上传与版本管理；Issue #6 提供后台解析和 Web 原文定位；Issue #7 提供题录、证据、笔记和项目内检索。Issue #8 提供受限 Pi 执行、调用记录和待核对摘记；稿件由后续任务接入。

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
  core/                        账号、项目、权限、健康检查、迁移与测试
  worker/                      独立 Celery 进程及诊断任务
infra/seaweedfs/filer.toml      Filer 元数据持久化配置
infra/seaweedfs/master.toml     本地 Volume 按需分配配置
scripts/init_dev.py            生成本地凭据及 S3 配置
compose.yaml                   基础服务与可选应用容器
```

API 与 Worker 共用 Python 依赖和镜像，但分别启动进程。Redis 只承担任务传输与短期结果，不替代 PostgreSQL 的业务事实源。业务任务状态、输入快照、尝试、租约、进度和错误保存在 PostgreSQL。Celery Beat 每 15 秒扫描等待任务与过期租约；outbox 由关系同步任务接入。

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

然后分别运行 API、Worker、调度器和 Web：

```bash
make api
```

```bash
make worker
```

```bash
uv run --directory services/backend celery -A worker.app beat --loglevel=info --schedule=/tmp/paper-celerybeat-schedule
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

配置由 `config/settings.py` 从仓库根目录加载；进程环境变量优先。不要在小程序、`VITE_*` 或客户端代码中放 AppSecret、数据库密码、模型密钥。未配置微信或生成模型时，相应入口明确返回不可用，不影响其他功能。

| 服务 | 宿主机地址 | 数据卷 |
| --- | --- | --- |
| PostgreSQL | `127.0.0.1:5432` | `postgres_data` |
| Neo4j | Browser `7474`、Bolt `7687` | `neo4j_data`、`neo4j_logs` |
| SeaweedFS S3 | `127.0.0.1:8333` | `seaweedfs_data`（包含 Filer LevelDB 元数据和文件卷） |
| Redis | `127.0.0.1:6379`（可由 `REDIS_PORT` 修改） | `redis_data` |

SeaweedFS 加载本地生成的 S3 凭据，Filer 与 Master 不发布宿主机端口。Redis 只暴露本机端口，本地开发未另设密码。Neo4j 用户固定为 `neo4j`；PostgreSQL 数据库名与用户名可在首次初始化前修改。

SeaweedFS 按需每次分配 1 个 Volume，单节点最多 32 个，每个上限 128 MB，适用于本地开发。容器健康检查同时确认 Master 已成为 Leader、存储节点有可分配容量和 Filer 可访问，避免重启选举期间提前宣告就绪。只启用本阶段需要的 S3 接口，未启用额外的 IAM、Iceberg 和 Lance 服务。

首次迁移安装 `vector` 扩展，应用 Django 自带的 auth、contenttypes、sessions 迁移，以及项目、成员和规则版本迁移。迁移不会创建用户或演示论文。初始化数据库用户有安装扩展权限；生产应另外设计最小权限和迁移角色。

数据库密码保存在已有数据卷内，修改 `.env` 不会自动更改 PostgreSQL / Neo4j 已初始化的密码。应通过数据库管理命令同步修改；修改 S3 凭据后重跑初始化脚本并重启 SeaweedFS。

`.env`、`.local/`、虚拟环境、node_modules、构建产物、浏览器测试结果、真实资料和运行数据均由 `.gitignore` 排除，构建上下文也通过 `.dockerignore` 排除。不要提交这些文件。

## 账号与项目

Web 首页为“我的论文”，环境检查位于 `/environment`。账号使用 Django 内部用户和数据库 Session；当前不开放自助注册或密码找回，微信身份通过小程序显示的一次性绑定码，在已登录 Web 账号下确认。

本机开发创建普通账号：

```bash
uv run python services/backend/manage.py shell
```

在交互终端执行，用户名替换为自己的测试账号，密码通过隐藏输入读取：

```python
from getpass import getpass
from django.contrib.auth import get_user_model
get_user_model().objects.create_user(username="local-author", password=getpass("密码："))
```

容器模式用 `docker compose exec api python manage.py shell` 进入同一终端。重复创建已存在的用户名会失败；修改密码用 `manage.py changepassword 用户名`。服务不会提供默认账号或固定密码。

登录后可创建项目，保存论文类型、写作要求与模板选择。项目中的 `department-default` 只是选择标识；导出时另选已登记的不可变模板版本。当前随项目提供的是自制示例规则，不代表任何院系认可；真实院系要求与 Word 打开验收仍待确认，详见本文的 Word 导出章节。

| 身份 | 权限 |
| --- | --- |
| 创建者 | 作者全部权限，添加、调整或移除已有账号的项目成员资格 |
| 作者 | 查看和编辑项目，新增规则版本，在当前规则允许时通过 AI 权限检查 |
| 审阅者 | 查看项目、成员和规则历史；不能编辑、修改成员或启动 AI 辅助 |
| 非成员 | 列表不可见；直接请求项目返回 404，包括超级用户 |

创建者始终保留作者权限，本阶段不提供创建者转移或移除。添加已有成员会更新角色；成员管理仅凭准确用户名，不提供全站用户目录。撤权后下一次请求重新校验，已下载或已显示的内容无法追回。

规则初始为 v1、未核对且全部 AI 功能关闭。核对必须填写规则来源与来源版本，再分别允许 `reading`、`comparison`、`review`、`expression`、`feedback`。未核对时服务端拒绝启用任何功能，未知能力也拒绝。每次规则保存新增不可由 API 改写的历史版本，记录操作者和时间；取消核对会保存关闭全部辅助的新版本。

接口均位于 `/api/v1/`：

| 路径 | 方法与用途 |
| --- | --- |
| `auth/session/` | GET 获取身份与 CSRF token；POST 用户名/密码登录并返回新 token |
| `auth/logout/` | POST 退出并使当前 Session 失效 |
| `projects/` | GET 授权项目列表；POST 创建项目与默认规则 |
| `projects/{id}/` | GET 详情；PATCH 更新项目设置 |
| `projects/{id}/members/` | GET 协作者列表；POST 添加或更新角色 |
| `projects/{id}/members/{user_id}/` | DELETE 移除成员 |
| `projects/{id}/policies/` | GET 规则历史；POST 保存新规则版本 |
| `projects/{id}/ai-permissions/` | POST 检查 `action` 与 `policy_version`，不创建或执行任务 |

所有写请求包含 `X-CSRFToken`；登录也校验 CSRF，成功登录后 token 旋转。开发代理的可信 Origin 默认仅允许本机 5173 端口，可通过 `DJANGO_CSRF_TRUSTED_ORIGINS` 显式配置；非 DEBUG 默认无可信 Origin，Session/CSRF Cookie 仅通过 HTTPS 发送。

列表统一按 `?page=1` 分页，每页 20 条，返回 `count/next/previous/results`。成员列表只返回协作者，创建者信息在项目详情中。修改项目、成员和规则均须提交详情中的 `version`；服务端在项目行锁内检查版本与当前权限，成功后递增版本。重复或并发的旧提交返回 409，页面保留输入，重新加载后再编辑。规则的 `policy_version` 独立计数，AI 检查携带旧规则版本同样返回 409。

后续文件与任务接口复用 `core/access.py`：先调用 `require_project`；资源 ID 查找调用 `require_project_resource`，同时限定资源实际的 `project_id`，不得仅依赖 URL 或界面筛选。事务写入传 `lock=True`，成员变更使用同一项目锁。AI 任务在入口、每次工具调用和发布结果前分别调用 `require_ai_action`；发布时必须在事务内持有项目锁，不能把预检查成功当作持久授权。业务任务取消、状态持久化与迟到结果处理由 #3/#8 实现，本任务不提供模型执行入口。

## 微信小程序与公众号

1. 安装当前稳定版微信开发者工具，导入 `apps/miniapp`，而非 `miniprogram` 子目录。
2. `project.config.json` 已设置 TypeScript 编译、Skyline 和 glass-easel。`touristappid` 只是占位符，官方自动化接口会对它返回 `APPID_ERROR`；编译验收必须配置当前登录账号有开发权限的真实测试 AppID，不需要 AppSecret。
3. 在工具中按工程配置选择基础库 3.17.6 并编译。`pnpm check` 执行 TypeScript 检查，微信开发者工具执行小程序编译和预览。
4. API 默认地址位于 `miniprogram/config/api.ts`。Windows 工具访问 WSL 服务时，先在 Windows 浏览器确认 `http://127.0.0.1:8000/api/v1/health/live/` 可达。
5. 在模拟器点击“检查 API 连接”，确认界面显示“API 已连接”。若请求报合法域名校验错误，可在该项目的本地调试设置中处理，公共工程配置保留 `urlCheck: true`。
6. 真机的 `127.0.0.1` 指向手机本身。真机调试改用可达 HTTPS API，配置 request 合法域名，恢复域名校验；不要向客户端添加服务端密钥。

小程序首页保留 API 检查，点击“我的论文”进入微信登录、项目列表、详情和后台任务。Web 与小程序共用内部用户和项目权限。材料上传、版本与 PDF/DOCX 下载入口已接入；证据卡和修改待办由后续任务接入。

服务端 `.env` 配置 `WECHAT_APP_ID`、`WECHAT_APP_SECRET`，重建 API 镜像或重启本机 API。AppID 必须与小程序工程一致，AppSecret 只放服务端，不复制进小程序或公开仓库。未配置时登录明确返回 503，不提供模拟身份登录后门。`wx.login` 的 code 只发送至业务 API，由服务器调用 [微信 code2Session](https://developers.weixin.qq.com/miniprogram/dev/server/API/user-login/api_code2session.html)。不存储或返回 session_key，不依据 UnionID、昵称、手机号自动合并。

绑定流程：小程序点击“微信登录” → 复制 5 分钟有效的绑定码 → 在 Web 登录目标内部账号，展开“微信账号”并确认绑定码 → 小程序重新登录。重新获取绑定码会废弃上一个码；每个码只能兑换一次，账号冲突先解绑。绑定接口只接受带 CSRF 的 Web Session，不能用小程序 token 代替 Web 确认。

小程序会话有效期 7 天，过期后重新调用微信登录。Web 和小程序均可解绑；解绑立即撤销所有该身份会话，重新绑定不会恢复旧 token。退出小程序只撤销当前会话，不删除项目。公众号 H5 使用普通 Web 登录，不依赖微信网页 OAuth。

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

公众号入口为 `/wechat`，提供绑定步骤和菜单使用说明。生成菜单 JSON：

```bash
uv run python services/backend/manage.py wechat_menu --web-url https://your-public-site.example
```

该命令只输出配置，不调用发布接口。管理员在公众号后台配置“我的论文”小程序菜单，使用实际 AppID 和 `pages/projects/projects`；“使用帮助”及不支持小程序的回退地址指向网站 `/wechat`。公众号需具备自定义菜单及跳转小程序权限，关联目标小程序；网站需已部署且 HTTPS 可达。权限与关联要求以实际账号后台和[微信自定义菜单文档](https://developers.weixin.qq.com/doc/offiaccount/Custom_Menus/Creating_Custom-Defined_Menu.html)为准。首版不使用网页 OAuth、JS-SDK 或消息回调，不能据此宣称已获得相关账号能力或公开发布审核通过。

真实验收需开发者用有权限的微信账号完成：登录并绑定、双端读取同一项目、解绑后旧会话拒绝访问，以及从公众号菜单打开目标小程序和帮助页。没有对应账号配置时保留待验收状态，不用单元模拟替代。

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

真实集成测试在单独的 `test_paper_assistant` 数据库中从空库执行迁移，并测试账号与项目权限、规则版本冲突、vector 查询、Neo4j 连接、S3 自制文本写入读取删除、错误 S3 凭据返回 403 和 Worker 消息往返。S3 测试只创建随机命名的 `paper-test-*` 临时桶并清理，不操作已有资料。集成测试缺少服务时失败，不伪装成跳过或成功。

只运行账号和项目测试时，需要 PostgreSQL，无需其他服务：`uv run pytest services/backend/core/tests/test_projects.py`。这些测试仍执行真实迁移和数据库约束，不使用 SQLite 替代。

浏览器测试（自动启动 Django WSGI 和 Vite，也可复用已启动的本地服务）：

```bash
pnpm --filter @paper/web exec playwright install chromium
pnpm --filter @paper/web test:e2e
```

覆盖桌面与手机尺寸、真实登录与 CSRF、项目编辑、规则变更、越权与撤权、真实 API 代理、503 依赖故障展示、断网重试恢复、`/wechat` 直接访问与横向溢出检查。账号场景要求 PostgreSQL 已启动并迁移；测试为每个用例生成随机账号与密码，结束时只清理对应随机前缀的专用数据。测试只在 DEBUG 环境运行，失败追踪可能包含测试会话，不公开发布。依赖未启动时可以验证环境页的真实 503 路径，但不代替成功路径的多服务联调。测试截图和失败追踪在 `apps/web/test-results/`，不进入 Git。

GitHub Actions 的 `Engineering checks` 在 PR 上运行系统与类型检查、单元测试和构建；同分支新提交取消旧检查，合并到 main 后不重复执行。完整 Docker 启动、空库迁移、集成及浏览器测试在 Actions 中手动运行该工作流。开发时仍按改动范围执行本地数据库或外部服务联调，不因常规 CI 精简而省略功能验收。工作流尚未在远端执行时，不应把它记作通过。


## 材料上传与版本

项目中打开“材料”，上传文献、研究材料或作者原稿。首版支持 PDF、DOCX、UTF-8 CSV/TXT，单文件最多 20 MB。PDF 不接收加密文件，DOCX 仅检查标准正文包结构；本步骤不解析正文、不执行文件内容。CSV 必须有非空列名且每行列数一致，实验结果解析使用下节的固定字段约定。

Web 可新增材料、选择已有材料上传新版本、查看每版状态并下载原件。小程序在项目详情选择聊天文件上传，失败后可“重试同一文件”；重新进入时从对应版本“重新选择文件上传”。小程序预览 PDF/DOCX；CSV/TXT 原件通过 Web 下载。所有操作复用项目权限，审阅者不能上传；下载由业务 API 鉴权转发，不暴露 S3 凭据或公共对象链接。已经下载的副本无法撤回。

上传分为两步：`POST /api/v1/projects/{project}/uploads/` 登记 `request_key`、材料名称/分类、文件名与大小；新版本还需 `material_id`、`base_revision`。随后向 `/uploads/{version}/` 提交 multipart `file`。同一用户同请求键返回同一版本，输入变化或旧材料版本返回 409。上传登记可能占用版本号，失败记录保留，不重新编号。

文件先进行格式与大小检查，再登记摘要和执行租约、写入独立 S3 对象、读回核对 SHA-256，最后在 PostgreSQL 发布可用状态。重复传输只允许相同内容，已可用的旧对象不会被新版本覆盖。发布时重新检查上传者权限。列表和版本记录显示等待上传、上传校验中、可用或失败。

服务端 `MATERIAL_BUCKET` 默认 `paper-materials`；首次上传会创建该私有桶，部署账号需具备相应权限。没有完成的对象始终有版本记录和对象键。对象写入成功但数据库发布失败时，可等待 2 分钟租约过期后重试同一文件，或运行：

```bash
uv run python services/backend/manage.py reconcile_uploads
```

命令每批最多检查 100 个已登记对象，不扫描或删除未知对象。对象缺失、摘要不匹配或上传者撤权时保留失败状态；物理删除与生命周期清理由 #18 接入。测试命令：`uv run pytest services/backend/core/tests/test_materials.py`，使用真实 PostgreSQL 和随机 `paper-test-*` S3 桶，仅清理对应自制数据。

Web 容器仅安装 Web 依赖；小程序自动化 SDK 仍由本机/测试环境安装，不进入 Web 运行镜像。

## 材料解析与原文定位

Web 材料版本中选择“查看原文 → 解析材料”。任务由真实 Worker 执行，离开页面后仍可从解析历史查回；“重新解析”新增独立记录，“重试解析”沿用失败记录与输入快照。片段、解析版本和成功状态在同一事务发布；存储或数据库故障保留错误代码，不展示半份结果。

- PDF 提取文字层，按文件第几页定位，并显示 PDF 页码标签；标签不保证等于纸面印刷页码。点击片段显示相邻片段，PDF.js 在本地绘制对应文件页，也可在新标签打开定位页或下载原件。预览失败提供重试；不执行 PDF 脚本或加载外部服务。
- DOCX 提取正文顶层段落与 1–9 级标题，空段仍占段落序号；使用段落与文字偏移，不生成稳定页码。表格、图片、公式不解析，并标记部分文字；版式以原件为准。
- CSV 列顺序固定为 `experiment,metric,value,unit,conditions`。实验和指标名称必填，value 为有限数值；锚点保存记录序号、起止文件行和字段，支持带引号的跨行字段。表头不符保留 `csv_schema` 失败，可更正原件后上传新版本。
- UTF-8 TXT 按行定位。单片段最多 4000 字符，提取总量最多 100 万字符、1 万片段；超过上限不发布结果。没有可提取文字时提示 `no_text`，不执行 OCR。

解析记录固定原件摘要、文件版本、解析器版本和任务代次。重试前后检查当前权限、规则、原件状态与租约；撤权、取消和迟到结果不能发布。解析器版本升级后旧失败任务需重新解析，已经发布的历史片段保留。提取文字不代表该材料支持某个论点。

接口位于 `/api/v1/projects/{project}/`：文件版本的 `files/{version}/parses/` 创建和列出解析；`parses/{run}/chunks/` 分页列出片段；`chunks/{chunk}/` 返回固定版本的定位及上下文。`files/{version}/preview/` 只允许 PDF 内联预览，经过项目鉴权；普通下载行为不变。

测试命令：`uv run pytest services/backend/core/tests/test_parsing.py services/backend/core/tests/test_parse_jobs.py`。解析器边界参考 [pypdf 文字提取说明](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)。

## 后台任务

项目页面可提交字数统计样例、查看进度和尝试记录、取消或重试。样例不调用模型。刷新或离开页面不会丢失任务；审阅者只能查看，任务输入不由客户端选定创建者或执行代次。

- `POST /api/v1/projects/{project_id}/jobs/` 接收 `kind=sample`、`idempotency_key`、`policy_version` 和 `input_snapshot`（`text`、`source_version`、可选 `steps=1..10`）。同用户同项目同键且输入一致时返回同一任务，输入不同返回 409。
- 任务详情与列表提供输入版本、状态、尝试记录和结果；`/{job_id}/cancel/`、`/{job_id}/retry/` 要求提交当前 `generation`。每项最多 3 次尝试，超时进入可重试失败，取消与成功结果不能重新运行。
- Worker 领取时创建新执行代次，30 秒租约内通过心跳续期。每个步骤前和发布时重新校验租约、创建者权限及规则版本；迟到结果、撤权或规则变化均不会发布。后续模型适配也必须在每次工具或模型调用前使用该检查。
- 队列发送失败保留 `queued/dispatch_failed`；调度器恢复后重新发送。重复消息由数据库领取锁拒绝。Worker 中断后，调度器将过期任务标记为 `failed/lease_expired`，作者可重试。错误只保存受控代码和文案，不保存底层异常正文。
- 本地容器模式包含 `scheduler` 服务；本机模式需运行上述 Beat。调度器故障或停机恢复后可手动执行 `uv run python services/backend/manage.py recover_jobs`。恢复扫描每批最多 100 项，按更新时间轮转；任务量增加后再优化批量调度。

任务测试：`uv run pytest services/backend/core/tests/test_jobs.py`。需要 PostgreSQL 和 Redis；真实 Worker 重启测试启动专用队列与独立测试库进程，结束时清理。字数统计和材料解析为确定性任务；模型和导出任务随各自 Issue 接入，不把样例输出当作真实 AI 结果。

## 文献卡、证据卡与检索

Web 的材料版本“查看原文”中可编辑文献卡：题录、资料范围、题录摘要、作者笔记和标签分开保存。默认“范围未核对”；“仅摘要”不会标成全文，全文范围由作者明确标记，不是模型验证结论。保存当前原文片段生成证据卡，固定该片段及当时的题录版本；之后编辑题录不会把旧摘要证据自动改成全文。笔记和标签保留修订历史，旧版本提交返回冲突；重复提交不重复创建卡片。

“阅读与证据”提供原文关键词检索、证据笔记/标签筛选和原文回查。小程序项目中同名入口可看证据、上下文及补充笔记；微信 `wx.request` 使用 PUT 更新笔记，与 Web PATCH 共用版本检查。真实微信登录和界面仍需按微信验收流程联调。

材料可从检索和新任务撤回，保留历史证据及原件以便复核；恢复材料时状态版本递增。永久删除使用已接入的“删除与清理”流程。新证据、解析和索引拒绝已撤回资料；检索限定当前授权项目、有效文件和该文件最近成功解析，历史证据继续引用原片段。

语义检索使用管理员配置的外部嵌入 API 与 PostgreSQL pgvector，不下载或部署本地向量模型。先在服务端 `.env` 设置：

```dotenv
EMBEDDING_BASE_URL=https://供应商地址/v1
EMBEDDING_API_KEY=由管理员填写
EMBEDDING_MODEL=供应商模型标识
EMBEDDING_DIMENSION=供应商输出维度
EMBEDDING_MODEL_REVISION=供应商版本或管理员版本标记
EMBEDDING_SEND_DIMENSIONS=false
```

地址须兼容 `POST /embeddings`，以 Bearer 密钥认证、接收字符串数组，返回带 `index` 的 float 向量。默认不发送 `dimensions`，仅校验实际返回维度；供应商支持自选维度时才开启 `EMBEDDING_SEND_DIMENSIONS`。例如 [SiliconFlow 嵌入接口](https://api-docs.siliconflow.cn/docs/api/embeddings-post)只对部分模型支持该参数。这里描述协议，不替作者选择供应商或把模型名猜成配置。正常部署使用 HTTPS，只有 DEBUG 开发环境允许 HTTP 协议夹具。

```bash
uv run python services/backend/manage.py check_embeddings
```

该命令仅发送两条自制短文本，验证认证、响应及维度，不读取项目资料。配置后重建 API、Worker 和 scheduler，作者在“检索索引”点击“重建检索索引”。索引任务每批发送至多八个 256 字符片段、请求超时 30 秒，不自动重试 HTTP 请求；网络/限流/服务端错误保留可重试失败，重试由现有任务接口发起。查询最多 200 字，同样调用该 API。不会跟随重定向，不记录密钥或上游错误正文。

索引保留模型名、维度、处理版本、原片段摘要及材料状态。既有 `artifact_digest` 字段在 API 模式表示端点、模型、维度、版本和参数的配置摘要，**不是供应商权重摘要**；地址和密钥不进入客户端可见快照。密钥轮换不改变向量空间，供应商同名模型升级时管理员应更新 `EMBEDDING_MODEL_REVISION` 并重建。旧本地索引不能用于 API 查询，排队中的旧模型任务会在有效新配置下取消。无数据库结构变化，历史索引和运行记录保留，不伪造迁移后的向量。

原文按 256 字符窗口编码，最多 5000 个窗口；全部向量与任务成功状态一起提交，中间批次失败不会发布部分索引。换模型、重新解析、新增材料或撤回/恢复后需重建；每批发送前、发布和查询返回前复核权限、规则和输入。语义检索需要项目允许“文献阅读”；审阅者可按已批准规则检索，不能构建索引或修改笔记。启用后所选资料片段及查询会发送给配置的供应商；关键词检索与资料维护不调用 API。

常规 PR CI 不调用付费 API，也不下载模型。完整手动 workflow 使用 `compose.test.yaml` 的固定向量 HTTP 夹具验证链路，不部署模型、不代表真实供应商或语义质量。需要本地重放浏览器验收时使用 `COMPOSE_FILE=compose.yaml:compose.test.yaml make up`；结束后用普通 `make up` 恢复服务配置并停止 `embedding-fixture` 测试容器。真实供应商验收须配置有效服务，使用专用自制材料单独记录。

## 阅读与检索验证（2026-11-05）

以下为切换 API **之前**的历史本地模型验证记录，不能视作当前 API 验收：

- 后端完整测试 116 项通过，新增 11 项使用真实 PostgreSQL、SeaweedFS、pgvector 和本地模型；验证摘要范围、不可变摘录、笔记冲突、数据库关系约束、重复执行、提交回滚与重试、执行/检索中撤权、撤回恢复、512/384 维模型切换及小程序 token 笔记可由 Web 读取。补充题录关键词检索后，11 项用例重新通过。
- 20 项桌面/手机尺寸浏览器测试通过；新流程使用真实 Worker 与本地中文模型，覆盖题录、摘要证据、笔记、原文上下文、语义检索和撤回后排除。初次失败来自测试对原生 select 的定位方式，改用可访问 combobox 角色后通过。
- 小程序会话及证据页面共 5 项模拟测试、Web 6 项协议测试通过。模拟页面验证笔记 PUT、旧版本冲突保留草稿、撤权清空；真实微信开发者工具和真机未运行，Issue #7 保留这部分验收。
- Ruff、双端类型检查、构建、迁移与遗漏检查、容器重建、五项依赖检查和真实 Worker 往返通过。模型仅显式下载公开文件，未使用真实论文或发送项目资料到外部模型服务。

## 材料解析验证（2026-11-05）

- 17 项解析测试通过，使用自制 PDF、DOCX、CSV、TXT、真实 PostgreSQL 和 SeaweedFS；覆盖页序/标签、段落/标题、跨行 CSV、并发请求、重新解析、存储失败重试、事务回滚、过期代次、取消、撤权、跨项目数据库约束及扫描件失败。
- 后端完整测试 105 项通过，迁移及遗漏检查、Ruff、双端类型检查、Web 构建、依赖健康检查与真实 Worker 往返通过。最后补充 DOCX 嵌套结构提示后，4 项解析器测试重新通过。
- 18 项桌面/手机尺寸浏览器测试通过，新流程调用真实 Worker；验证固定版本上下文、旧解析历史、扫描件错误和 PDF 绘制失败重试。首次截图发现原生 iframe 空白，改为本地 PDF.js 后验证画布实际像素并查看截图；字体、字符映射及解码资源随构建部署。
- 本次不调用模型，不承诺 OCR 或复杂版式无损提取；微信真实验收仍保留在 #4/#5。轻量 CI 不运行这些基础设施和浏览器测试，完整验证在本地执行。

## 材料上传实现验证（2026-11-05）

- 11 项材料测试通过，真实 PostgreSQL 与 SeaweedFS 覆盖原件读写及 SHA-256、版本不覆盖、重复/并发登记、损坏文件、旧版本冲突、存储失败、对象写入后数据库发布失败对账、撤权拦截和跨项目下载拒绝。PDF/DOCX/CSV/TXT 样例均为自制；专用随机桶已清理。
- 自制小程序 token 经过实际认证后上传，Web 账号可读回同一材料；这验证业务 API 的双端身份一致，不代替真实微信登录与真机上传。
- 与账号、任务和微信测试合并运行共 71 项通过。小程序会话层 3 项模拟测试及 Web 6 项协议测试通过。
- 桌面/手机尺寸共 16 项浏览器测试通过，包含两版文件逐字节下载对比、损坏 PDF 失败状态及原有功能回归。浏览器测试清理仅处理其随机账号项目下的自制对象。
- Ruff、双端类型检查、构建、迁移遗漏检查和容器重建启动通过。初次 Web 镜像构建因无关小程序自动化依赖下载发生 DNS 失败；改为仅安装 Web 依赖后构建及完整浏览器测试通过。
- 未执行微信开发者工具新上传页面与真机端到端验收，Issue #5 保留待验收。物理删除、资料解析与正文导入由后续任务接入；未操作真实论文或发布外部服务。

## 微信绑定实现验证（2026-11-05）

- 18 项微信 API/数据库测试通过，微信身份响应为自制模拟；真实 PostgreSQL 验证一次性码、过期、重复、应用隔离、账号冲突、并发兑换、Session/CSRF、token 撤销与跨项目拒绝。
- 与 14 项任务、28 项项目权限用例合并运行，共 60 项通过。小程序会话层 2 项模拟 wx 测试和 Web 原有 6 项协议测试通过。
- 桌面/手机尺寸共 14 项 Playwright 测试通过，包含自制微信身份的 Web 确认绑定、解绑和旧码拒绝；不会把该测试称作真实微信 code2Session 联调。
- 双端 TypeScript、Web 构建、Ruff、迁移遗漏检查通过，容器 API 执行新迁移。首次回归中的旧文案断言及规则历史定位已按新界面修正，完整浏览器用例重新通过。
- 未执行：真实 AppSecret 登录、微信开发者工具新页面编译、真机与公众号菜单。仓库开发配置未提供微信服务端配置，桌面自动化工具因 WSL 工作目录识别错误无法初始化。Issue #4 保留待验收，不将模拟测试计为真实双端验收；没有发布外部服务。

## 后台任务验收（2026-11-05）

- 14 项任务测试通过，使用真实 PostgreSQL；覆盖幂等、并发创建与领取、心跳、过期重试、取消、规则变化、撤权、跨项目访问、只读角色及次数上限。
- 专用测试队列中强制终止真实 Celery Worker 后重新启动，旧代次保留失败，新代次成功；测试缩短了租约等待时间，未把该部分记录为真实 30 秒等待。
- 28 项原有项目权限测试通过；桌面与手机尺寸共 8 项账号、项目及后台任务浏览器测试通过，刷新页面后可查回真实 Worker 输出。
- Ruff、Django 系统检查、双端 TypeScript 检查、Web 构建和迁移遗漏检查通过。容器增加调度器并执行迁移；首次桌面测试因旧 API 镜像失败，重新创建应用容器后相关 8 项测试通过，未删除数据卷。
- 取消和撤权针对任务状态及发布事务验证；样例不调用模型，真实模型调用中断与输入资源有效性由后续模块联调。

## 账号与项目验收（2026-11-05）

- 后端：12 项原有单元测试、33 项真实集成测试通过。其中 28 项覆盖登录/退出、CSRF、项目隔离、作者/审阅者权限、成员撤权、规则默认关闭、版本历史、旧请求冲突、数据库约束与并发规则更新。
- Web：6 项协议测试通过；完整容器环境下 10 项桌面/手机尺寸浏览器测试通过，覆盖真实登录、创建与编辑、模板选择、规则版本与禁用功能拦截、成员管理、撤权、会话失效后的重新登录及原有环境页回归。
- 工程：Django 系统检查、Python 编译与 Ruff、Web/小程序 TypeScript 检查、Web 生产构建通过；PostgreSQL 测试库从空库迁移成功，本地重复迁移无变更，`makemigrations --check --dry-run` 无遗漏。
- 联调：容器构建启动通过，五项依赖检查及 Worker 任务往返通过。首次容器验收发现已有 Web 容器仍使用旧镜像，强制重新创建应用容器后再运行并通过浏览器测试；未清理基础服务数据卷。
- 提交前复查：统一未授权项目与不存在项目的 404 响应，避免通过错误文案探测项目是否存在；28 项项目权限测试重新运行通过。分支命名规范已写入协作说明。
- 边界：跨项目资源 ID 使用规则资源验证统一鉴权函数；真实文件与业务任务接口尚未实现，需在 #3/#5/#8 接入并重新联调。AI 接口仅检查权限，未执行模型，未发布外部服务。远端 CI 结果以关联 PR 的 Checks 为准。

## 基础工程验证记录（2026-11-04）

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

## Pi 受限执行（Issue #8）

在服务端 `.env` 配置 `AI_MODEL`、`AI_BASE_URL`、`AI_API_KEY`。端点须兼容 OpenAI Chat Completions 的流式工具调用，`AI_BASE_URL` 通常以 `/v1` 结尾；不自动选择供应商或读取其他客户端的账号配置。未配置时返回 `model_unconfigured`，不创建任务。容器中的本地模型地址须能从 Worker 访问；不要把密钥放入客户端或提交到仓库。配置后重建 API、Worker 和 scheduler。`AI_MAX_TOKENS_FIELD` 默认 `max_tokens`（包括本机 Ollama 0.40.14）；供应商要求新字段时显式改为 `max_completion_tokens`。只接受这两个值，不按端口猜供应商。该选择进入任务快照，变化后旧任务取消，须按新配置重新创建；不改写既有调用记录。

`AI_REASONING_EFFORT` 留空时不发送该字段，沿用服务默认；可显式设为 `none`、`low`、`medium` 或 `high`，须先验证供应商与模型支持该值。模式会进入任务快照，变化后旧任务取消。Pi 的本地模型元信息 `reasoning=false` 不等于请求关闭服务端推理；本机 Ollama 0.40.14 已验证 `reasoning_effort=none` 关闭推理内容，其他级别含义由供应商决定。调用次数、输出 token 上限、总时限和工具权限独立保持，不能据此假定内容更准确。接口和模型均不能修改管理员选择。

作者先启用当前规则的 `reading`，上传并解析材料，再在阅读区选择资料或在原文面板选择“AI 阅读”。后台任务显示取消、重试、待核对摘记、原文回查和调用记录。审阅者只能查看；来源的摘要/全文/未知范围来自题录版本，模型不能自行提升。当前 Web 入口使用下述结构化阅读任务；旧短摘记接口保留执行框架协议。两者均不提供整篇论文写作。

- `POST /api/v1/projects/{project_id}/ai-tasks/`：提交 `idempotency_key`、`policy_version` 和 1–5 个 `version_ids`。不接受提示词、模型、工具或身份字段。同一键和输入返回原任务，不同输入返回 409。
- `GET /api/v1/projects/{project_id}/ai-tasks/{job_id}/trace/`：返回各代次的模型、提示词版本、输入快照摘要、用量、耗时、错误代码及有限事件。未返回用量时为 null，不能当作零用量。
- 现有 `jobs/` 接口提供查询、取消和重试。失败至多重试至 3 个代次；旧代次、旧权限或旧输入均不能发布结果。

`services/pi-runner` 固定使用 `@earendil-works/pi-agent-core` / `pi-ai` 1.5.0。Python Worker 以最小环境启动 Node.js 24 子进程，输入与密钥经 stdin 传递；模型只能使用 `project_search`、`read_evidence`、`save_note`、`submit_suggestion`。无 shell、服务器文件或任意网络工具。请求仅发送到管理员配置的端点，拒绝重定向，SDK 自动重试为 0。材料中的指令不能增加工具或项目范围。

创建时冻结文件摘要、有效解析、片段摘要、材料状态版本及题录版本，最多 256 个片段。初始提示提供其中最多 5 个片段编号，模型可在作者所选版本内检索、读取；这不代表已完整审阅所有材料。每次模型和工具调用、等待回包时的心跳，以及最终发布均重查当前作者权限、规则、输入和模型配置。单任务每代次最多 4 次模型调用、8 次工具调用，总时长 90 秒，每次请求 30 秒、输出上限 2048 token。

Pi 与业务端分别校验工具参数；摘记和建议必须引用本次实际读取的片段。写工具仅暂存内存中的候选结果，全部成功后在项目锁内发布到 `Job.output`，状态固定为 `pending`。中途失败、超时、撤权、撤回/恢复材料或输入变化会丢弃全部暂存结果；不会创建作者笔记、改写稿件或采纳建议。调用记录独立保留，Worker 中断后租约回收会结束未完成的调用，错误记录不含供应商原文或密钥。

### Issue #8 实际验证

2026-11-05：后端完整测试 133 项通过；最后的 URL 配置校验和进程回收调整后，17 项 AI 联调重新通过。Pi SDK 的 5 项受控协议测试通过，覆盖工具白名单、参数拒绝、用量、服务端错误不重试及拒绝重定向。撤权、角色移除、规则变化、资料变化、取消、超时、租约回收和暂存后失败均不会发布结果。

Web 全量浏览器回归中 18 项通过，新增任务展示使用的测试主机名修正后，涉及的桌面/移动两项重新通过；实际查看了移动截图，待核对摘记可回查摘要原文，并能显示两次模型调用记录。类型检查、单元测试、Web 构建、迁移及遗漏检查、容器构建启动、五项依赖健康、真实 Worker 往返通过。构建曾遇到临时 DNS 故障，重试及宿主机网络构建后成功，未改变常规 CI 流程。

以上使用真实 Pi SDK 和本地受控 HTTP/SSE 服务验证执行框架；未配置真实生成模型，不能据此认定阅读或比较内容质量通过。上层业务效果继续由 #9/#19 验收。


## 阅读摘记与文献比较（Issue #9）

作者启用 `reading` 或 `comparison` 后，在“阅读摘记与比较”中选择已解析资料，提交单篇阅读或 2–5 个版本的比较。结果按研究对象、方法、结果、局限、条件和适用范围排列，可展开精确引文、回查原文位置。摘要、全文、研究材料及未知范围保持题录中的标记。阅读结果独立保存，不写入稿件或证据笔记。

- `POST projects/{id}/reading/tasks/`：`idempotency_key`、`policy_version`、`purpose`、`version_ids`，可选 `question`（最多 500 字）。权限、规则、来源与配置快照复用 Pi 任务；取消、重试和调用记录使用现有任务接口。
- `GET projects/{id}/reading/sources/`、`GET projects/{id}/reading/`：分页资料与结果；`GET reading/{record_id}/` 返回模型原始提取、最新作者修订及来源是否变化。
- `PATCH reading/{record_id}/`：提交 `version`、`edits`（资料版本、六类字段之一、作者文字）、`note`、`verified`。作者修改追加版本，模型原始结果不变；重复请求不重复追加，旧窗口返回 409。来源改变后禁止确认旧结果，未保存的界面草稿在冲突时保留。

阅读提示版本为 `reading-v2`；初始目录每份资料最多提供 12 个片段编号，仍可在冻结的资料范围内检索。每代次最多 4 次模型调用、32 次工具调用，总时长 180 秒，单篇阅读每次模型请求 60 秒、多篇比较 120 秒，输出上限 8192 token。批量读工具最多 64 个编号，累计返回原文最多 8000 字符；超出部分显式返回 unavailable，不能据此声称已读完整材料。模型只使用检索、读原文、提交阅读结果三个工具。

后端要求所选版本逐一对应、原文已读取且引文为精确子串，提取与比较说明中的阿拉伯数字必须来自其引文。未读完的“未提及”降为依据不足；摘要、未知范围、条件或跨资料依据不足的比较降为可比性不确定。相同结果重复提交只保存一份，冲突提交拒绝整个结果。未暂存时，引文或数值错误一次返回所有字段的位置反馈；逐字唯一匹配本篇已读片段时提示其编号供核对，允许模型在上述 4 次调用内修正；仍未通过则保留失败记录，不能发布部分结果。撤权和来源版本变更仍立即终止。阅读请求向供应商声明 `parallel_tool_calls: false`，但是否执行取决于供应商；Ollama 0.40.14 不解析该字段，不能据此保证单工具输出。返回的所有调用仍交业务端校验。数值与出处检查不等于语义正确，遗漏、错配或错误推断仍需作者核对。

### Issue #9 实际验证

2026-11-05：后端完整测试 150 项通过；随后补充重复提交、比较数值校验等调整，阅读模块 18 项重新通过。真实 Pi SDK 的受控服务测试覆盖来源拒绝、遗漏版本、摘要范围、读取预算、结构修正、作者版本冲突、撤权及暂存结果丢弃。真实生成模型的内容效果单独记录在 [测试说明](testing.md#阅读模型实测issue-9)，不能用协议样例替代内容验收。

最终容器环境下 22 项桌面/手机尺寸浏览器测试全部通过，覆盖阅读创建失败反馈、比较结果、原文回查、作者编辑与核对、旧窗口冲突和重新加载。已查看手机尺寸截图；比较表在自身区域横向滚动，没有撑宽页面。Ruff、类型检查、单元测试、生产构建、迁移遗漏检查、五项依赖健康及真实 Worker 往返通过。CI 继续只运行原有轻量检查，没有新增每次推送/合并的全服务联调。


## 作者原稿与版本对照（Issue #10）

项目内“作者原稿”支持研究问题、方法、结果说明，添加标题和正文块，调整标题层级、移动与删除块。章节树按标题层级定位。正文按纯文字保存，不处理 Word 富文本排版；作者编辑不依赖模型配置或 AI 开关。审阅者只能查看。

每次显式保存建立新稿件版本，正文块保持稳定 UUID，只有内容或标题层级变化的块产生新块版本。历史页可查看旧稿，对照研究说明、文字、层级和顺序的变化；恢复旧稿生成新稿件版本，旧版本和块身份不被覆盖。浏览器离开有未保存草稿的原稿时提示，接口返回冲突后仍保留当前草稿。

接口均在 `projects/{project_id}/manuscript/` 下：

- `GET` 返回当前版本，尚未保存时为 v0；`PUT` 接收 `version`、`request_key`、`research`（question/method/result）和有序 `blocks`（id/text/heading_level，0 为正文，1–9 为标题）。最多 500 块、正文共 20 万字符，单块 2 万字符，研究说明各 1 万字符。
- `history/` 分页列版本；`history/{number}/` 读取固定稿；`diff/?before={n}&after={m}` 返回增删、内容修改、层级和位置变化，v0 表示空稿。
- `POST restore/` 接收当前 `version`、`request_key`、`from_version`，恢复正文和研究说明，追加一个版本。
- `GET imports/` 分页列可导入 DOCX 的最新成功解析；`GET imports/{parse_id}/` 返回正文预览、来源 token、未支持内容提示。
- `POST imports/` 接收当前 `version`、`request_key`、`parse_id`、`token`、`mode`（append/replace）。作者确认后导入，保留研究说明。重复请求返回原操作结果；新请求基于旧版本返回 409，绝不覆盖新稿。

DOCX 原件先通过材料模块上传并解析。导入复用 #6 的固定解析结果，按原段落重组分片，不再解析一次文件。仅导入顶层文字段落及标题，表格、图片、公式、嵌套结构和排版不导入；预览和历史记录保留解析警告，不能当作无损 Word 导入。重新解析、来源撤回或预览之后状态变化时拒绝旧请求；超出原稿上限整次拒绝，不截断正文。追加相同解析造成块 ID 重复时拒绝，可改用替换或手工编辑。

### Issue #10 实际验证

后端全量 165 项通过；补充导入过期解析、空稿恢复和超范围版本号后，原稿模块 16 项重新通过。包括实际双线程并发保存、请求重放、旧版本冲突、跨项目块、数据库不可变/关系约束、项目级联删除，以及真实文件上传、Worker 解析和 DOCX 长段落重组。阅读数据未被复制为正式稿件。

浏览器全量回归的原有 22 项通过；新增原稿桌面/手机两项最初因测试按钮和下拉框标签定位失败，补齐返回列表草稿保护及下拉框可访问名称后，两项完整流程重新通过。已查看手机编辑与差异截图，页面未横向溢出。类型检查、单元测试、生产构建、Ruff、迁移遗漏检查、五项依赖健康与真实 Worker 往返通过；未增加常规推送/合并 CI 的重型检查。

## 原稿证据核验与论证诊断（Issue #11）

作者启用 `review` 后，先保存原稿，在“原稿诊断”选择正文块及已解析资料。每次检查 1–20 块、共不超过 6000 字符，依据可选 0–5 个资料版本；研究说明各字段仅提供前 1000 字符，截断时界面提示。没有资料时只检查原稿及作者研究说明，不提供材料检索或读取工具。未保存的编辑不进入任务。

问题卡固定原稿版本、块版本、精确引文和字符位置，分别展示文献依据、相关原稿和作者研究说明。可按类型、作者状态筛选，回查固定稿与原文；忽略必须填原因。作者确认只是自己的判断，不替代学术核验，也不会修改正文。原稿或资料变化后禁止确认旧卡，按当前稿复查创建新任务与新记录，保留前次问题及作者决定。

接口均位于 `projects/{project_id}/`：

- `POST reviews/tasks/`：`idempotency_key`、`policy_version`、`manuscript_version`、`block_ids`、`version_ids`，可选 `question` 和 `previous_review_id`。同键同输入返回原任务，冲突返回 409；任务取消、重试、调用记录复用现有接口。
- `GET reviews/`、`reviews/{id}/`：分页历史、固定范围、资料登记与全文范围、输入是否变化、复查任务关系。
- `GET reviews/{id}/findings/?status=&category=`：筛选问题；`GET/PATCH review-findings/{id}/`：读取问题或提交 `version`、`status`（pending/confirmed/ignored）、`reason`。只有作者可写，重复请求不追加同一决定，旧窗口冲突保留输入。

提示词版本 `review-v2`，沿用阅读任务的 4 次模型调用、32 次工具调用、180 秒总预算。读资料累计 8000 字符，初始目录每份最多 12 个片段；不能声称覆盖全部原件。模型必须先读取原稿；引文位置、所选范围、实际读过的资料及研究说明均由后端校验。尚未暂存时的引文、数值或重复问题错误可反馈给模型，在原预算内修正；越权、版本变化及撤权立即终止。未得到有效结果时保留任务和错误记录，不发布部分卡片。

`review-v2` 明确区分正文、其他正文、研究说明与资料引用；模拟材料按其内部陈述核对，局部摘述不必复述资料的全部细节。有资料时提示模型在首轮提出两个只读调用，Pi 依次执行，节省交互轮次；这不扩大读取范围。定位失败返回块内实际匹配次数，数值失败列出本卡引文尚未支持的数值。同一位置、相同依据的跨分类重复，以及交换两处正文位置后的重复矛盾，均要求模型合并后重提，不由后端静默删卡。普通文字未提交时最多补一次协议提示，仍受四次调用、原时限及撤权检查约束。`tool_choice=required` 只是兼容接口请求声明，本机 Ollama 0.40.14 不解析它，不能依赖它保证提交。

模型仅提交带定位的 `findings`；范围说明由实际保存的问题数量生成，避免总述声称发现问题却没有问题卡。旧 `review-v1` 排队任务因配置快照不匹配而取消，需重新创建。历史问题和作者决定保留；这些校验只保证结构、定位和已读引用，不保证模型识别了全部问题，也不能自动识别所有语义误报。完整复测与未达标项见 [诊断缺陷复测](testing.md#诊断缺陷复测issue-42)。

“项目内有原件”“已登记题录”“摘要/全文/未知范围”和“原文是否支持主张”分别展示。未连接外部出版目录，出版真实性明确标为未核验；题录登记、文件可读、精确引文均不能证明文献真实或解释正确。全文范围沿用作者登记，不由模型升级。模型实测及误报见 [测试说明](testing.md#诊断模型实测issue-11)。

### Issue #11 实际验证

后端全量 187 项通过；随后新增的非 BMP 字符、重复引文定位、相关原稿与无资料工具范围测试单独通过。真实 Pi SDK 受控服务覆盖结构/引文校验反馈、四次调用上限、作者判断幂等、版本冲突、来源变化、撤权丢弃、数据库跨项目及不可变约束。真实模型的错误率与任务失败单独记录，不作为这些协议测试通过的推论。

最终容器下 26 项桌面/手机尺寸浏览器测试全部通过，包含诊断、固定稿定位、摘要范围、原文回查、忽略原因、筛选、编辑后复查和前次决定保留。已查看手机尺寸截图，没有页面横向溢出。类型检查、单元测试、生产构建、Ruff、迁移遗漏检查、容器启动、五项依赖健康及真实 Worker 往返通过。常规 CI 维持原有轻量检查，没有新增每次推送/合并的全服务联调。

## 表达建议与双端作者决定（Issue #12）

作者在 Web 保存原稿并启用 `expression` 后，从“表达建议”选择原稿块及可选资料，生成局部建议。结果展示原句、建议、逐字差异、理由和可回查依据；模型输出保持不可变。小程序项目中的“表达建议”使用同一接口查看、筛选和处理待办，生成任务的入口在 Web。

作者可接受、编辑后查看差异再接受，或拒绝并记录原因。采纳前须核对原意、数值、条件与依据；服务器再次检查当前作者身份、规则、固定稿件及资料快照。拒绝不改稿；过期建议可拒绝，但不能覆盖新稿。请求超时后重试同一决定不会生成第二版，另一个窗口已处理的建议返回 409，界面保留尚未提交的编辑。

- `POST projects/{id}/expressions/tasks/`：`idempotency_key`、`policy_version`、`manuscript_version`、`block_ids`、`version_ids`，可选 `question`。复用固定稿件范围、资料读取和 Pi 预算；任务记录使用 `expression-v3`。
- `GET projects/{id}/suggestions/?state=`、`suggestions/{suggestion_id}/`：分页建议、差异、作者决定及输入是否变化。状态为 pending/accepted/edited/rejected，未传表示全部。
- `POST suggestions/{suggestion_id}/preview/`：提交作者编辑的 `text`，返回差异及内容变化提示，不修改稿件。
- `POST suggestions/{suggestion_id}/decision/`：`request_key`、`manuscript_version`、`policy_version`、`action`（accepted/edited/rejected）、`meaning_confirmed`，可选 `reason`；只有 edited 可提交 `text`。Web 与微信会话共用相同事务和权限逻辑。

采纳在项目锁与单一 PostgreSQL 事务中建立正文新版本、关联引用和作者决定。未改块继续复用旧版本，原句之外的文字不变；被改块保留原有仍有效的引用，并附加作者此次核对的建议依据。引用保存固定片段、题录修订及状态快照；尚未登记题录时保留空题录，不虚构文献信息。该关联不证明原文在语义上支持论断。之后作者普通编辑产生新块版本时，旧引用仍保留在历史块上，不自动认定支持新表述。

模型标为实质修改的建议不保存其扩写正文，只展示需作者处理的说明，不能走表达采纳。程序保守拦截数值、字母术语、常见运算/温度符号、否定、方向和结论强度变化，以及大幅扩写；编辑后的文字再次检查。这些规则无法完整判断语义，也可能拒绝合理改写，不能替代作者判断。涉及核心观点、数据或结果解释时，应由作者回到原稿编辑区处理。

`expression-v3` 的原稿读取只向模型提供所选正文及固定版本编号，研究登记、题录状态与文献正文均不作为待编辑文字。模型只提交 `suggestions`，范围说明由已保存的建议数量生成。新生成的表达建议若触发内容保护或引入不配对引号/括号，在发布前反馈修正；没有文字变化时要求显式移除此项再提交，不能由后端静默当成空结果。明确标为实质问题的条目仍只保留原句和待作者处理的说明。 范围保护同时检查“适用/外推”用语，不能把“不外推到某范围”改成“不适用于该范围”；生成和作者编辑采纳均会检查，旧 v1/v2 排队任务取消。这仍是保守的文字检查，不能证明其他语义等价。

同轮两个只读调用仍由 Pi 依次执行；普通文字未形成提交时最多补一次提示。错误修正仍在原四次调用、180 秒总预算内，权限、旧版本与材料变化立即终止；无法形成有效结果时不发布部分建议。旧 `expression-v1` 排队任务取消后须重新创建，历史建议及作者决定保留。内容保护不能完整识别语义变化，作者确认仍必需。复测中的漏改、偏义与协议失败见 [Issue #43 记录](testing.md#表达缺陷复测issue-43)。

### Issue #12 实际验证与待办

后端完整回归 207 项通过；最后补充常见运算符保护后，相关拒绝测试单独复测通过。表达模块覆盖真实 Pi SDK、微信 Bearer 与 Web 共用作者决定、双线程同请求只修改一次、编辑后接受、拒绝不改稿、撤权/规则/稿件/依据变化、事务失败回滚、既有引用复制、不可变及跨项目约束。一次全量运行曾因测试按随机 UUID 比较片段而失败，改为固定片段序号后完整回归通过。

最终容器下 28 项桌面/手机尺寸浏览器测试通过，已查看手机尺寸的采纳与差异截图；小程序 7 项模拟组件/会话测试通过，其中包含旧版本与请求键、冲突保留编辑、拒绝不传替换文字和撤权清除内容。类型检查、单元测试、生产构建、Ruff、迁移遗漏检查、依赖健康和真实 Worker 往返通过。常规 CI 保持轻量。

用户尚未打开或登录微信开发者工具，因此真实微信页面编译、登录与跨端采纳仍待验收，不用模拟组件或 Bearer 接口测试替代；Issue #12 不提前关闭。本机模型也尚未产出可用表达建议，具体记录见 [测试说明](testing.md#表达建议模型实测issue-12)。

## AI 使用记录与披露清单（Issue #13）

Web 的“AI 使用与披露”按项目整理系统内任务、执行器及提示版本、输入资料范围、固定稿件位置、输出和作者决定。调用次数按 `ModelCall` 记录的发起事件统计，包含失败、取消和重试，不能据此断定供应商已收到请求；未开始的排队任务不算调用，未知 token 用量保持未知。阅读记录、摘记、诊断和表达建议分别计数，只有接受或编辑后接受并产生稿件版本的表达决定计入实际采纳；阅读核对、诊断确认、拒绝和空输出不算采纳。资料索引单独列出，不混入生成模型调用；检索时的查询向量没有独立任务记录。

作者可逐项回查建议、决定、修改前后稿件及输入片段，按学校要求编辑使用说明，并填写系统外工具与版本、用途、范围/稿件位置、时间和采纳备注。参考草稿直接从业务记录生成，不调用模型，也不覆盖作者已有文字。系统只能记录明确保存的采纳，作者手工转抄和其他工具使用仍需自行补充；不计算原创比例，不提供原创证明或合规认证。

- `GET projects/{id}/usage/`、`usage/{job_id}/`：分页任务记录及固定输入片段，采用字段白名单，不返回端点配置、目录、密钥或原始提示输入。
- `GET disclosure/`：当前汇总、参考草稿、事实摘要 `facts_token`、最新保存版本及 `stale`。
- `POST disclosure/`：`version`、`request_key`、`facts_token`、`text`、`external_uses`、`verified`。外部使用每项包含 `tool`、`purpose`、`scope`、`used_at`、`note`；最多 50 项，全部标为作者自报。
- `GET disclosure/history/`、`disclosure/history/{number}/`：分页修改历史、单版作者内容及当时的固定事实快照。

清单是普通作者编辑，不要求启用 AI；审阅者只读。项目锁内重新检查权限、清单版本与事实摘要，再追加历史。相同请求键和内容重复提交不会再建版本；同键异内容、旧清单或旧事实返回 409。Web 保留草稿，刷新后对照最新版本，再明确更新保存基准。新任务、调用、决定、阅读修订、诊断决定或稿件版本会使旧清单过期；作者修改内容后也要重新核对。旧版本的“当时已核对”记录保留，不能当作当前有效确认。后续 #17 从固定快照接入导出。

### Issue #13 实际验证

2026-11-05 后端完整回归 219 项通过；随后补充“阅读核对、诊断确认不算采纳”，披露模块 13 项全部通过。覆盖真实 PostgreSQL 迁移和不可变历史、调用/输出/采纳计数、同一修改的原建议与前后版本、外部使用历史、旧事实/旧清单冲突、并发幂等、撤权、跨项目隔离、未知用量和敏感字段过滤。

浏览器全量运行先通过 29 项，随后进程收到 SIGTERM，最后一项没有结果；清理专用测试数据后单独补跑该手机检索用例通过。最后的清单编辑核对状态修正已重新构建 Web，并分别通过桌面及手机尺寸的披露流程：受控模型任务的调用/建议/采纳差异、原建议与修改前后版本回查、外部使用、历史、两类冲突保留草稿、内容变更取消核对、审阅者只读。30 个场景均有通过记录，但不把中断的全量命令描述为成功。已检查手机清单截图，无横向溢出。

`make check test build`、Ruff、迁移遗漏检查、容器启动、依赖健康及 Worker 往返通过。披露不新增模型调用；浏览器的受控供应商输出只验证使用记录链路，不作为模型内容质量证据。CI 配置保持不变，常规 PR 仅执行原有轻量检查。

## 导师反馈与修改待办（Issue #14）

作者在 Web 的“导师反馈与修改待办”录入意见及来源说明，可关联已保存证据片段和原稿正文块。意见与导师回复均明确标注作者转录，不代表导师本人登录提交。原始记录保留不变；需要更正时另录意见。作者可手动登记任务，也可启用 `feedback` 后用 Pi 拆分，逐项编辑、核对和接受候选，再加入待办。拒绝保留决定但不创建任务。

每次处理保存独立版本。完成须填写处理说明，并选择已修改原稿或无需改稿；前者须关联最新正文，不能把初始同一块版本登记为修改。界面分别回查初始稿、处理位置、原始意见与历史。正文变更或删除后，旧关联标记失效，必须核对并重新关联。导师回复固定在当次处理记录上，后续进度变化不会自动沿用回复；记录人仍是作者，未实现导师身份签批。

小程序从项目的“修改待办”进入，查看、筛选、更新作者进度及说明。Web 和微信 Bearer 使用相同 POST 接口及事务。刷新保留未保存说明和旧版本基准；发生冲突须对照新内容后明确采用新基准。候选、Web 处理草稿及小程序待办切换提供离开确认；小程序系统返回提示受平台能力限制，退出应用或手势返回不保证拦截，未提供跨会话草稿持久化。

- `GET/POST feedback/`、`GET feedback/{id}/`：原始意见列表、录入及回查。
- `POST feedback/{id}/split/`、`GET feedback/{id}/candidates/`：拆分任务及分页候选。
- `POST feedback-candidates/{id}/decision/`：作者确认或拒绝，提交规则版本、核对状态、请求键及可选固定稿件位置。
- `POST feedback/{id}/tasks/`：作者手动登记，不依赖 AI 开关。
- `GET feedback-tasks/?status=&feedback_id=`、`GET/POST feedback-tasks/{id}/`：分页、详情及处理新版本；POST 提交 `version`、`request_key`、标题、要求、进度、说明、结果类型与位置。
- `GET feedback-tasks/{id}/history/`、`POST feedback-tasks/{id}/mentor-reports/`：处理历史与指定处理版本的作者转录回复。

以上接口均位于 `projects/{id}/` 下。位置使用 `manuscript_version` 与 `block_id`，同时指定或同时为空。审阅者只读，撤权后清除页面内容。拆分执行器只开放 `read_feedback` 和 `submit_feedback`；最多四次模型调用、32 次工具调用、90 秒总预算与单次 30 秒请求预算。输入稿件、来源或规则变化即取消，失败不发布部分候选；引文须与原始意见逐字匹配。详情及限制见[测试记录](testing.md#导师反馈验收issue-14)。

`feedback-v2` 按可独立处理的要求分别提取，缺少具体图表编号或位置时保留可辨认的事项供作者补充，不因同段有越权文字而丢弃合法要求。仅有未来禁止性约束时不另建候选；明确要求纠正已有错误仍是任务。引文出现次序错误会返回对应原文与实际匹配次数，模型须在原调用预算内直接修正，不自动更改位置或发布部分候选。总述按已保存候选数量生成，不让模型宣称导师已确认；旧提示版本排队任务取消后须重新创建，历史候选和作者决定保留。系统五例复测符合预期，但直接提问对照仍漏合法任务，见 [Issue #44 记录](testing.md#反馈拆分缺陷复测issue-44)。

### Issue #14 实际验证与待办

后端完整回归 237 项通过；补齐反馈来源在披露中的文件/片段计数和原文回查后，反馈与披露模块 30 项通过。桌面与手机尺寸各 16 项浏览器测试通过，合计 32 项；已查看手机反馈处理与历史截图，无横向溢出。小程序 10 项模拟测试通过，其中反馈 3 项；类型检查、单元测试、生产构建、Ruff、迁移遗漏检查、依赖健康及 Worker 往返通过。

真实微信编译、登录与跨端操作尚未验收，不能以浏览器手机尺寸或 Bearer 接口测试替代。早期本机模型曾合并独立任务并漏拆；后续 #44 系统五例复测符合预期，直接对照仍有漏项，详见测试记录。CI 保持原有轻量 PR 检查，没有添加每次推送或合并的全服务测试。

## 依据关系与路径查询（Issue #15）

Web 的“依据关系”支持按正文块查依据、按材料查关联正文，也可组合筛选。路径显示固定稿件版本、主张原话、证据原话和材料版本，能回查对应正文与原始片段。历史稿件位置不会自动变成新稿位置；正文或来源发生相关变化后显示需复核。正文只保留相同块版本的移动不会错误失效，原稿引文和来源引文的出现次序分别以原文为准。

作者从已保存证据卡选择来源，在自己的原稿中引用具体主张，核对后登记支持、矛盾或背景关系；未启用 AI 也可操作。作者可追加核对决定或撤回关系，旧版本仍可回查。旧请求版本返回 409，界面保留草稿，刷新后须明确采用新基准。来源撤回时图中移除关联；恢复材料后需重新核对，不能沿用此前的确认。重新解析或改写正文后，应为最新来源或新稿登记新关系。

模型诊断中的资料关联标为候选；作者确认诊断问题，也不等于核对支持关系。表达采纳时保存的引用单独标注为引用，不声称支持整段文字。图只用于回查，不向模型增加权限，也不修改原稿。

- `GET/POST projects/{id}/evidence-links/`：分页作者关系及新登记。POST 包含请求键、稿件版本/正文块、主张与出现次序、来源片段、证据原话与出现次序、关系、说明、明确核对状态。
- `GET/POST evidence-links/{link_id}/`、`GET evidence-links/{link_id}/history/`：详情、带版本与请求键的新决定及分页历史，均在项目路径下。
- `GET graph/paths/?block_id=&material_id=&page=`：每页 20 条路径及同步状态；只有 synced 返回有效计数，其他状态的 count 为 null，不能据此显示“没有关联”。
- `POST graph/rebuild/`：当前业务 revision 与 request_key。项目作者可请求重建或恢复丢失投影，审阅者只读。请求重复不产生第二次重建事件。

Celery scheduler 每 15 秒消费最多 10 个项目的 outbox，业务请求不依赖 Redis 投递成功。普通同步失败保留事件并延后 30 秒重试；项目删除的独立图清理事件也可重试。错误只记录类型或预定义代码，不记录驱动异常正文、密钥或论文内容。图写事务超时 10 秒、查询事务 5 秒，连接与连接池等待各 3 秒。首版每项目投影最多 10000 条路径，超过上限保留失败状态，不静默截断；当前采用完整项目投影，尚未做大项目性能验收。

同步使用项目锚点属性写锁串行化，再校验版本并发布水位；原理参见 [Neo4j 并发访问文档](https://neo4j.com/docs/operations-manual/current/database-internals/concurrent-data-access/)。事件及正文以 PostgreSQL 为准，Neo4j 无原文副本；不要将 Neo4j 直接修改当作作者决定。此项不新增模型调用，也不把图路径作为来源真实性或支持关系的自动证明。

### Issue #15 实际验证

后端全量 252 项通过；补充恢复后图水位超前的重建场景后，图模块 16 项通过。最后的删除标记与路径筛选复核分别补跑相关场景通过。桌面、手机尺寸全量各 17 项浏览器测试通过，共 34 项；新增诊断记录回查后，两端的图流程再次通过，包含真实 Pi SDK 受控诊断输出、模型候选区分及固定诊断记录回查。受控输出只验证数据链路，不是新增模型质量评测。

已查看手机路径截图，文字与按钮可换行，无横向溢出。类型检查、单元测试、生产构建、Ruff、迁移遗漏检查、依赖健康与 Worker 往返通过。常规 CI 没有增加服务容器、数据库集成测试或重复推送检查。

## 材料变更与影响分析（Issue #16）

Web 的“材料变更与影响”可选择已上传的版本，登记补充、更正或撤回说明。上传新版本身不改变旧版；更正后旧版保留作历史对照，不能用于新的检索/模型任务或过期表达建议采纳；撤回版本也停止新解析。原件与历史清理由 #18 处理，此功能不执行物理删除。

生成影响清单后，先查看已登记的正文依赖、待处理表达建议和关联修改任务，逐项记录作者处理。存在其他有效来源时仍提示核对其支持范围，不自动判定原论述错误。修改稿件后“复查已登记依赖”创建新轮次，并列出保留、新增和不再登记的数量；历史处理不会自动移植到新一轮。冲突后保留填写内容，刷新并明确采用最新状态后才能再次确认。

模型补查复用项目“原稿诊断”权限与 Pi 执行器，提示词版本为 `impact-v2`：选择 1–20 个正文块、合计不超过 6000 字符；只发送尚未登记位置的正文、新旧材料各前 8 个片段、各最多 4000 字符及作者变更说明。已撤回材料不发送；更正旧版明确标为历史对照。`read_impact` / `submit_impact` 之外的工具禁止，输出校验正文编号、逐字引文和材料范围。最多 4 次模型调用、32 次工具调用；输入、权限或规则变化时取消。空候选可以成功，失败保留诊断状态；失败、取消和重试均可从任务记录回查。 `old/new` 依据必须提供对应侧的已读片段编号，`note` 依据只能引用变更说明且编号为空；错误反馈说明应修正的字段，不自动转换来源。仅有主题相似而未使用变更事实的位置不应列入候选。候选数量说明由服务端生成，不允许用模型总述替代条目。固定样例及限制见[测试记录](testing.md#影响分析缺陷复测issue-45)。

API（项目内）包括：

- `material-changes/`：查询/登记；`material-changes/<id>/runs/`：查询/生成影响清单。
- `impact-runs/<id>/`、`impact-runs/<id>/items/`：轮次与分页影响项；`impact-runs/<id>/model/`：模型补查及任务历史。
- `impact-items/<id>/`、`impact-items/<id>/history/`：处理、刷新与历史。写入均核对作者权限、请求键、版本和事实令牌。

自制模型验收可显式执行（只接受 DEBUG 环境和本机端点，不使用 `.env` 的模型密钥）：

```bash
PYTHONPATH=services/backend uv run python services/backend/core/tests/evaluate_impact.py \
  --model qwen3:4b-instruct --base-url http://127.0.0.1:11434/v1 \
  --output .local/impact-eval.json
```

实际结果及模型误报见[测试说明](testing.md#材料变更验收issue-16)。本功能的 Web 移动尺寸测试不等于真实微信或手机验收。

## 固定快照 Word 导出（Issue #17）

先保存原稿，在“AI 使用与披露”核实当前清单，再到“Word 导出”刷新资料、选择明确模板版本、填写交付标题与署名。预览列出固定正文、引用顺序、题录副本、披露及外部使用；作者核对后创建快照。已有未保存原稿或披露时不能创建。之后编辑原稿、修改题录或披露，不改变旧快照；预览与确认之间发生变化返回 409，需重新预览。

首版提供项目自行编写的中文论文示例规则，**不是院系官方模板**。模板仅是有界 JSON 排版规则，不接受宏或任意 Word 文件。管理员根据获准使用的要求整理规则，填写来源及使用权限说明后追加版本：

```bash
uv run python services/backend/manage.py register_export_template template.json \
  --user 管理员账号 --rights-confirmed
```

JSON 顶层字段是 `code`、`name`、`source_label`、`rights_note`、`layout`。可复制 `core/export_templates.py` 中的 `DEFAULT_LAYOUT` 字段并按要求调整页宽高、四边距、字体/字号、九级标题字号、行距、首行缩进、题注字号、页眉文字与目录层级。长度单位为 mm，字号为 pt；`header_text` 中 `{title}` 替换交付标题。相同内容重复登记返回已有版本，内容变化追加版本，旧记录不可改写；新版本不会自动替换已选版本或旧快照。暂不声称满足未提供的院系规范。

导出保留作者标题层级及正文文本，在文末按正文首次登记顺序列参考文献，同一来源文件版本只编一个编号；段内按引用登记时间、ID 排序。正文中的普通文字如手写 `[1]` 不会被识别为系统引用。依据图关系也不会自动变成引用。题录缺作者/年份会在预览警示，导出不补造缺失信息，也不宣称符合某项参考文献格式标准。资料更正、撤回或引用失效时须先核对来源。

可将已有单行正文块指定为图题或表题；保留原文标题，使用 Word SEQ 域分别顺序编号。标题内不预填“图 1”等编号。当前原稿与 DOCX 导入仍是文本，**不会恢复原文件中的图片、表格结构或复杂排版**。封面、目录、正文分节；正文有页眉和从 1 开始的页码。下载后在 Microsoft Word 中更新整个目录，再检查分页、图表题注、引用和字体；目录初始包含更新提示，服务端不计算 Word 页码。操作参照 [Microsoft 的目录更新说明](https://support.microsoft.com/en-au/word/update-a-table-of-contents)。

任务使用现有租约、取消及最多三次执行机制。每次执行写入独立 S3 路径，校验内容摘要后才发布；旧 Worker 不能覆盖重试文件。重试只读取原快照，导出器版本变化则要求重新预览。正文或题录修改不取消已确认导出，权限/规则变化或来源撤回会取消未完成任务；来源版本状态变化也会阻断旧文件下载。文件先登记存储路径，失败保留诊断及未发布文件记录，供 #18 清理。下载时重新检查项目权限、来源状态和文件摘要，再保存发出记录；该记录不证明客户端已保存文件。

项目内 API：`GET export-templates/`；`POST exports/preview/`；`GET/POST exports/`；`GET exports/{id}/`；`GET exports/{id}/download/`。确认包含预览令牌、稿件/披露/模板版本、标题、署名、题注位置、请求键与明确核对状态。列表分页，详情最多显示最近 100 次下载，完整记录保存在数据库。任务重试/取消复用 `jobs/{id}/{retry|cancel}/`。所有导出不调用生成模型。

## 永久删除与清理（Issue #18）

材料“撤回”停止后续使用并保留历史。需要删除在线副本时，在 Web“删除与清理”选择材料或整个项目，先保存/放弃其他未保存编辑，再预览记录数量和受影响正文，明确勾选后确认。项目作者可删除材料，只有项目创建者可删除整个项目。整项目删除包含所有稿件历史；单材料删除覆盖全部版本及已登记派生链，多来源结果可能整体删除，其他材料与未受影响当前正文保留。预览后范围发生变化会返回 409，必须重新核对。

确认成功后旧业务路径返回 404，界面重新加载当前项目；整项目删除返回项目列表。全局“我发起的清理”仍可查看进度与重试。`在线清理完成` 只表示清单中业务行、向量、文件和图步骤成功或共享保留；任何步骤失败都显示清理未完成。详细步骤显示前 100 项并提供全量状态计数，执行历史显示最近 100 次，完整清单和历史仍存数据库。错误仅记录异常类型/预定义代码，不记录驱动响应或内容。

- `POST projects/{id}/cleanup-preview/`：`scope` 为 material/project，`material_id` 为材料 UUID 或 null；返回预览令牌、数量、当前受影响正文和稿件版本。
- `POST projects/{id}/cleanup/`：同一选择加 `preview_token`、`request_key`、`confirmed: true`。同发起者同键同内容返回原记录，项目已删除也可重放；同键不同内容返回 409。
- `GET cleanups/`、`GET cleanups/{id}/`：发起者自己的分页记录/详情，不再依赖已删除项目的成员关系；禁用账号不能访问。
- `POST cleanups/{id}/`：携带当前 `generation`，继续失败项；旧代次返回 409。已成功步骤不会重复执行。

数据库部分在确认事务中执行，文件与图由 Worker 处理；scheduler 每 15 秒补投未派发请求，并将过期执行记录为失败。首版单次最多 50000 条业务记录，超限拒绝确认，不部分删除；尚未进行大规模删除性能验收。不要绕过 API 直接删除项目或文件记录，否则可能遗漏对象清单。

删除无法撤回已下载文件、手工转抄或已发送给模型服务的内容；已开始发出的下载也不能追回。当前没有自动备份过期或第三方内容删除承诺。备份由部署维护者按实际保留策略管理；恢复时先保持服务离线，保留备份时间之后的删除账本，重新执行这些删除及图重建，再开放访问。不要仅恢复旧 PostgreSQL/对象备份便宣称删除仍有效。恢复操作与实际演练由 #20 补充，未演练不算通过。

## 固定模型对照评测（Issue #19，验收进行中）

`evaluation_cases.py` 将已有分模块自制样例统一为 14 个案例，包含阅读/比较、诊断、表达、反馈拆分和材料更正。它们是虚构软件验收资料，不是真实研究论文；预期标注由实现者/AI 起草，尚待人工核对。运行器固定代码摘要、样例内容、模型文件摘要和服务版本，保存两组原始结果、用量和时间。只在 DEBUG 环境使用本机已下载模型，不读取应用的模型密钥。

```bash
PYTHONPATH=services/backend uv run python services/backend/core/tests/evaluate_core.py \
  --model qwen3:4b-instruct --base-url http://127.0.0.1:11434/v1 \
  --output-dir .local/core-evaluation-v1
```

目标目录必须是新目录。系统组使用真实 Pi 执行器和业务 API，通过同步派发完成专用任务；直接组使用同一模型的单次请求，协议参见 [Ollama 官方兼容接口说明](https://docs.ollama.com/api/openai-compatibility)。系统最多四次调用，直接组一次；两组每次输出上限相同，但工具读取、校验和返回结构不同。固定先运行系统组再运行直接组，没有平衡模型冷启动和缓存，不能据此推断普遍效率提升。格式不合格时保留原始文本与失败状态，不把空结果当作正确判断。

对支持该字段的服务，可加 `--reasoning-effort none`（或 `low/medium/high`）；不传时两组都省略字段，不继承应用的推理模式。系统子进程与直接提问使用同一显式设置，每份结果记录模式，配置改变不能混入同一轮。该参数只用于本机自制评测，不修改 `.env`。

`run.json` 保存整轮结果，`system-*.json` 保存分模块原始记录，`review-template.json` 是待填写复核表。中断后可加 `--resume` 续写已确认完整的分组与尚未发出的直接请求；代码、模型、推理模式或样例变化时拒绝续写。部分执行的系统分组需先检查保留的日志，不自动重跑掩盖原失败。专用项目使用永久清理流程移除文件及派生数据，失败时保留清理账本。

复核者应先检查样例预期，再逐项填写 `correct/incorrect/partial/neutral`、对应预期 ID 与理由，并核对阴性条件。正确项只匹配一个预期；重复正确输出计为误报，部分正确单列且不消耗预期，失败任务的内部草稿不算交付。`assistant_draft` 与 `human` 分开报告；前者不能填写人类核验用时或操作量。未测值保留 null，不能用推测数字补齐。完成复核后：

```bash
PYTHONPATH=services/backend uv run python services/backend/core/tests/evaluate_core.py \
  --output-dir .local/core-evaluation-v1 --review .local/review.json
```

结果写入 `scores.json`。整轮未结束、配置变更、复核遗漏或结果摘要不匹配时拒绝评分。此评测与常规 CI 分开，不增加每次推送的模型调用。软件集成测试、真实模型输出、人工复核和微信/Word 外部验收分别记录；尚未验证的部分不能因脚本执行成功而打勾。

运行结束还会生成离线 `review.html`。用浏览器打开，先核对资料与预期，再填写每项判断、对应预期及理由，主动开始/暂停计时，最后导出复核 JSON。页面隐藏、切换计时项或导出会停止计时；未计时保留未知。操作量只统计判断字段修改次数，不代表完成整个论文任务的总操作量。草稿按本轮摘要保存在浏览器本机，清除浏览器数据会丢失；请导出保存。不认可预期时不要勾选确认，也不要将 AI 草案改名为人工标注。

公开自制运行记录见 [2026-11-06 评测结果](evaluation/2026-11-06/run.json)，逐项 AI 草案及计数与原始试跑同目录保存，人工复核仍待进行。无需模型服务即可复算草案：

```bash
PYTHONPATH=services/backend uv run python -c 'import json; from pathlib import Path; from core.tests.evaluation_metrics import score; p=Path("docs/evaluation/2026-11-06"); assert score(json.loads((p/"run.json").read_text()), json.loads((p/"assistant-review.json").read_text())) == json.loads((p/"assistant-scores.json").read_text())'
```

需要从公开记录重建空白复核页面时，调用 `evaluation_review.render(run)` 并将 HTML 写到 `.local/`；它从原始运行生成待定表，不预填 AI 判断。具体结果、口径及缺陷链接见[测试记录](testing.md#核心流程与固定模型对照issue-19)。
