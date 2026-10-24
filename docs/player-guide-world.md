# 游玩助手世界查询

后端入口为 `platform_app/player/guide.py`，世界数据与确定性查询在 `guide_world.py`。
当前已实现服务端查询和前端本轮未来许可；绍宋正式资料和真实游玩验收仍待完成。

## 数据与时间

使用既有 `script_overrides.data.guide_world`，随v2剧本包的 `overrides.json` 导入。
数据结构由 `GuideWorld` 校验：

```json
{
  "version": 1,
  "edition": "shaosong-yaoshan-v1",
  "moments": [{
    "key": "jy4-05-29-after-battle", "order": 100,
    "label": "建炎四年五月廿九战后", "chapter_min": 242, "chapter_max": 242
  }],
  "subjects": [{"key": "wu-jie", "name": "吴玠", "kind": "character", "aliases": []}],
  "facts": [{
    "id": "wu-jie-commander", "subject": "wu-jie", "kind": "state",
    "field": "identity", "value": "当期职位的核对内容",
    "starts_at": "jy4-05-29-after-battle", "ends_at": null,
    "basis": "novel", "certainty": "confirmed",
    "evidence": [{"source": "绍宋", "locator": "具体章号与行号"}]
  }]
}
```

这是结构示例，不是正式设定条目。日期只有月、季节时，label必须保留这种精度。
`order`表示故事内时序，不是揭示章号。`starts_at`包含起点，`ends_at`不包含终点。
闪回或后章揭示可指向更早的moment，不能按其出现章号误判未来。
历史对照的moment可不绑定章节，便于记录小说时期以外的两宋基线。

当前时点优先匹配存档 `world.guide_moment`、`world.time`、已锁时间线标签；否则使用
快照中的时间线锚点章、worldline进度，再回退到会话worldline中的进度章号。
切换分支后，快照中的分歧记录优先于会话估计。若同章含多个场景，采用最早可确定场景，避免泄露当日下午等后事。
仍无法确定时，仅返回明确的存档事实；不以“未知进度”开放整本书。
如存档写入 `world.guide_edition`，必须与资料edition相同。
新建剧本存档时，服务端在写根提交与KB之前读取已授权剧本的guide_world并绑定edition。
优先使用所选出生点的准确时间或进度章；默认从剧本开头进入时才采用最早的正文章时点，
不把更早的真实历史参考条目当开局。资料未覆盖的出生点仍绑定版本，但不猜精确时点。
无guide_world的旧故事保持原有建角流程。无效世界资料返回明确错误，不留下半建档或收费。
更新edition后，旧存档仍需明确的资料版本迁移或保留旧版；目前不会自动把旧存档改绑最新版。

subjects的aliases仅放稳定姓名异写；新封爵位、称号是有起止时点的事实，不能作为永久别名。
facts的kind为state、event或history；basis为novel或history。
certainty可为confirmed、reported、inferred、disputed，报告和推断不可装成既成事实。
Evidence可附chapter_index、line_start、line_end与chapter_sha256；行区间必须成对且起点不晚于终点。
绍宋私有包构建器会把每条小说依据与已读章节逐项核对，拒绝范围外、指纹不符或越章的证据。

## 存档分歧与事实优先级

查询状态逐字段优先使用本存档记录，再用小说，最后才是史实补缺。
若有 `worldline.divergence_chapter`，其后的原著资料标为
`baseline_after_divergence`，助手只能作为对照，不能声称当前分支必然如此。
分歧之前已完成的事件仍是过去事实；史实资料统一标为historical_reference。
同来源等级的状态冲突保留并标记conflict，不静默挑选一条。

已提交的 `active_entities` 可提供角色身份、状态和当回合位置；旧的最后目击位置不能当作当前位置。
旧的结构化快照可在既有`memory.items`保存runtime_fact，查询端继续支持：

```json
{
  "id": "rescue-hou", "kind": "runtime_fact", "status": "active",
  "turn": 8, "text": "玩家及时救下侯丹",
  "guide": {"subject": "hou-dan", "field": "status", "value": "存活", "cause": "玩家及时拖离战场"}
}
```

假说、待审批写入、未来回合记录不生效。新记录优先于旧记录，明确记录优先于轻量人物索引。
新回合采用下节的world_fact记录路径；普通memory.items仍会裁剪，不再承担长期世界状态的唯一来源。
历史时点查询不把当前的改史记录倒填过去。
时间线也读取当前分支的world.known_events及guide.kind=event的已提交runtime_fact，
保留行动原因和回合出处；未记录年月的事件不伪造日期，不倒填到过去时点。

## 正常回合记录

已配置`world.guide_edition`的存档，统一史官及旧提取器均可以生成world_fact op，
沿正常`apply_structured_updates`和回合提交链保存到分支快照的world_facts。
原生工具schema与JSON提示使用同一字段定义；其他set/append操作仍支持原有数组等值形状。

```json
{
  "op": "world_fact", "subject": "侯丹", "subject_kind": "character",
  "field": "status", "value": "存活，右臂受伤", "kind": "state",
  "certainty": "confirmed", "cause": "玩家将其拖离战阵并请军医止血",
  "quote": "军医确认侯丹尚活，右臂受伤，留营休养。", "diverges": true
}
```

这是改史测试示例，不是原著内容。quote必须逐字存在于本轮剥去ops的叙事正文且包含主体名。
服务端校验类型、字段、长度和出处存在性；语义是否符合正文仍依赖史官提取及后续游玩验收，
不能把引用匹配宣称为自动证明一切判断。报告用reported和report字段，拟议用proposal，
都不能标为已经改史或覆盖真实官职、存亡。事件用kind=event、field=event。

回合、当前时间、时点键和进度章由服务器记录；模型不能注入save_id、turn等溯源字段。
时间更新先处理，之后再登记本批事实；改日期会清除旧的精确场景键，避免查询永远停在开局。
read_only/default模式进入既有待审批队列，批准后仍保留最初回合与时间，不倒填批准当天。
full_access/auto_review沿既有叙事写入规则直接应用。普通path写入不能覆盖world_facts以绕过出处检查。
同一条去重，每回合最多12条；长期记录不随普通记忆裁剪，现有分支快照和KB子树投影一并持久化。

助手按当期逐字段读取最新记录，支持原著没有的存档人物；历史查询只使用可明确映射到该时点之前的记录。
当前查询不把新传闻覆盖为旧的确证状态。改变后的事实及原因也以有界上下文送回GM，
让后续叙事能沿本分支发展，仍明确全局资料不自动成为角色本人所知。

## 工具和调用

助手最多选择四个查询：get_current_time、get_timeline、get_character、get_situation、
get_history、get_evidence。参数只有query、at、fact_id、limit；没有可选的user_id、save_id、
script_id或未来开关。存档授权和剧本绑定由服务器确定，单次读取后固定同一资料版本。

模型先返回查询计划，服务器执行白名单工具，再让模型依据结果回答；各供应商沿用同一结构化调用接口。
每个工具结果最多6000字符，报价包含计划与回答两次调用及工具上下文，仍按供应商实际用量结算。
停止、预算封顶、失败释放沿用现有流程；结算前复核分支提交和世界资料版本，变更后不保存旧回答。
旧故事没有guide_world时保持一次回答，不使用未整理的静态终局角色卡填现状。

## 本轮未来许可

`POST /api/player/quote` 和 `POST /api/player/execute` 都增加严格布尔值
`reveal_future`，默认false，只能用于kind=guide。报价指纹包含该许可，因此不能以无许可报价
执行有许可查询，也不能改变许可重放相同request_id。实际调用读取预留请求profile中保存的许可。

工具按事件真实起点阻断未来状态、时间线、史实对照与出处查询；问题或模型参数不能覆盖。
许可只属于本轮。带未来许可的历史咨询不进入下轮默认上下文；其他分支的咨询也不参与当前分支上下文。
界面使用默认关闭的“本次揭示未来”勾选项，改变许可后重新报价，旧报价不能发送。
发送后立即重置，失败释放后也不会沿用许可；恢复中的请求仍保存其原始许可，不作为长期偏好。

全局现状可供玩家理解，不能据此声称其扮演角色已经知道远方秘密、获得能力或采取了行动。

## 验证记录

查询、记录、权限、上下文、时间更新和完整积分流程的相关150项单元/数据库测试通过。
其中真实数据库用测试替身输出史官结果，经生产JSON应用与收费回合提交链，验证获救状态查询、
KB投影无损、切换分支和恢复原结果；尚未以真实供应商模型跑完整故事，不能视为最终游玩验收。
前端工作区与服务流程21项测试、ESLint及生产构建通过。浏览器访问被Work设置关闭，
未完成页面视觉验收与供应商真实调用；这不是《绍宋》正式数据已完成的声明。

建角绑定另有7项新增单元/数据库用例，验证默认开头、所选章节、未覆盖出生点、
根提交与KB一致、免费创建及无效资料原子拒绝。连同本轮相关查询、记录、打包、
索引、史官与积分检查合计107项通过，不将此前150项与本轮重叠用例简单相加。
