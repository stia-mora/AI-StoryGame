# 创作者 MCP 接入与验收

实现分支：`codex/creator-mcp`。验收日期：2026-10-27。此次交付未部署生产环境。

## 服务端准备

1. 安装 `rpg/requirements.txt` 或 `rpg/pyproject.toml` 依赖，固定使用官方 Python SDK `mcp==2.3.0`。数据库迁移 **109–112** 建立创作、OAuth、版本及专用试玩账本和后台索引；沿用现有迁移和备份流程。
2. 配置 `PUBLIC_BASE_URL` 为外部客户端实际访问的 HTTPS 根地址，开启 `RPG_FEDERATION_PROVIDER=1`，保留真实登录及现有 Origin 白名单。反向代理需转发 `/mcp/authoring`、`/.well-known/*`、`/oauth/authoring/*` 及 `/api/authoring/*`。
3. 管理员沿用 `/play/manage` 建立服务模型及其凭据，再在 `/play/authoring-admin` 选择试玩模型。未配置或停用时返回明确的服务不可用错误。
4. 账号须已取得创作者权限，或为管理员。新玩家不能通过授权、上传包或兑换试玩码获得创作者权限。

MCP 地址：`https://你的域名/mcp/authoring`。无状态 Streamable HTTP 挂载到现有应用生命周期。原有“平台调用外部 MCP”的客户端功能保留。

## 浏览器 OAuth

支持授权发现、DCR、Authorization Code + PKCE S256、资源受众校验、1 小时访问令牌、30 天轮换刷新令牌、刷新令牌重放撤销和主动撤销。只保存令牌哈希。当前不支持 CIMD。

注册超过 90 天且没有未过期授权请求或有效授权的客户端会被分批清理；如果本地客户端仍保存该客户端 ID，需删除其旧连接并重新注册、授权。存在有效请求或令牌的客户端会保留。每次授权最多轮换刷新令牌 4096 次，达到上限后需重新授权；已使用令牌的历史会保留到该授权完全失效，以便检测重放。注册和授权存在容量与速率限制，达到限制时服务会返回明确错误。

权限为 `authoring:read`、`authoring:write`、`authoring:preview`、`authoring:submit`。工具发现需要 read；上传和导入需要 write；试玩需要 preview；提交需要 submit。网页作者复核必须使用真实登录会话，外部令牌不能代替作者确认。关闭 provider、账号停用、令牌过期或撤销后拒绝新操作；导入在提交内容事务前再次验证凭据。

Codex 配置示例（合并进自己的配置，不覆盖已有内容）：

```toml
[mcp_servers.authoring]
url = "https://你的域名/mcp/authoring"
scopes = ["authoring:read", "authoring:write", "authoring:preview", "authoring:submit"]
```

```sh
codex mcp login authoring --scopes authoring:read,authoring:write,authoring:preview,authoring:submit
```

Claude Code 示例：

```sh
claude mcp add-json --scope user authoring '{"type":"http","url":"https://你的域名/mcp/authoring","oauth":{"scopes":"authoring:read authoring:write authoring:preview authoring:submit"}}'
claude mcp login authoring
claude mcp get authoring
```

按客户端打开的浏览器页面登录已有创作者账号并授权；登录后会返回原授权流程。`--no-browser` 可用于远程终端，仍须在真实登录会话完成同意。

## PAT

在 `/play/authoring` 的“使用个人令牌接入”生成或撤销创作令牌，仅创建时显示明文。使用 `Authorization: Bearer <PAT>`，不要把令牌放在 URL、作品包或版本库中。

官方 SDK 最小调用：

```python
import asyncio
import os
import httpx2 as httpx  # SDK 2.3.0 的 HTTP 类型
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def main():
    headers = {"Authorization": "Bearer " + os.environ["AUTHORING_PAT"]}
    async with httpx.AsyncClient(headers=headers) as http:
        transport = streamable_http_client(os.environ["AUTHORING_URL"], http_client=http)
        async with Client(transport) as client:
            result = await client.call_tool("authoring_get_contract", {"section": "summary"})
            print(result.structured_content)

asyncio.run(main())
```

## 工具与工作流

| 工具 | 输入与结果 |
| --- | --- |
| `authoring_get_contract` | `section=summary/schemas/example`，返回规范、实际模型生成的 schema 或完整原创文件集合 |
| `authoring_create_project` | `project_key,title`；同账号相同 key 幂等创建私人项目 |
| `authoring_begin_upload` | `project_id,size,sha256`；返回账号和项目绑定的上传引用、分片大小及 HTTP 地址 |
| `authoring_upload_chunk` | `upload_id,part,data`；part 从 0 连续编号，data 为 Base64，每片解码最多 128 KiB，相同分片可重试 |
| `authoring_complete_upload` | `upload_id`；核对完整大小和 SHA256，重复完成安全 |
| `authoring_validate_package` | `upload_id`；只校验，返回 valid、errors、warnings、missing、checks 和内容指纹 |
| `authoring_import_draft` | `project_id,upload_id,expected_version`；新项目版本为 0，返回持久化 job_id |
| `authoring_get_job` | `job_id`；返回本人任务的状态、进度、结果或错误 |
| `authoring_get_draft` | `project_id,version?`；返回版本、任务、校验、实际试玩和申请，提供项目页面链接 |
| `authoring_preview` | `mode=create/quote/execute,data={...}`；见下节 |
| `authoring_submit` | `revision_id`；已由作者网页复核的明确版本进入 pending_review，重复提交复用现有申请 |

先获取规范和样例，再创建项目、上传、校验并修复错误，导入后轮询任务。修订上传新包，携带最新项目版本；同内容指纹不会重复导入，过期版本或并发修订返回冲突。每次修订建立独立的私人剧本；内容、overrides、版本及成功状态同事务提交。进程重启恢复导入任务，失败不会暴露半成品。

上传压缩上限 50 MiB、解压总量最多 500 MiB、成员数 100，所有 JSONL 合计最多 500,000 行；服务器可根据内存进一步限制解压大小、JSON 成员和单行大小及结构节点数，实际值以 `authoring_get_contract` 返回的 `limits` 为准。JSON 嵌套深度最多 64 层。内容包解析在服务进程间共享预算，繁忙时返回 429 并可稍后重试，已接受的导入任务会自动恢复。每个账号最多保留四个上传引用，引用有效期 24 小时，后台清理过期数据；导入中的引用保留到任务结束。HTTP 客户端也可以向 begin_upload 返回的地址流式 PUT ZIP，携带相同 Bearer 或真实会话；纯 MCP 客户端使用三个分片工具完成全程。

## 内容契约与原创样例

继续使用 v2 内容包，增加 `authoring.json` v1。实际权威模型为 `rpg/platform_app/authoring/contract.py`、`content_schema.py` 和现有 `GuideWorld`。

- [JSON Schema](examples/creator-mcp/schemas.json)
- 《渡口灯火》：[可读文件集合](examples/creator-mcp/ferry-lamp.json)、[完整 ZIP](examples/creator-mcp/ferry-lamp.pack.zip)
- 《无号星站》：[可读文件集合](examples/creator-mcp/unnumbered-station.json)、[完整 ZIP](examples/creator-mcp/unnumbered-station.pack.zip)，使用两份日志和不同开局时点展示另一种章节结构。

在 `rpg/` 执行 `python -m scripts.export_authoring_examples` 可重新生成以上原创文件与 schema。原创样例可公开使用，私人小说不属于公开测试素材。

来源使用逻辑 key，列出章节索引、UTF-8 正文 SHA256 和 splitlines 行数；声明 scope 及完整性记录。来源总指纹记录输入原件，服务端核对包内每章的指纹、行数和证据定位。`evidence.source/locator` 分别引用来源及章节 key；引用文字须位于声明的行范围。

游玩配置的身份引用 `GuideWorld.subjects[].key` 和 openings 的逻辑 key，开局时点及章节必须一致。原作人物身份必须通过角色卡 `metadata.authoring_subject` 唯一绑定启用角色卡，禁止用同名字符串替代人物身份；导入后映射平台数据库编号。同名人物使用不同 subject，角色卡展示名须唯一，可将人物原名作为时期姓名或别名。

章节摘要覆盖、结构检查、待办缺项、语义质量及实际试玩分开记录；结构通过不能说明语义正确。媒体清单校验封面大小、类型和指纹。包内不能声明平台密钥、模型凭据、审核状态或公开权限。

## 试玩、积分及恢复

`authoring_preview` 的 `data`：

```json
{"mode":"create","data":{"revision_id":1,"identity_id":"keeper","request_id":"UUID","name":"旅人"}}
{"mode":"quote","data":{"revision_id":1,"save_id":1,"kind":"opening","message":""}}
{"mode":"execute","data":{"revision_id":1,"save_id":1,"kind":"opening","message":"","quote_id":"报价 UUID","request_id":"新 UUID","cap_micro":5000000}}
```

create 免费，返回阅读页 URL；同 UUID 必须对应相同版本、身份和名字。quote 支持 opening、turn、guide；turn/guide 需要 message。execute 必须确认报价的 cap_micro，行动内容、资料时点、模型、费率和请求编号均受绑定。请求返回任务编号后可断线，通过 get_job 查结果；勿把断线视为调用失败而立即重发模型请求。

每位已有或未来创作者首次访问专用余额，均在账户锁下领取一次 **10,000 积分**。不过期，重新授权、创建项目、反复访问或重新开通创作者都不会重复发放。仅自己的版本试玩可使用；普通游玩不能消费，试玩不足不会扣普通余额。

试玩沿用现有报价、冻结、真实用量结算、失败返还和流水。积分以 1,000,000 微积分计。兑换码 purpose 为 preview 或 player，原有码默认 player；保留每账户限领、次数和有效期约束。试玩码仅向创作者专用余额充值。

存档保存确定的身份、剧本、开局、封面及服务模型编号快照。更换版本不会改变旧存档资料；模型配置仍由管理员管理，原模型停用后旧存档不能继续生成。已提交版本禁止通过普通编辑接口修改，修订须新建版本。模型任务断线继续记录结果，进程中断不自动重复推理；过期冻结按原有租约机制返还。

## 作者复核和管理员发布

从 `/play` 顶部“我的创作”进入 `/play/authoring`，游玩工作区也可通过账户菜单进入。游客先登录；普通玩家会看到创作者开通说明，权限仍由管理员授予，不自动升级账号。

创作者可复制 MCP 地址、通用 `mcpServers` JSON 配置及发给 Agent 的任务说明，使用浏览器 OAuth 或个人令牌接入。令牌区仅列出创作令牌，新令牌以密码字段显示并可复制、隐藏或撤销；令牌列表加载失败不会阻塞项目管理。

作者可在网页创建项目，选择 ZIP 内容包执行“上传并校验”，查看错误字段路径、警告及缺项，通过后明确点击导入私人版本。上传需 HTTPS 或 localhost，浏览器使用真实 SHA256；同项目的相同文件复用上传引用，完成后的 HTTP 重试返回已完成结果。导入绑定校验时的预期版本，并发修订仍拒绝冲突。后台任务在项目页每 3 秒刷新，网络错误后保留上下文并提供手动刷新，不自动重发收费调用。

项目页展示结构校验、实际试玩、作者复核及审批状态，支持最新与历史版本切换。`authoring_get_draft` 返回所选版本的 `preview_saves`（最多 20 个本人试玩存档）和版本复核链接；网页可创建指定身份和名字的试玩，或继续已有试玩。未配置可用试玩模型时明确提示，仍可编制和校验。试玩兑换入口仅接受专用试玩码，普通游玩码应在游玩积分页兑换。

填写来源授权说明并确认复核后，可提交明确版本；修改尚未保存的授权说明会禁用提交，需再次复核。已待审批或已上架的版本禁用重复提交。MCP 的 submit 工具不能代替网页复核。

管理员在 `/play/authoring-admin` 查看申请、正文分页、契约与实际试玩记录，选择服务模型后批准上架，或填写原因拒绝、暂停。大厅显示作者与版本。发布新版切换版本指针，保留故事编号及评论；源文、剧本包和研究资料继续私有。普通下架与紧急暂停语义沿用玩家服务规则。

## 验收记录与复现

2026-10-29 本轮完成 `/play` 创作入口及网页流程完善，执行前端生产构建、修改文件的 ESLint、Python Ruff 与语法检查；按用户要求未执行测试、真实客户端或浏览器验收，也未部署生产环境。下方历史验收结果仅对应其记录时的代码状态。

所有数据库检查在自动创建并销毁的 `authoring_test_*` 数据库执行，不迁移或改写本机日常数据库。运行账户需具备 PostgreSQL CREATEDB 权限。

```sh
# 在仓库根运行，Python 指向已安装开发依赖的环境
python rpg/scripts/check_authoring.py
python rpg/scripts/check_authoring.py --clients --private-pack
python rpg/scripts/check_authoring.py --live-model tests/integration/test_authoring_regressions.py::test_real_configured_provider_saves_opening_turn_and_guide -q -s
# 可选桌面/手机检查夹具，只监听本机，退出后销毁数据库
python rpg/scripts/check_authoring.py --serve
```

`--clients` 使用已安装 CLI 及临时配置目录，Windows Claude 终端授权验收依赖开发依赖 pywinpty。`--private-pack` 仅检查本机已有私有《绍宋》包。`--live-model` 明确调用已配置的真实供应商，会产生供应商费用；仅在内存读取源配置和凭据，临时数据库保存结果和测试账本。Windows 测试进程对该端点补充 NO_PROXY，避免系统代理的 CONNECT 差异，用户配置不变。

| 验收项 | 实际结果 |
| --- | --- |
| 官方 Python SDK 2.3.0 | auto 与 legacy 初始化模式；真实 TCP/OAuth、11 项工具发现、仅 MCP 多片上传及重试、校验、导入、试玩保存、网页复核及待审提交通过 |
| Codex CLI 0.162.1 | 真实浏览器授权流程、工具发现、app-server 实际 get_contract 调用通过；无推理费用 |
| Claude Code 2.1.296 | 真实浏览器授权流程、连接发现、真实 get_contract 调用通过；本地确定性推理替身只负责驱动客户端选工具 |
| 平台真实服务模型 | 实际开场、后续行动及助手查询均成功保存，专用余额结算、无普通余额扣费通过 |
| 私人 v2 兼容包 | 本机《绍宋》包完整导入通过，未将小说内容提交到仓库 |
| 浏览器页面 | Playwright 0.1.22，1440×1000 与 390×844，明暗主题；审阅、批准、免费建档、独立报价展示通过，控制台无错误 |

最终检查：MCP 功能与真实客户端/私有包 **41 通过**（完整应用生命周期与中间件下运行，真实供应商测试在此轮按开关跳过，已另行 **1 通过**）；现有计费、导入、助手时序与 MCP 配置兼容回归 **147 通过、1 跳过**，跳过项为原有依赖本地文件的旧上传链测试；原有 MCP orphan response 测试 **5 通过**；相关前端 **152 通过**，生产构建通过。新增 Python 文件 Ruff 检查通过，前端无 ESLint 错误；保留 Reader 原有 hook 依赖警告及 Vite 原有构建提示。

常规检查不自动消耗真实模型额度；真实客户端、私有包和付费模型测试均使用显式开关。外部文本按资料处理，语义质量及来源授权仍由创作者和管理员人工复核。此次未进行生产部署、真实公网域名和反向代理上线验收。
