# 部署、恢复与升级

这份 Compose 用于单机开发和课程演示，Web 仍是 Vite 开发服务，所有宿主端口只监听 `127.0.0.1`。以下命令在仓库根目录执行，使用独立的演示项目和数据卷；不直接用于公开生产发布。功能入口见[使用流程](workflows.md)，实际验证及未通过项见[测试记录](testing.md)。

## 独立环境

准备 Python 3.12、uv、Node 24、pnpm、Docker Engine / Desktop 和 Compose v2，按锁文件安装。先执行 `make install`，再为演示生成独立配置：

```bash
python3 scripts/init_dev.py --directory .local/demo-source --port-offset 20000
export COMPOSE_PROJECT_NAME=paper-demo-source
export PAPER_ENV_FILE="$PWD/.local/demo-source/.env"
export PAPER_STATE_DIR="$PWD/.local/demo-source/.local"
dc() { docker compose --env-file "$PAPER_ENV_FILE" --profile app "$@"; }
dc config --quiet
dc up -d --build --wait
dc exec -T api python manage.py check_services
dc exec -T api python manage.py check_worker
```

此例 Web 为 `http://localhost:25173`、API 为 `http://localhost:28000`，数据库、图、对象存储和队列端口也整体偏移 20000。初始化同时更新客户端地址和 CSRF 来源；重复执行不覆盖已有 `.env`，也不会重新套用端口偏移。改端口时需要同时调整对应地址和 CSRF 来源。

三个隔离设置都要保留：`COMPOSE_PROJECT_NAME` 隔离网络/卷，`PAPER_ENV_FILE` 选择应用凭据，`PAPER_STATE_DIR` 选择 SeaweedFS 凭据文件。只改 Compose 项目名不会自动更换配置。默认不传这些变量时仍使用原有 `.env` 和 `.local`。`PAPER_EMBEDDING_CACHE` 可指定只读的公开模型缓存，默认是仓库 `.local/embeddings`；首次索引前按开发说明准备模型，不共享用户资料目录。

管理员维护配置文件，通过 `dc exec api python manage.py shell` 按[账号说明](development.md#账号与项目)创建普通账号，密码使用隐藏输入；当前没有自助注册或密码找回。迁移不创建演示账号。`migrate` 容器成功退出后才启动 API、Worker 和 scheduler。查看 `dc ps` 与 `dc logs --tail=80 服务名` 定位失败，日志可能含运行资料，不公开上传。`check_services` 检查迁移和实际依赖，`check_worker` 验证任务投递/执行/结果往返；仅 API 存活不能代表可用。

生成模型和微信凭据只填写在选中的服务端 `.env`，不放入客户端。新配置默认不启用外部生成模型或微信账号；需要联调时按[开发说明](development.md#微信小程序与公众号)填写该环境自己的配置。启动成功不等于模型内容质量或微信真机验收通过。

## 配对备份

PostgreSQL 保存业务事实和向量；SeaweedFS 卷同时包含原件、导出、Filer 元数据和 Volume 数据。必须配对保存。Neo4j 是可重建投影，Redis 队列不是事实源，不用它们替代业务备份。

以下是停写演示备份。先停止所有写入来源，包括本机开发进程、直接数据库脚本和其他客户端；单独停止 API 不足以停止 Worker。任何命令失败都应停止后续步骤，保留日志与当前状态。

```bash
umask 077
export PAPER_BACKUP_DIR="$PWD/.local/demo-backup"
mkdir "$PAPER_BACKUP_DIR"
dc stop -t 90 web api scheduler worker
dc exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl' > "$PAPER_BACKUP_DIR/postgres.dump"
dc stop seaweedfs
dc images -q postgres > "$PAPER_BACKUP_DIR/postgres-image.txt"
dc images -q seaweedfs > "$PAPER_BACKUP_DIR/seaweedfs-image.txt"
git rev-parse HEAD > "$PAPER_BACKUP_DIR/commit.txt"
docker run --rm --network none \
  --mount "type=volume,src=${COMPOSE_PROJECT_NAME}_seaweedfs_data,dst=/data,readonly" \
  --entrypoint tar "$(cat "$PAPER_BACKUP_DIR/postgres-image.txt")" \
  -czf - -C /data . > "$PAPER_BACKUP_DIR/seaweedfs.tgz"
(cd "$PAPER_BACKUP_DIR" && sha256sum postgres.dump seaweedfs.tgz > SHA256SUMS)
dc up -d --wait
```

目录必须是新目录。使用已下载的 PostgreSQL 镜像作为 tar 工具，没有启动第二个数据库；归档时 SeaweedFS 已停止。`pg_dump -Fc` 可由 `pg_restore` 恢复，但只覆盖这个数据库，不包括外部账号系统或整个集群角色。[PostgreSQL 17 备份说明](https://www.postgresql.org/docs/17/app-pgdump.html)、[Docker 卷备份说明](https://docs.docker.com/engine/storage/volumes/#back-up-restore-or-migrate-data-volumes)。

备份包含研究资料和账号数据，留在受控存储，另行备份所需密钥与配置，不进入 Git。只记录代码提交还不够：保留镜像 ID、锁文件、迁移版本及恢复所需配置。定期实际恢复；仅生成压缩包不能证明备份可用。此示例不提供自动轮换、异地副本、加密托管、时间点恢复或灾备时限承诺。

## 恢复到全新卷

先准备与备份相同的代码及 PostgreSQL / SeaweedFS 镜像，不在现有环境覆盖恢复。旧环境停写期间另行保存最新删除账本；备份之后的撤权、删除和保密规则变化也要核对。只有备份而缺少这些后续决定时，不得直接开放旧数据。

```bash
python3 scripts/init_dev.py --directory .local/demo-restore --port-offset 30000
export COMPOSE_PROJECT_NAME=paper-demo-restore
export PAPER_ENV_FILE="$PWD/.local/demo-restore/.env"
export PAPER_STATE_DIR="$PWD/.local/demo-restore/.local"
test -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")"
(cd "$PAPER_BACKUP_DIR" && sha256sum -c SHA256SUMS)
dc up -d --wait postgres neo4j redis
dc create seaweedfs
test "$(dc images -q postgres)" = "$(cat "$PAPER_BACKUP_DIR/postgres-image.txt")"
test "$(dc images -q seaweedfs)" = "$(cat "$PAPER_BACKUP_DIR/seaweedfs-image.txt")"
dc exec -T postgres sh -c 'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl --exit-on-error --single-transaction' < "$PAPER_BACKUP_DIR/postgres.dump"
docker run --rm -i --network none \
  --mount "type=volume,src=${COMPOSE_PROJECT_NAME}_seaweedfs_data,dst=/data" \
  --entrypoint tar "$(cat "$PAPER_BACKUP_DIR/postgres-image.txt")" \
  -xzf - -C /data < "$PAPER_BACKUP_DIR/seaweedfs.tgz"
dc up -d --wait seaweedfs
```

这里仍未启动 API、Worker、scheduler 和 Web。只恢复可信来源的配对备份；`pg_restore --exit-on-error --single-transaction` 出错时回滚本次数据库导入，不能忽略错误继续上线。[PostgreSQL 17 恢复说明](https://www.postgresql.org/docs/17/app-pgrestore.html)。新环境的数据库与 S3 凭据可由初始化生成，Django 签名密钥改变后旧签名/会话不能假定仍有效，需要重新登录与确认。

恢复后的检查顺序：

1. 核对数据库迁移、行数和选定原件/导出 SHA-256；确认没有混用另一次对象备份。
2. 在限制访问的维护环境按最新决定重放删除与撤权。使用既有清理流程，保留清理清单和失败状态；不能只删数据库行，不能把备份后已删除的内容重新提供下载。
3. 从 PostgreSQL 重建 Neo4j。新图卷没有原来的投影，即使数据库事件已标记完成，也要对项目加新同步事件再执行；不能看到空图就宣布恢复成功。
4. 检查所有清理是否完成，再恢复 API/Worker/scheduler。队列重新依据 PostgreSQL 待办派发；过期运行任务按租约转为失败，由作者决定重试，不恢复旧 Redis 队列作为业务事实。
5. 检查依赖、Worker 往返、登录、授权下载、原文定位和固定快照导出，最后才开放入口。

当前仓库没有通用的生产删除账本导入或权限变更合并工具。维护者必须保留完整历史并按实际账号/资料核对；未具备这项能力时，只能进行下面的专用自制数据演练，不能把它描述为任意生产恢复已验收。

## 可复现的自制恢复演练

`deployment_fixture.py` 仅在 DEBUG 环境操作它登记的随机 `deployment-eval-` 项目，使用两份自制文本、正文、引用、依据关系和一个 Word 文件。使用真实数据库与文件存储，引用通过测试夹具登记、API 调用使用测试客户端，后台任务同步执行；不调用生成模型，也不代替真实微信、浏览器登录或 Word 打开验收。

在源环境备份之前登记数据：

```bash
PYTHONPATH=services/backend uv run python services/backend/core/tests/deployment_fixture.py seed \
  --env-file .local/demo-source/.env --state .local/demo-state.json
```

完成配对备份后，在源环境删除第一份材料，保存删除记录并核对无关内容保留：

```bash
PYTHONPATH=services/backend uv run python services/backend/core/tests/deployment_fixture.py delete \
  --env-file .local/demo-source/.env --state .local/demo-state.json --deletion-ledger .local/demo-deletions.json
PYTHONPATH=services/backend uv run python services/backend/core/tests/deployment_fixture.py check-deleted \
  --env-file .local/demo-source/.env --state .local/demo-state.json
```

把旧备份恢复到新卷，在 API/Worker 尚未开放时依次执行：

```bash
PYTHONPATH=services/backend uv run python services/backend/core/tests/deployment_fixture.py check \
  --env-file .local/demo-restore/.env --state .local/demo-state.json
PYTHONPATH=services/backend uv run python services/backend/core/tests/deployment_fixture.py replay-deletion \
  --env-file .local/demo-restore/.env --state .local/demo-state.json --deletion-ledger .local/demo-deletions.json
PYTHONPATH=services/backend uv run python services/backend/core/tests/deployment_fixture.py check-deleted \
  --env-file .local/demo-restore/.env --state .local/demo-state.json
```

第一步核对原件/Word 摘要、正文与引用，并从业务事实重建图；之后按专用记录重放删除，确认旧原件、派生正文和导出不可用，无关材料与正文保留。重复调用不绕过失败清单。这仅重放指定样例的一次材料删除，不是通用账本导入；`demo-state.json` 和删除记录都保留在本机。

演练核对通过后，执行 `dc up -d --build --wait`、`check_services` 和 `check_worker`；此目标 Web 为 `http://localhost:35173`。恢复失败时保留环境和日志，不对原环境执行清库或 `down -v`。确定要丢弃时，先核对 `COMPOSE_PROJECT_NAME` 及卷标签，再仅删除专用演练卷。

## 升级与回退

升级前记录当前提交、镜像 ID、锁文件和迁移状态，完成配对备份及恢复检查；先在独立环境验证，再安排停写窗口。新镜像启动前运行迁移；失败时保持入口关闭，不跳过迁移直接启动旧代码。新代码健康检查和关键流程通过后再开放，观察失败任务与清理记录。

只有数据库模式兼容时才允许直接切回旧应用镜像。本项目没有承诺所有迁移可逆；涉及删除、不可逆数据转换或结构不兼容时，在新的隔离卷恢复升级前的完整备份，并核对停写之后的业务决定。不能只回退 Git 或只恢复 PostgreSQL，否则可能产生文件、版本和权限不一致。回退损失哪些新操作须先明确，正式数据操作由部署维护者授权。

## 公开部署和账号条件

公开服务需要另行配置 HTTPS、域名与可信代理、静态资源服务、`DEBUG=false`、允许的 Host / CSRF 来源、安全 Cookie、访问控制、备份保留及日志权限，并收紧数据库/对象存储管理凭据。本 Compose 的 Vite、调试设置和本地存储账号不构成生产配置。

真机不能访问电脑的 `127.0.0.1`。小程序需要实际 AppID、已登录开发者工具、手机可达的 HTTPS API 和合法域名；公众号菜单还需要实际账号具备对应权限并关联小程序。创建 Web 账号不会自动绑定微信，必须按一次性绑定流程由已登录作者确认。未完成账号、域名和审核条件时不发布服务、不声称真机或公众号入口通过。
