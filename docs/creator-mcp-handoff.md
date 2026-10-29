# 创作者 MCP 功能开发交接

原始交接日期：2026-10-26（Asia/Shanghai）。实现状态更新于 2026-10-29。

**创作者 MCP 已在 `codex/creator-mcp` 实现。** 当前接入方式、原创包、schema、积分规则、实际客户端及模型验收记录见 [创作者 MCP 接入与验收](creator-mcp.md)。已实现 OAuth/PAT、11 项工具、不可变私人版本、专用试玩积分、网页复核和管理员发布。本次不部署生产环境。

2026-10-29：`/play` 顶部及阅读界面的账户菜单提供“我的创作”。创作页补齐账号开通提示、MCP 配置与任务复制、网页 ZIP 校验导入、任务自动刷新、历史版本及继续试玩入口。网页仍遵循现有账号和发布权限。本轮仅执行构建与静态检查，按用户要求不运行测试；历史测试不代表本轮页面已完成实际客户端或浏览器验收。

以下保留为开工前的背景和验收要求；其中“尚未实现”“接下来”等措辞描述 2026-10-26 状态，当前代码与验收以接入文档为准。

## 从这里接手

用户希望：用户接入自己的 Agent，向 Agent 提供一本小说；Agent 按平台规范制作完整可玩的故事剧本，上传到平台，作品归属该创作者，并能在平台试玩、修订及提交上架。

先读本文件，再读 [产品与技术方案](creator-mcp-proposal.md)。方案已经分析现有代码和《绍宋》的实际制作流程；接下来直接进入实现，不必重复长时间调研，也不必重新阅读《绍宋》全书。

给新对话的启动指令可以直接使用：

> 请先读取 AGENTS.md、docs/creator-mcp-handoff.md 和 docs/creator-mcp-proposal.md，在当前项目实现创作者 MCP。复用已有鉴权、剧本包和导入服务，先完成外部 Agent 获取规范、校验内容包、上传私人草稿、配置开局并试玩、提交上架的完整链路。按文档补足权限、幂等、版本及真实 MCP 客户端验收，不要只停留在方案，也不要重跑《绍宋》研究。保留现有用户改动，按阶段提交 Git。

## Git 与交付状态

- 本机工作区：`E:\Group-projects\rpg-roleplay-platform`。
- 新的 `origin`：`https://github.com/stia-mora/AI-StoryGame.git`；分支 `main` 跟踪 `origin/main`。
- 原仓库保留为 `upstream`：`https://github.com/felixchaos/rpg-roleplay-platform.git`。
- 用户指定的新仓库原为空，已先推送 `main` 的现有完整提交历史，功能基线为 `59604b9`；本交接文档随后独立提交并推送。
- 开始开发前重新检查 `git status`、暂存区、分支和远程；遵守根目录 `AGENTS.md`。不要把新改动推回原 `upstream`，不要强推覆盖用户的后续提交。创建功能分支时使用 `codex/` 前缀。
- 原始小说、私人研究目录 `manuscript/`、交付文件 `output/`、数据库、用户上传与环境凭据不在代码仓库中。克隆代码不等于恢复本机剧本与存档。

最近相关提交：

| 提交 | 内容 |
| --- | --- |
| `59604b9` | 创作者 MCP 可行性与编制流程方案，仅文档 |
| `6d7ecc7` | 所有已上架故事的公开评论区 |
| `d4a50a4` | 《绍宋》封面；动态场景背景仍为方案 |
| `16284e0` | 原著人物开局与更长回合正文 |
| `8dd015e` | 《绍宋》本地试玩、资料导入及助手查询验收 |

## 已确认的方向与首版边界

1. 用户自己的 Agent 负责使用自己的模型阅读、创作和管理本地工作目录。平台提供编制规范、校验、草稿、试玩、发布能力；首版不建设平台托管的全文阅读 Agent。
2. 长任务分批做、保留进度和版本。断线恢复不重复创建作品；Agent 停止后平台保留成果，不能宣称平台会自动继续外部 Agent 的工作。
3. “完整”按作品声明范围、必交资料和执行过的验收判定。章节覆盖、人物分期、主线资料、结构检查与试玩结果分别记录，不能只凭条目数量或 Agent 自报“已读”认定完成。
4. 平台已有 MCP 页面是**平台调用外部工具**。本需求是新增**外部 Agent 调用平台的 MCP 服务端**，两者共存，不能把设置页配置成功当作本需求完成。
5. 上传私人剧本、公开分享剧本包、上架玩家大厅是不同操作。保留作品归属、私有源文和发布权限边界。
6. 普通玩家账号不能通过调用 MCP 或上传包自动取得创作者／管理员权限；创作者账号的开通与状态要沿用平台规则。
7. 《绍宋》的“小说优先、宋史补充”和古雅话风属于作品配置，不应成为任意小说都必填的全局要求。
8. 首版不包含自动生成全套背景图。封面可作为资源上传；场景背景方案见 `docs/player-scene-backgrounds.md`，不应扩散本次范围。

## 优先阅读的实现入口

| 文件 | 接手时关注什么 |
| --- | --- |
| `rpg/platform_app/api/__init__.py`、`rpg/app.py` | 路由注册、应用启动与 MCP 服务挂载位置 |
| `rpg/platform_app/federation.py` | PAT 创建／验证／撤销、设备授权、创作者状态检查、外部包导入 |
| `rpg/platform_app/api/federation.py` | Bearer 令牌依赖、provider 开关、`/api/ext/library/*` 接口 |
| `rpg/platform_app/api/_deps.py` | 现有 cookie 登录和本机免登录回退；不能将此回退直接作为 MCP 身份认证 |
| `rpg/platform_app/knowledge/script_pack.py` | `FORMAT_VERSION = 2`、`import_script_pack`、`export_script_pack`、包大小及解压边界、内部编号映射 |
| `rpg/platform_app/api/scripts/imports.py` | `/api/scripts/import-pack`、TXT/MD 导入、分片上传与切章预览 |
| `rpg/platform_app/api/scripts/review.py`、`library.py` | 设定复核、公开分享条件和归属校验 |
| `rpg/platform_app/api/scripts/cards.py`、`media.py`、`listing.py` | 人物卡、封面、时间线与出生点相关接口 |
| `rpg/platform_app/api/admin/player.py` | 玩家大厅故事配置、身份、开局默认值、服务模型绑定和发布权限 |
| `rpg/platform_app/player/guide_world.py`、`guide.py` | `GuideWorld` 数据约束、同版时序资料、全局与未来查询边界 |
| `rpg/platform_app/db/migrations.py` | 新表走现有迁移机制；交接时最新编号 108，实施前再检查，勿假定下一编号永远是 109 |
| `rpg/routes/mcp.py`、`rpg/mcp_broker.py` | 已有 MCP 客户端能力；避免新增依赖或升级 SDK 时破坏它 |
| `frontend/src/player/PlayerApp.jsx`、`Initialize.jsx`、`Reader.jsx` | 现有玩家入口与试玩阅读体验，尽量复用 |
| `PRODUCT.md`、`DESIGN.md` | 产品结构与现有界面规范；需要修改前端时先读 |

已有 `POST /api/ext/library/scripts/publish` 使用 PAT 和包导入服务；它不等于玩家大厅发布。`federation.VALID_SCOPES` 目前仅有 `library:read`、`library:publish`，新增创作权限要连同白名单、签发、验证和测试一起改。现有 PAT／设备码实现不代表已经具备 MCP 标准 OAuth 授权发现。

普通 `/api/scripts/*` 主要使用 cookie；推荐抽取或复用业务服务，让 HTTP 页面和 MCP 在各自身份入口后调用同一业务逻辑，避免用内部请求冒充浏览器会话。provider 开关的部署含义需要保留，不应为了工具可用而无条件开放所有外部接口。

## 当前最大的格式缺口

v2 内容包已有章节、章节事实、人物卡、世界书、实体、时间锚点、世界线、overrides，以及可选检索片段；`overrides.guide_world` 可以承载时序人物与助手资料。

但包没有独立携带 `player_stories` 的完整游玩配置，也不自动携带封面文件。需要定义版本化的游玩配置和媒体清单，包含简介、身份、原著姓名绑定、各自开局与默认值；平台服务模型／密钥由平台管理，不写入作品包。用作品内逻辑标识引用角色与开局，由服务端映射内部数据库编号。

现有 TXT/MD 分片上传有扩展名校验，不能直接把 ZIP 发进去。大包上传需要受项目及账号约束的入口；MCP 工具传上传引用。针对没有任意 HTTP 能力的 MCP 客户端，须实测受限分片工具或配套本地适配器。不要假定每个 Agent 都能运行 shell。

## 建议的实施顺序

### 1. 创作契约与原创样例

先从实际数据模型生成／维护权威 schema，明确内容包、游玩配置、来源证据、完整性清单和错误格式。提供一篇自写短故事的完整样例，让外部 Agent 能独立照着制作，不使用《绍宋》原文作为公开测试素材。

确定 `authoring_get_contract` 的返回内容。拟议工具名见方案，可以为一致性调整；不必为了清单机械新增抽象层。

### 2. 项目、校验与私人导入

实现 `authoring_create_project`、`authoring_validate_package`、`authoring_import_draft`、`authoring_get_job`、`authoring_get_draft`，复用现有包导入服务及大小边界。确定项目归属、草稿版本、内容指纹、上传引用、幂等和并行版本冲突行为。

远程服务优先考虑 Streamable HTTP，固定实际支持的协议与 SDK 版本。复用现有账号及令牌基础，按目标客户端补齐授权发现和 OAuth 流程；手动 PAT 或 stdio 适配器可以作为明确限定的接入方式，不能把它们宣称成通用 OAuth 接入已经完成。

### 3. 游玩配置、试玩与提交

增加创作者自己的配置草稿和 `authoring_preview`、`authoring_submit`。试玩绑定指定资料版本与身份，模型调用遵守明确预算和现有扣费／失败恢复机制。提交返回真实待审／上架状态，不通过 MCP 给用户管理员能力，也不向外泄露平台模型凭据。

### 4. 真实端到端验收

用真实 MCP 客户端执行授权、工具发现、规范获取、校验失败与修复、文件上传、私人导入、断线重试、开局试玩及提交。然后在本机用《绍宋》已有包做兼容回归，再以第二种结构的小说样例检验通用性。

必须覆盖：其他用户作品越权、撤销与过期令牌、玩家账号限制、无效／过大包、来源引用错误、同名人物与时期冲突、不同身份开局、重复导入、并行更新、版本变化后的旧存档，以及助手未来隔离。格式通过和语义质量分开汇报；外部文本始终作为资料处理。

## 本机环境与检查命令

环境路径是本机状态，换机器须按仓库说明重新配置。不要把实际 `.env`、密钥、PAT、数据库连接密码写进提交或工具输出。

- 当前可用 Python：`E:\Group-projects\rpg-roleplay-platform\rpg\.venv\Scripts\python.exe`；pytest 同目录。不要假定在仓库根 `.venv`。
- 前端开发地址：`http://localhost:5173`；后端：`http://127.0.0.1:7860`。是否仍在运行，接手时重新确认。
- 本机 Postgres 使用 5433；读取既有环境配置，不照搬生产文档中的默认端口覆盖它。
- `scripts/dev.ps1` 当前引用根 `.venv`，与本机实际 venv 不同；不要未经检查直接用它重启服务。后台启动需用隐藏窗口，并先确认端口和进程归属。
- 集成测试会自动读取 `rpg/.env`；先确认测试隔离和清理方式。曾有凭据相关测试因缺少 `RPG_MASTER_KEY` 失败，只能使用测试进程自己的临时配置，不能为测试修改生产主密钥。
- 上轮 Work 设置禁用浏览器，未做视觉验收。若后续需要页面验收，先检查当前可用浏览器；不要绕过禁用设置。

以下为接手时可选的相关回归命令，本次交接没有重新执行这些测试：

```powershell
# 在 rpg 目录：先按改动范围选择，新增 MCP 测试另加入
.\.venv\Scripts\pytest.exe tests/unit/test_player_guide_world.py tests/unit/test_causal_story_policy.py tests/unit/test_mcp_add_contract.py tests/unit/test_mcp_broker_orphan_response.py -q
.\.venv\Scripts\pytest.exe tests/integration/test_script_pack_reveal.py tests/integration/test_script_pack_chunks.py tests/integration/test_upload_import_chain.py -q

# 在 frontend 目录：若改动了登录、分享或玩家入口
npm test -- src/__tests__/script-sharing-ref.test.jsx src/__tests__/script-play-gate.test.jsx src/__tests__/player-comments.test.jsx
npm run build
```

历史验收供参考：评论区相关 55 项后端与 110 项前端测试通过，生产构建通过；更早的《绍宋》角色与篇幅改动也做过真实建角和真实模型回合。这些不是新增 MCP 的验收结果；不能替代本轮开发后的检查。

## 《绍宋》素材与已知限制

- 最新交付状态以 `docs/shaosong/playtest.md` 为准；部分早期设计文档仍保留“尚未正式入库”等阶段记录。
- 本机玩家故事 1546，私人剧本 2790；仅供定位现有试玩，跨部署编号不同。
- 私人包：`manuscript/shaosong/authoring/shaosong-yaoshan.playtest.pack.zip`。本地完整助手资料：同目录 `playtest-guide-world.json`。两个文件都未上传 GitHub。
- 包覆盖前三卷 244 章；全书正文 435 章。当前版不是完整全书改编，亦不是全部人物每个时期均有精细档案。
- 已编人物、地点、场景、因果前提、助手时序资料可以用于验证平台能力；仍有未知状态和未实现的逐场条件执行，不应把已有候选事件当作全自动事件系统。
- 现有 `rpg/scripts/build_shaosong_pack.py` 固定《绍宋》和 244 章，只能作为专项构建经验。不要对外暴露为任意小说通用编制器，也不要让公共 MCP 测试依赖本机私人包。
- 原著人物固定姓名、11 种身份及对应开局已经接通；封面已接通；动态场景背景尚未实现。公开评论区已完成，无需在 MCP 开发中重做。

交付新功能时请更新用户文档和本交接状态，报告实际接通的客户端、执行过的测试、尚存限制与可直接操作的入口，提交并推送到用户的新仓库。
