# 开发说明

本工程提供 [Issue #1](https://github.com/jiuwen567/ai-paper-assistant/issues/1) 的基础设施，以及 [Issue #2](https://github.com/jiuwen567/ai-paper-assistant/issues/2) 的账号、项目和权限实现。Issue #3 提供持久后台任务与字数统计样例；Issue #5 提供材料上传与版本管理；Issue #6 提供后台解析和 Web 原文定位；稿件与模型任务由后续任务接入。

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

配置由 `config/settings.py` 从仓库根目录加载；进程环境变量优先。不要在小程序、`VITE_*` 或客户端代码中放 AppSecret、数据库密码、模型密钥。尚未接入的微信或 Pi 能力不要求填入真实凭据。

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

登录后可创建项目，保存论文类型、写作要求与模板选择。首版模板标识为 `department-default`（院系模板），这里只登记选择，模板文件、版本与 Word 导出由 #17 提供。

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
