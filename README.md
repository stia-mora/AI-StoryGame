<div align="center">

# 故事之间 · AI-StoryGame

**选择一个世界，成为其中的人，让行动改变故事。**

面向玩家与创作者的 AI 文字角色扮演平台。

[项目仓库](https://github.com/stia-mora/AI-StoryGame) · [问题反馈](https://github.com/stia-mora/AI-StoryGame/issues) · [部署说明](deploy/PRODUCTION.md) · [MCP 开发交接](docs/creator-mcp-handoff.md)

</div>

## 平台是什么

故事之间将小说和原创设定编制成可以进入、探索和改变的故事世界。玩家选择身份、阅读剧情并决定行动，AI 主持根据世界设定与当前存档推进故事；人物关系、物品、任务和局势随已发生的事件更新。

创作者可以管理章节、人物、世界书和时间线，配置不同的角色与开局，试玩后将故事提供给玩家。平台支持自部署，模型服务可由用户配置，也可由平台为玩家统一提供。

## 玩家如何游玩

1. 在故事大厅浏览介绍，选择想进入的世界。
2. 选择原著人物、推荐身份或自定角色，确认开局设定。
3. 阅读剧情，选择行动建议或自由输入自己的决定。
4. 查看局势、角色、背包、人物、任务和世界线，依据变化作出下一步选择。
5. 保存进度、继续游玩，或从已有节点探索不同分支。

游玩助手提供独立咨询入口。故事配置了时序世界资料时，可以查询当前人物状态、局势和事件依据；未来资料按本次请求的许可揭示，咨询本身不替玩家行动。

## 当前功能

| 能力 | 当前内容 |
| --- | --- |
| 故事大厅 | 游客浏览与搜索已上架故事，查看介绍、封面和可选身份 |
| 角色创建 | 推荐身份、自定角色、原著人物固定姓名，以及故事专属开局选项 |
| 剧情推进 | 流式正文、行动建议与自由输入，支持合并普通步骤、推进到实质选择 |
| 状态与存档 | 六类状态、已保存回合变化、历史阅读、分支存档与恢复 |
| 游玩助手 | 只读咨询；有相应资料的故事支持人物、时间线、局势和证据查询 |
| 评论区 | 每部已上架故事独立评论；游客可读，登录后发表，作者可删除自己的评论 |
| 积分与费用 | 生成前报价、额度预留、实际用量结算，以及停止、断线后的结果恢复 |
| 创作工作台 | 章节、人物卡、世界书、设定复核、时间线与开局配置相关能力 |
| 剧本导入导出 | TXT/MD 分章导入、剧本包迁移、人物卡与相关资料管理 |
| 酒馆模式 | 以人物卡为中心的角色对话，支持 SillyTavern 格式导入导出 |
| 模型与部署 | 多种模型接口、自带凭据、自部署，以及平台统一模型服务 |

玩家无需配置模型即可游玩已由管理员配置服务的故事。创作能力和管理能力按账号权限开放；当前玩家大厅上架由管理员配置。

## 示例故事：《绍宋 · 尧山篇》

<img src="frontend/public/assets/story-covers/shaosong-yaoshan-v1.png" alt="绍宋·尧山篇封面" width="180" align="right" />

本机已完成首个试玩版：范围为前三卷 1—244 章，止于尧山决战及战后收束。

- 可扮演赵官家（赵玖）、岳飞、杨沂中、张浚、赵鼎、胡寅、韩世忠、吕颐浩，也可使用普通身份或自定角色。
- 原著人物从各自对应的时期进入，身份、职分和所知受当期资料约束。
- 已发生的存档事实优先；未改变的部分遵循小说，小说未说明处以宋史补足。
- 允许玩家通过有因果的行动造成分歧，原著后果作为参照。
- 助手默认查看当前和已发生资料，未来按需揭示。

这是一份限定范围的试玩版，完整人物分期和全篇连续游玩仍需继续完善。小说原文、私人研究包及本机数据库不随仓库分发；克隆代码后，故事大厅需在自己的实例中导入和配置。

详情见 [试玩说明](docs/shaosong/playtest.md) 与 [制作过程](docs/shaosong/README.md)。

<br clear="all" />

## 创作者 MCP：开发计划

目标是让用户接入自己的 Agent，提供一本小说，由 Agent 按平台规范制作故事并上传为自己的作品：

```text
提供小说与要求 → 分章阅读与编制 → 校验缺项 → 上传私人草稿 → 试玩修订 → 提交上架
```

**创作者 MCP 服务端尚未实现。** 当前已有剧本包、外部访问令牌和导入接口作为基础。接下来需要补齐创作契约、包校验、进度恢复、游玩配置和外部 Agent 接入。

平台现有的 MCP 设置用于调用外部工具，创作者 MCP 将提供平台自身的创作工具。动态场景背景切换也仍处于方案阶段。

- [创作者 MCP 方案](docs/creator-mcp-proposal.md)
- [下一轮开发交接](docs/creator-mcp-handoff.md)
- [场景背景方案](docs/player-scene-backgrounds.md)

## 本地开发

需要 Python 3.11+（推荐 3.12）、Node.js 22.12+、npm，以及可连接的 PostgreSQL 数据库。准备数据库角色、数据库和 pgvector 扩展的步骤见 [部署文档](deploy/README.md)。下面以 Windows PowerShell 为例。

### 1. 获取代码

```powershell
git clone https://github.com/stia-mora/AI-StoryGame.git
cd AI-StoryGame
```

### 2. 安装后端并配置环境

```powershell
cd rpg
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `rpg/.env`，将 `DATABASE_URL` 设置为自己准备的 PostgreSQL 数据库。完整配置说明见 [环境模板](rpg/.env.example)。迁移使用数据库直连地址；本机端口可能是 5432 或 5433，按实际部署填写。

### 3. 迁移数据库并启动后端

在 `rpg/` 目录执行；新数据库使用 `full`，已有数据库升级使用 `up`。

```powershell
.\.venv\Scripts\python.exe -m platform_app.migrate full
.\.venv\Scripts\python.exe -X utf8 -m uvicorn app:app --host 127.0.0.1 --port 7860 --reload
```

### 4. 启动前端

另开终端，在仓库根目录执行：

```powershell
cd frontend
npm ci
npm run dev
```

打开以下入口：

| 入口 | 地址 |
| --- | --- |
| 玩家故事大厅 | http://localhost:5173/play |
| 登录 | http://localhost:5173/Login.html |
| 创作工作台 | http://localhost:5173/Platform.html |
| 玩家服务管理（管理员） | http://localhost:5173/play/manage |

macOS/Linux 使用 `.venv/bin/python` 替换上述 Python 路径，使用 `cp` 复制环境模板，其余步骤相同。桌面端、移动端与原生 iOS 客户端源码分别位于 [desktop](desktop/README.md)、[mobile](mobile/README.md)、[ios](ios/README.md)。

## 部署与开发文档

公网部署以 [生产配置与验收](deploy/PRODUCTION.md) 为准，另有 [裸机部署](deploy/bare-metal/README.md) 和 [测试服说明](deploy/test-server/README.md)。

| 文档 | 内容 |
| --- | --- |
| [产品定义](PRODUCT.md) / [视觉规范](DESIGN.md) | 玩家体验、交互与界面约定 |
| [玩家服务](docs/player-service.md) | 故事上架、报价、积分、回合保存与恢复 |
| [助手世界查询](docs/player-guide-world.md) | 人物分期、时序资料、证据与未来边界 |
| [故事评论](docs/story-comments.md) | 评论权限、分页、草稿与接口 |
| [MCP 交接](docs/creator-mcp-handoff.md) | 下一轮实现入口、范围与验收 |
| [仓库协作规则](AGENTS.md) | 修改范围、验证和 Git 工作流程 |

## 项目结构

```text
rpg/             FastAPI 后端、剧情与状态引擎、模型接入、存档和数据库迁移
frontend/        React + Vite 网页端、玩家入口与创作工作台
desktop/         Electron 桌面端
mobile/          Expo / React Native 移动端
ios/             SwiftUI 原生客户端
docs/            功能说明、设计与开发交接
docs-site/       文档站源码
deploy/          部署配置与运行说明
```

修改前先读 [AGENTS.md](AGENTS.md)，按改动范围执行相关测试。前端检查使用 `npm test` 与 `npm run build`；后端在 `rpg/` 目录使用虚拟环境中的 pytest，集成测试需要相应数据库及测试配置。

## 来源与许可证

本项目在 [RPG Roleplay](https://github.com/felixchaos/rpg-roleplay-platform) 的基础上继续开发，保留上游及第三方版权声明。代码采用 **AGPL-3.0-or-later**，详见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。故事素材、原文及用户上传内容与代码分别管理。
