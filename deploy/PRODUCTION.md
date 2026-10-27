# 正式部署配置与验收

生产配置从 [production.env.example](production.env.example) 开始，开发 `.env` 不用于公网。填入本站域名、已验证的邮件发件地址和服务凭据；`RPG_MASTER_KEY` 与 `EMAIL_CODE_SECRET` 分别生成、跨进程共享并保持稳定。主密钥与数据库备份分开保管。首次管理员注册后可以清空 `RPG_SETUP_TOKEN`。

从 v105 或更早版本升级时，先暂停注册并替换全部旧 Web worker，避免新旧注册逻辑混用。迁移 v106 后，升级前尚未确认的注册需要重新提交；已注册账号与会话不受这一注册资料迁移影响。

## 裸机

按 [bare-metal/README.md](bare-metal/README.md) 部署。Web 使用 server/auth=1，迁移 CLI 用显式 `DATABASE_URL` 直连 PostgreSQL，运行时可用 PgBouncer。`RPG_SKIP_AUTO_MIGRATE=1` 时应先执行 `platform_app.migrate full`（新库）或 `up`（已有库），然后再启动 Web。Postproc 使用专用 `.env.postproc` 和直连 DSN；systemd 的 `EnvironmentFile` 会覆盖 `Environment`，不能依赖书写顺序覆盖数据库地址。

nginx 的 `/play` 和子路径回退到 `Player.html`，根路径是游客大厅，创作端路径回退 `Platform.html`。反代应覆盖客户端提供的 XFF 并只将实际代理地址/网段加入 `RPG_TRUSTED_PROXIES`。关闭 API/SSE 缓冲。

## Compose

```sh
cp deploy/production.env.example deploy/.env
# 编辑 deploy/.env：数据库/Redis口令、两个共享密钥、域名、邮件服务
# POSTGRES_PASSWORD 使用 openssl rand -hex 32，仅包含字母数字。
docker compose --env-file deploy/.env -f deploy/docker-compose.yml config --quiet
docker compose --env-file deploy/.env -f deploy/docker-compose.yml build backend pgbouncer
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d
```

`migrate` 服务直连 PostgreSQL，并在成功后放行 Web、postproc、cron。Web/cron 跳过自动迁移；postproc 的 LISTEN/NOTIFY 使用直连连接。Web、worker 与 cron 共用 `player_files:/app/data`。非 HTTP 服务禁用继承的 Web 探针，使用任务日志和队列积压监控。测试服 Compose 使用独立项目/主机，避免与正式服务的固定容器名、端口冲突。

连接池镜像由 `deploy/pgbouncer` 构建，启动时在容器内生成仅进程用户可读的认证文件，
不需要把数据库口令写入仓库。数据库口令必须至少 32 位且仅包含字母数字；按上面的
`openssl rand -hex 32` 生成即可。生产升级前应在目标网络验证连接池认证和事务模式。

本机可先执行隔离容器冒烟：分别构建应用镜像为 `ai-storygame:creator-readiness-local`、
连接池镜像为 `ai-storygame:pgbouncer-readiness-local`，然后运行
`python rpg/scripts/check_production_https.py`。该检查使用临时 PostgreSQL、PgBouncer、
nginx 和自签证书，覆盖旧版数据库迁移、授权、连接池事务锁及备份恢复；它不替代目标服务器验收。

Compose 后端只绑定本机 7860；使用 HTTPS 反代公开服务。生产不运行或暴露 Vite/Vitest 开发服务。

## Kubernetes

模板需要已有 `postgres-svc`、`redis-svc`、PgBouncer 及私密配置。替换 configmap/secret 中所有示例值；先准备 [storage.yaml](k8s/storage.yaml) 中的 **ReadWriteMany** PVC，并选择支持共享文件的 StorageClass。Web 与 worker 使用同一个卷，不可给每副本分配不同磁盘。容器 UID/GID 固定为 10001，Pod 配置 fsGroup=10001；NFS root-squash 等存储仍须预置该组写权限。

先应用配置与 PVC，再提交 [migrate-job.yaml](k8s/migrate-job.yaml) 迁移 Job，等待 `rpg-migrate` 完成后部署 Web/worker。每次升级重新创建迁移 Job，使用本次构建的固定镜像标签；Web/worker/迁移必须用同一版本。模板未代替真实集群、存储和密钥服务的部署验收。

[workers.yaml](k8s/workers.yaml) 包含 postproc 和每日数据保留 CronJob，按集群时区运行；上线前明确调整 schedule，并观察实际执行日志。

## 运行语义

- `/livez` 只表示进程存活；`/readyz` 和 `/api/health` 检查数据库，不泄露连接异常内容。探针不需要登录凭据。
- `RPG_RATE_LIMIT_PER_MIN` 限制每个真实客户端 IP 的 API 请求数。Redis 正常时跨 worker 共享；Redis 故障时降为有界的进程内保护，需监控 Redis。上传体积使用单独上限，其他写请求使用普通 body 上限。`RPG_REQUEST_TIMEOUT_SECS` 限制读取请求体和响应头等待；SSE 已开始后继续使用生成租约、停止及恢复机制。
- 后台安全设置控制登录失败次数/窗口/锁定、密码规则、会话期限和 IP 网段黑名单。缩短期限会拒绝超龄会话；延长期限不延长旧会话已签发的 expires_at。API 通用请求限额由上面的部署参数控制。
- 未使用且过期超过一小时的报价按批清理；已被请求/结算引用的报价保留。历史每页默认 20 回合、最多 50 回合；正文、状态差异与费用按页处理，祖先 ID 的校验仍随分支长度增长。
- 删除申请立即撤销登录态、PAT 和待授权设备。30 天内只能用已验证邮箱的单次恢复码撤销，封禁与到期账户不能恢复。硬删除同时删除个人积分账本、请求、报价及调用记录；本版本没有接入现金交易。持有共享故事或服务凭据的账户必须先转交所有权；旧的阻塞删除队列会记录失败，且不会中断其他账户删除。

## 上线前必须在预发布环境验证

用两个普通账户和一个管理员验证游客只读、存档/账单归属、停用与退出后旧凭据失效。验证真实域名上的注册、验证码重发、登录码与密码重置邮件；检查邮件链接域名与 HTTPS Cookie。若启用 Apple 登录，完成真实供应商认证验收。

在 1440、1024、390、360px 两套主题中检查布局、焦点和触控；走通完整生成、停止、断线重连与部分保存结算。观察 postproc 的真实消费者及任务积压，按预计并发压测。

备份 PostgreSQL、`RPG_DATA_ROOT` 文件及解密密钥，并在隔离环境演练恢复。恢复时保持两个共享密钥稳定；不要用重新生成密钥来“修复”旧密文或验证码。
