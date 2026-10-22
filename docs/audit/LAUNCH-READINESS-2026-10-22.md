# 公开上线前代码审查

日期：2026-10-22。代码基线：`b1fa9e0`，分支 `main`。

后续代码与部署模板的修复及验收边界见 [修复记录](LAUNCH-REMEDIATION-2026-10-22.md)。下文保留原始审查证据。

**结论：暂不通过公开上线验收。** 登录与会话基础已经存在，但注册凭据绑定、停用账户鉴权、生产路由、数据生命周期与运行保障仍有明确缺陷。游客浏览、玩家新手指引和玩家退出入口也未完成，尚不满足本次提出的用户流程要求。

本轮交付是审查报告，未修改业务实现或生产配置。P1 表示应在对应功能公开使用前修复；P2 表示重要缺陷或运营保障缺口。没有提供线上域名或实际部署配置，因此部署发现按裸机、Compose、K8s 分别限定适用范围。

## 1. 用户流程现状

| 要求 | 当前实现 | 验收判断 |
| --- | --- | --- |
| 登录态 | 数据库会话、Cookie、登录/退出接口；HTTPS 下 Cookie 有 HttpOnly、Secure、SameSite=Lax | 基础存在，账户停用和多种登录分支仍有缺陷 |
| 鉴权 | server/auth=1 时匿名玩家接口返回 401；存档读取校验所有者，后台有 admin 依赖 | 不能用本地免登录配置直接上线，PAT 另有绕过 |
| 游客界面 | PlayerApp 启动即请求受保护的 bootstrap，401 后跳登录页 | 缺少可匿名浏览的故事大厅、故事介绍和登录引导 |
| 新手指引 | WelcomeModal、使用须知挂在创作端 PlatformShell，玩家入口是独立应用 | 普通新玩家不能到达现有指引 |
| 退出/切换账户 | 创作端有退出调用，玩家端导航只有主题和积分 | 普通玩家缺少可用退出入口 |

## 2. P1：上线前需要处理

### F01 注册验证码与密码资料在多 worker 下串绑

- 位置：`rpg/platform_app/auth.py:491`、`:730`。
- 条件：两个 worker 具有独立进程缓存、共享 Redis/数据库；验证码密钥按正常生产要求共享。
- 问题：`_pending_store_get()` 优先使用 worker 的旧本地缓存，验证码查询却选择数据库中的最新有效记录。验证码和待注册凭据只按邮箱关联，没有绑定同一注册事务。
- 复现：worker A 暂存第一份注册资料；同邮箱在 worker B 提交第二份资料并收到最新验证码；在 A 验证第二个验证码，最终建成第一份用户名及密码的账号。独立 PostgreSQL、共享 Redis 桩和两份进程缓存下，最新验证码通过，第一份密码有效，第二份密码无效。无需取得邮箱验证码的预注册者可因此预置受害者账号密码。
- 修复：每个验证码记录绑定不可变的注册事务 ID 和凭据快照，统一共享存储并原子消费；不能让进程内旧资料覆盖共享存储的新资料。增加跨 worker、重复发码和并发验证的回归测试。

### F02 推荐公网部署步骤仍可能保留免鉴权模式

- 位置：`deploy/bare-metal/README.md:209`，`rpg/.env.example:20`，`rpg/core/config.py:33`，`rpg/app.py:399`，`rpg/routes/skills.py:23`、`:35`。
- 问题：推荐裸机指南复制本地模板，必填配置没有声明 `RPG_DEPLOYMENT_MODE=server`、`RPG_REQUIRE_AUTH=1`。默认模式为 local。本机当前两份 `.env` 也显式关闭鉴权，应视为开发配置。
- 影响：新版 `current_user()` 的隐式账户回退有回环限制，不能笼统说所有公网请求都变成管理员；但旧 `_require_api_user()` 在免鉴权时直接返回，非 strict 的 admin 依赖不再拦截匿名调用。Skill 导入/执行使用的正是非 strict 依赖。
- 证据：隔离库现有安全回归中，匿名和普通用户请求不存在 Skill 的运行端点均到达业务层并返回 404，未在鉴权层返回预期的 401/403。没有执行任何 Skill 命令。
- 修复：新增专用生产模板与启动检查，显式启用 server/auth；高危功能统一 strict admin 依赖。公网部署不得仅依赖反代对 loopback 的处理来防护旧接口。

### F03 推荐 nginx 回退规则导致玩家登录循环

- 位置：`deploy/bare-metal/README.md:462`，`frontend/src/components/login/nextTarget.js:7`，`frontend/src/login-app.jsx:65`。
- 触发：按裸机指南部署静态前端，普通玩家登录后进入 `/play`。
- 问题：nginx 对不存在的路径统一回退 `Login.html`；构建产物的玩家入口是 `Player.html`。登录壳发现已有会话又重定向 `/play`，从而循环，存档深链同样无法正确进入玩家应用。
- 修复：为 `/play` 及其子路径配置 `Player.html` 回退；创作端干净路由配置 `Platform.html` 回退，或统一使用后端已实现的 SPA 路由。必须在实际反代后验证登录、刷新和直接打开存档链接。

### F04 停用账户的 PAT 仍然有效

- 位置：`rpg/platform_app/federation.py:166`，`rpg/platform_app/api/admin/users.py:143`。
- 问题：PAT 校验只检查令牌是否撤销、过期及 scope，没有验证用户的 `deactivated_at`、账户模式。停用账户主要撤销 Cookie sessions；没有 Cookie 的 Bearer 请求也不会进入依赖 Cookie 用户的玩家路径限制。
- 复现：停用隔离账号并删除会话后，Cookie 被拒绝，`verify_pat(..., 'library:publish')` 仍成功，真实 HTTP `GET /api/ext/library/scripts` 携带 PAT 返回 200。
- 修复：将有效账户和账户权限检查纳入 PAT 认证；停用/封禁/终止时处理 PAT 与待完成设备授权。测试所有凭据形态，不能仅测试 Cookie。

### F05 运行依赖锁定了已披露的漏洞版本

- 位置：`rpg/requirements.txt:7`、`:13`；`rpg/platform_app/auth.py:890`；`frontend/package-lock.json`。
- Python：扫描当前运行环境的 66 个包，发现 2 个包涉及 3 条公告。`certifi==2026.7.22` 包含应撤出的证书信任根，影响依赖该 CA 集合的对外 HTTPS。上游将此公告标为 Critical；本次扫描建议修复版本为 `2026.10.19`。应更新依赖并重建部署镜像。见 [certifi 官方公告](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)。
- `PyJWT==2.14.0` 也命中公告，修复版本为 `2.15.0`。应用确实调用受影响的 `PyJWKClient` 路径，但本项目外围有 `except Exception`，本轮没有证明应用因此出现进程崩溃、认证绕过或未捕获的 500；不能直接套用公告的最坏影响。见 [PyJWT 官方公告](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-42vr-xj54-vc7v)。
- npm：完整树有 5 个受影响包（3 high、2 moderate），涉及 Vite、Vitest 及开发链传递依赖；`npm audit --omit=dev` 为 0。应更新开发链，但这些结果不等于生产静态 JS 有 5 个可利用漏洞。生产不能暴露 Vite/Vitest 开发服务。

### F06 多 worker 的邮件验证码缺少共享密钥配置

- 位置：`rpg/platform_app/security.py:103`，`deploy/docker-compose.yml:129`，`deploy/test-server/docker-compose.yml:97`。
- 问题：`EMAIL_CODE_SECRET` 未设置时，每个进程使用不同随机 HMAC 密钥。两份 Compose 分别默认多 worker，却没有将该变量传入容器；在宿主 `.env` 中填写但没有 interpolation/env_file 也不会自动透传。
- 影响：验证码生成与验证落在不同 worker 时失败，重启也会使进行中的验证码失效。裸机模板只有注释提示，生产指南未列为必填。
- 修复：所有 worker 使用稳定共享密钥；生产缺失时启动失败。统一透传邮件服务配置，并验证真实域名上的注册、登录码和重置邮件流程。

### F07 账号硬删除存在两个独立阻塞

- 位置：`rpg/cron/hard_delete.py:49`、`:103`、`:110`；`rpg/platform_app/player/schema.py:48`。
- 第一层：删除清单仍包含 v105 中已不存在的 `user_character_cards`、`user_personas`。空账号也会触发 `UndefinedTable`。异常被捕获后没有 rollback/savepoint，事务保持 INERROR，后续整批删除不能继续。
- 第二层：新增的玩家账本、报价、请求等依赖没有纳入删除策略，相关外键未声明级联。只在探针里临时过滤不存在的旧表后，空账号可删除，但调用过一次 `wallet.wallet()`、得到每日积分的账号仍因 `player_ledger_user_id_fkey` 删除失败。无需实际付费或生成剧情。
- 修复：每账号独立事务或 savepoint，补齐全部外键依赖。明确计费数据是删除还是匿名保留，并确保用户删除流程与该策略一致。增加包含真实玩家账本的删除集成测试。

### F08 推荐异步 worker 命令不可启动

- 位置：`deploy/bare-metal/README.md:382`、`:386`；`deploy/docker-compose.yml:180`。
- 问题：工作目录为项目的 `rpg/`，却使用 `python -m rpg.scripts.run_postproc_worker`；同样目录下应使用 `scripts.run_postproc_worker`。根 Compose 的 cron 命令也多了 `rpg.` 前缀。
- 证据：按相同工作目录解析模块，在任何 DB 操作前就得到 `ModuleNotFoundError: No module named 'rpg'`。
- 修复：纠正模块路径，使用专用环境文件和直连数据库配置；确认后处理/审核/生图任务有实际运行的消费者，不能仅确认 Web 进程启动。

### F09 迁移工具覆盖显式设置的数据库地址

- 位置：`rpg/platform_app/migrate.py:45`、`:46`；`deploy/bare-metal/README.md:241`。
- 问题：指南通过 inline `DATABASE_URL` 指定直连 PostgreSQL，迁移模块随后用 `override=True` 加载 `rpg/.env`，可将其覆盖回 PgBouncer transaction pool。
- 证据：使用真实 dotenv loader 语句与临时假配置复现，调用方的 5432 被文件中的 6432 覆盖；未对现有数据库执行这种迁移。
- 修复：显式环境应优先，或使用独立迁移 DSN。验证 advisory lock 始终走直连。生产不能靠修改同一份运行环境文件来区分迁移与应用连接。

### F10 Docker 健康检查在强制鉴权下恒失败

- 位置：`deploy/Dockerfile:60`，`deploy/docker-compose.yml:153`，`deploy/test-server/docker-compose.yml:137`。
- 问题：无 Cookie 的检查访问 `/api/state`，但 Compose 默认启用鉴权。
- 复现：隔离 server/auth=1 的真实 ASGI 应用，匿名 `/api/state` 为 401，而公开 `/api/health` 为 200。原检查将使容器长期 unhealthy，无法提供有效的健康信号。
- 修复：使用公开、无敏感数据的健康端点，区分存活与依赖就绪；不要给探针配置管理员登录凭据。

### F11 容器方案没有持久化用户文件

- 位置：`rpg/platform_app/storage.py:20`、`:75`，两份 Compose 的 backend 配置，以及 `deploy/k8s/deployment.yaml`。
- 问题：头像、AI 图片、剧本原文件等默认写本地 `platform_data`，backend 没有对应持久卷。K8s 多副本也没有共享存储。
- 影响：容器重建丢失磁盘文件，数据库中的 URL/路径仍存在；多副本上传后请求到另一副本会读不到文件。
- 修复：单机明确持久卷与文件备份；多副本使用共享存储或对象存储。恢复演练必须包含文件、数据库及解密所需密钥。

### F12 本次要求的游客、玩家退出与指引尚未交付

- 位置：`frontend/src/player/PlayerApp.jsx:56`、`:106`；`rpg/platform_app/api/player.py:113`；`frontend/src/api-client.js:133`；`frontend/src/platform-app.jsx:380`、`:548`。
- 游客：`bootstrap` 依赖 `require_player/require_user`，未登录立即 401 并跳登录。没有匿名故事目录或详情页面。应提供只读公开 DTO，进入建角/游玩/钱包时再要求登录，不能通过放开现有私人 bootstrap 实现游客功能。
- 退出：普通玩家没有账户菜单或退出按钮，打开 Login 又因现有会话被送回 `/play`，公共设备上不能通过正常界面切换账号。应调用已有退出 API，确认会话撤销后再跳转，并清理当前账号的内存数据。
- 指引：欢迎、使用须知、帮助入口只在创作端，默认进入独立 PlayerApp 的普通玩家无法使用。应在玩家端解释建角、行动、费用/封顶、保存/恢复及助手的边界，保留可再次打开的帮助入口。
- 这些是本次上线范围中的功能阻塞，不能把现有内部组件或受认证接口当作已经完成的游客/指引体验。

### F13 登录后的跳转过滤可以绕过

- 位置：`frontend/src/components/login/nextTarget.js:12`，调用点 `frontend/src/login-app.jsx:72`。
- 问题：正则检查原始字符串，没有用浏览器 URL 规则归一化。
- 证据：`next=%2F%5Cevil.example%2Flogin` 经函数返回后，被 WHATWG URL 解析为站外 HTTPS 地址，creator/admin 登录后会跳往站外。前置空格或含 Tab 的协议写法也通过过滤，但本轮未证明 `javascript:` 会在具体浏览器/CSP 下执行，不将它表述为已确认 XSS。
- 修复：先 `new URL(raw, location.origin)`，再要求 HTTP(S)、同源，并限制允许的站内路由及 Login 自循环目标。为编码、反斜杠、控制字符和重复参数增加测试。

### F14 Apple 新建账户绕过永久邮箱封禁

- 位置：`rpg/platform_app/auth.py:953`；对照密码注册的 `:364`。
- 条件：开放 Apple 登录；同邮箱已在永久封禁表中，旧用户记录已被删除。
- 复现：隔离库中，密码注册被拒绝，Apple 建号服务函数却创建同邮箱账号并颁发有效会话。测试没有伪造 Apple 身份校验，也没有调用外部 Apple 服务；缺陷在身份校验之后的本地准入检查。
- 修复：所有账户创建路径共用邮箱规范化、封禁和注册准入逻辑。身份供应商验证成功不能代替站内账户准入。

## 3. P2：认证完整性和运行保障

| 编号 | 发现、证据位置 | 触发与修复方向 |
| --- | --- | --- |
| F15 | 邮箱别名绕过账号级失败桶，`rpg/platform_app/auth.py:1334` | 限流按 normalize_username，查询按去掉 +tag 的 normalize_email。8 个不同 IP/不同 tag 都执行密码校验；相同邮箱第 6 次起被限流。按固定用户 ID/统一标准标识计数，同时保留 IP 桶。 |
| F16a | 玩家会话过期后丢失存档深链，`frontend/src/components/login/nextTarget.js:7` | 普通玩家的 next 无条件变为 `/play`。应允许经过校验的 `/play/...` 返回地址。 |
| F16b | 魔法链接跳向错误应用/不存在的页面，`frontend/src/login-app.jsx:143` | 硬编码 `/profile-setup` 或 `/profile`，未按账户模式分流；前者未注册。统一登录成功后的用户路由与真实资料补全页面。 |
| F16c | 现有会话抢走密码重置页面，`frontend/src/login-app.jsx:65` | 自动进入应用的 effect 未排除 `#reset?token=...`。应优先处理显式重置流程。 |
| F16d | 创作端退出失败仍跳走，`frontend/src/platform-app.jsx:532` | logout 异常被吞掉，原会话仍有效，Login 又自动登录。失败应提示并允许重试，确认撤销后再导航。 |
| F17 | 删号宽限期撤销不可达，`rpg/platform_app/frontend_routes/account.py:194`、`:220` | 申请删除立即停用并撤销所有会话，但 cancel-delete 要求正常会话。真实 HTTP 为申请 200、原会话撤销 401、正确密码登录 400。应提供限权恢复认证/一次性恢复凭据并检查截止时间。 |
| F18 | 后台安全设置只保存、不参与实际策略，`rpg/platform_app/api/admin/security.py:48`，`rpg/platform_app/auth.py:26` | 保存 session_timeout_days=1 返回 200，新会话实际仍为 14 天；该配置键没有其他运行读取方。IP blocklist、密码长度等也缺少接入。应统一配置权威来源，未实现的选项不应显示为生效。 |
| F19 | 部署通用请求限制没有对应实现，`deploy/docker-compose.yml:143`，`rpg/core/startup.py:671` | 频率、超时、body 限额变量在 Python 运行代码无引用。无 DB 探针设置每分钟1次/1KiB/.001秒，连续3次2KiB/.02秒请求仍200。业务局部限流依然存在，但不替代通用限额。补实际限制或在生产反代实现并验证。 |
| F20 | 过期报价永久积累，`rpg/platform_app/player/wallet.py:128`、`:336`，`frontend/src/player/ActionChoices.jsx:11` | 每次报价新增行，四个选项每分钟刷新；到期不自动删除，reaper只处理执行租约。探针中的3条过期未使用报价在reap后仍存在。应清理过期且未被账单引用的报价，并为报价接口限流；不能删除结算审计依赖。 |
| F21 | 长存档读取无界，`rpg/platform_app/player/catalog.py:130`、`:147` | 读取整条祖先链的所有正文及前后状态，再逐轮计算progress；前端虽逐页展示，接口仍全量返回。轮数增长会放大查询、传输、序列化与重算成本。代码证据已确认，未做容量压测；应分页历史并限制单次工作量。 |
| F22 | K8s 存活/就绪探针落到前端 HTML，`deploy/k8s/deployment.yaml:73`、`:84` | Python 无 `/livez`、`/readyz`，SPA fallback 返回200 HTML。提取真实SPA类的无DB探针已复现。补真实存活与就绪路由，不能用壳页面证明数据库可用。 |
| F23 | 新域名的邮件回调地址缺少配置说明，`rpg/platform_app/email.py:20` | PUBLIC_BASE_URL 默认原维护站域名。迁移到新域名若未显式设置，重置等链接仍指向原站。生产模板应要求本站公网HTTPS地址，并校验邮件中的实际链接。 |

## 4. 已验证的正向基础

- server/auth=1 的匿名 `/api/state`、`/api/player/bootstrap` 返回 401；认证 schema 与非敏感健康检查可公开访问。
- HTTPS 请求的登录 Cookie 已实际验证具有 HttpOnly、Secure、SameSite=Lax。
- 玩家存档读取、请求状态、用量明细按用户范围查询；相关越权/旧计费入口绕过回归已运行。
- 玩家计费具备钱包锁、请求幂等、预算预留、保存与结算事务、租约回收等基础；相关隔离数据库测试已覆盖，并非从 UI 是否可见推断权限。
- Compose 的数据库/Redis 公开端口仅绑定回环，镜像构建排除环境密钥与运行数据；基础异常处理和安全头已有实现。

## 5. 验证结果与边界

| 检查 | 结果 |
| --- | --- |
| 全前端 Vitest | 62 个文件、508 项测试通过 |
| 前端 TypeScript | 通过 |
| 生产构建 | 通过；保留既有 Vite 配置及大包警告 |
| ESLint | 0 errors，1914 warnings，未在本轮修改业务实现 |
| 全新隔离 PostgreSQL | 完整迁移成功，到 v105 |
| 后端关键路径扩大检查 | 306 passed、7 failed，136 subtests passed；详见下面分类 |
| 注册/PAT/删号/安全设置探针 | 已对独立库复现报告中注明的结果，未发起模型调用或真实邮件 |
| npm 依赖 | 全树 5 个受影响包；omit=dev 为 0 |
| Python 依赖 | 当前环境 66 个包，2 个受影响包、3 条公告 |

后端 7 个失败分为：

1. 2 项 Skill 权限回归在 local/auth=0 下返回404，暴露 F02 的非 strict 权限短路。
2. 1 项密码重置旧 mock 仍模拟旧 SELECT 读取方式，未适配现有原子 UPDATE RETURNING；不据此认定真实密码重置失败。
3. 4 项账户生命周期测试自身仍有旧 `rpg.cron` 导入路径和缺少 display_name 的夹具问题，其中一个错误会使模块共享事务进入 aborted 状态。真实 HTTP 撤销和真实 cron 的功能缺陷由独立探针确认，不能靠修复测试夹具便认为功能已修复。

最初空库跑228项时还有一项默认玩家注册因“本地首用户自动管理员”的夹具前置条件失败；在隔离库建立明确的管理员前置后，扩大检查中该项通过。这不是已确认的生产注册提权漏洞。

现有 CI 后端主要跑 tests/unit，未纳入上述关键认证 HTTP、账户生命周期和玩家交易集成套件。应将修复后的关键路径加入部署门禁。通过 UI 测试或构建不能代替上线鉴权验收。

本轮没有部署公网服务、使用现有业务库做写入测试、调用模型或发送真实邮件。未做真实 DNS/TLS、邮件送达、Apple 外部认证、实机移动端、容量压测、灾备恢复或外部渗透测试；这些需要在确定部署方案后用独立预发布环境验收。代码审查覆盖关键入口和横切边界，不代表逐条证明全仓库每条业务分支安全。

## 6. 修复顺序与上线门禁

1. 先修 F01、F02、F04、F13、F14 的账户和权限边界，更新运行依赖，加入可稳定失败/通过的回归测试。
2. 选择一个正式部署路径，修复 SPA 路由、共享验证码密钥、邮件域名、迁移/worker、健康检查和文件持久化；用该路径的实际配置部署预发布环境。
3. 补齐游客只读目录/详情、玩家账户退出、可回看的新手帮助，并修复所有登录成功、会话过期及重置的导航分支。
4. 完成删号撤销、硬删除和账本数据处理策略，修复测试夹具，并把关键集成测试纳入 CI。
5. 用两个普通账户和一个管理员逐项验收：匿名仅可读公开内容；互换存档/请求编号不得越权；普通玩家不能调用创作/管理/外部发布能力；停用账号后所有凭据失效；退出和重置后旧会话失效；登录后可回原存档。
6. 在预发布验证真实邮件、完整/停止/断网恢复的计费、后台任务、备份恢复和预期并发，确认日志不泄露凭据，再决定正式开放。

本地证据保存在忽略目录 `.dev-logs/launch-review-*`、`.dev-logs/auth-audit-probe.py`、`.dev-logs/hard-delete-audit-probe.py`，不随报告提交。修复应按问题分成独立提交，保留各自回归测试和部署验证结果。
