# 2 GiB ECS 部署

此配置使用单个 Web worker、直连 PostgreSQL 和有上限的连接池，适合低并发实例。
镜像必须在本地或 CI 构建并传入服务器；此 Compose 文件没有 build 配置。
数据库和 Redis 不映射主机端口，Web 仅监听主机回环地址。

在独立目录（例如 `/opt/ai-storygame`）放置 `compose.yaml`、私密 `.env` 和
UID/GID 10001 可写的 `data/`。`.env` 必须包括：

- `APP_IMAGE`：本次固定版本镜像标签。
- `POSTGRES_PASSWORD`、`REDIS_PASSWORD`：独立强口令。
- `DATABASE_URL=postgresql://rpg:<password>@postgres:5432/rpg`。
- `REDIS_URL=redis://:<password>@redis:6379/0`。
- `RPG_DEPLOYMENT_MODE=server`、`RPG_REQUIRE_AUTH=1`、`RPG_ENV=prod`。
- `RPG_MASTER_KEY`、`EMAIL_CODE_SECRET`：稳定、独立保管的共享密钥。
- `RPG_SKIP_AUTO_MIGRATE=1`、`RPG_DATA_ROOT=/app/data`。
- `RPG_DB_POOL_MIN=1`、`RPG_DB_POOL_MAX=6`、`RPG_POSTPROC_MODE=async`。
- `PUBLIC_BASE_URL`、`RPG_CORS_ORIGINS`：按实际访问入口配置。
- `RPG_COOKIE_SECURE=1`：公开 HTTPS 时必须启用。

创作包和旧剧本包的解压上限在此配置中默认均为 32 MiB，以适应 512 MiB
后端内存；上传请求体默认上限为 16 MiB。需要更大的包时，应先按实际内存和并发验证，再分别设置
`RPG_UPLOAD_BODY_LIMIT_BYTES`、
`RPG_AUTHORING_MAX_EXPANDED_BYTES` 与 `RPG_SCRIPT_PACK_MAX_EXPANDED_BYTES`。
应用层的绝对上限为 500 MiB。创作包的 JSON 成员、JSONL 单行及结构节点
默认分别限制为 4 MiB、4 MiB 和 500,000；调整时应一并考虑解析后的内存占用。

首次启动，先启动基础服务并直连迁移，再导入剧本数据，最后启动运行时：

```sh
docker compose config --quiet
docker compose up -d --no-build postgres redis
docker compose run --rm --no-deps migrate
# 在此恢复经核验的数据；不要把已有数据库当成首次部署重新导入。
docker compose up -d --no-build --no-deps backend postproc cron
curl --fail http://127.0.0.1:7860/readyz
docker compose ps
docker stats --no-stream
```

运行时更新先备份数据库、`data/` 和私密配置（密钥单独保存），加载本地构建的
新镜像，更新 `APP_IMAGE`，直连执行 `platform_app.migrate up`，再用
`up -d --no-build --no-deps backend postproc cron` 替换运行时。
迁移失败时不要启动新运行时；数据库已有 schema 变更时，代码回退前先核对兼容性。

没有域名时仅通过 SSH 隧道访问，可临时将 CORS 配为
`http://localhost:17860,http://127.0.0.1:17860`、Cookie Secure 设为 `0`，
注册设为关闭。`PUBLIC_BASE_URL` 暂用 `https://localhost`，不发送邮件。
接入域名后设置真实 HTTPS 源地址、邮件配置及 Cookie Secure，添加 HTTPS 反代，
再验证注册邮件和实际生成，才开放注册。不要启用旧项目的隧道配置。

```powershell
ssh -i "$env:USERPROFILE\.ssh\your-deploy-key" -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -N -L 17860:127.0.0.1:7860 root@YOUR_SERVER
```

隧道运行时打开 `http://localhost:17860/play`。初始管理员口令单独交付，
不写入仓库。迁移后的章节数、人物与知识数据、素材校验和、登录隔离、HTTP
响应及资源余量都应核验；容器 Up 不代表验收完成。

## 公网 IP 的 HTTPS 入口

`compose.ip.yaml` 使用 Caddy 和 Let's Encrypt 的 `shortlived` 证书为公网 IPv4
提供 HTTPS，无需域名。云安全组必须允许入站 TCP 80（证书验证）和 443（访问）。
加载固定版本的 Caddy 镜像，将 `Caddyfile` 放在部署目录，在私密 `.env` 设置
`PUBLIC_IP` 和 `CADDY_IMAGE`（使用镜像摘要固定版本）。同时设置：

```dotenv
PUBLIC_BASE_URL=https://YOUR_PUBLIC_IP
RPG_CORS_ORIGINS=https://YOUR_PUBLIC_IP
RPG_COOKIE_SECURE=1
RPG_TRUSTED_PROXIES=YOUR_DOCKER_HOST_GATEWAY/32
```

网关使用 host 网络连接回环后端；受信代理地址应取实际 Docker 网络网关，
不要信任所有地址。Caddy 默认覆盖不受信客户端的转发头，并即时转发 SSE。

```sh
docker compose -f compose.yaml -f compose.ip.yaml config --quiet
docker compose -f compose.yaml -f compose.ip.yaml run --rm --no-deps gateway caddy validate --config /etc/caddy/Caddyfile
docker compose -f compose.yaml -f compose.ip.yaml up -d --no-build --no-deps --pull never gateway
# 更新应用的私密配置后，替换运行时，保留数据库与素材。
docker compose -f compose.yaml -f compose.ip.yaml up -d --no-build --no-deps backend postproc cron
curl --fail https://YOUR_PUBLIC_IP/readyz
```

入口为 `https://YOUR_PUBLIC_IP/play`，HTTP 自动跳转 HTTPS。证书与 ACME 账户
保存在 `caddy_data` 卷，Caddy 自动续期；勿删除此卷。短期证书需要持续保持
网关运行及 80/443 可达。验收必须从外网确认 TLS、登录 Cookie 和 SSE，
服务器本机的 HTTPS 成功不表示云安全组已经放行。注册仍需配置邮件后单独开放。
