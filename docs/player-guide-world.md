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
需要明确记录改史时，可在既有 `memory.items` 保存runtime_fact：

```json
{
  "id": "rescue-hou", "kind": "runtime_fact", "status": "active",
  "turn": 8, "text": "玩家及时救下侯丹",
  "guide": {"subject": "hou-dan", "field": "status", "value": "存活", "cause": "玩家及时拖离战场"}
}
```

假说、待审批写入、未来回合记录不生效。新记录优先于旧记录，明确记录优先于轻量人物索引。
该结构仍由正常GM/记录与提交链写入；助手只有读取能力，不能写入上述内容。
目前GameState.add_memory_item尚无guide参数，正常GM/史官自动产出该结构的链路待接通；
已有存档事件和轻量人物索引可以读取，但不能把构造快照验证冒充完整的真实改史验收。
历史时点查询不把当前的改史记录倒填过去。
时间线也读取当前分支的world.known_events及guide.kind=event的已提交runtime_fact，
保留行动原因和回合出处；未记录年月的事件不伪造日期，不倒填到过去时点。

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

`tests/unit/test_player_guide_world.py`与完整`tests/integration/test_player_credits.py`
合计58项通过，覆盖时期与来源优先级、改史事件、未知时间、未来边界、查询越权、只读性、
本轮许可与报价/重放绑定、资料变更拒结算、分支祖先咨询隔离及既有积分流程。
前端工作区与服务流程21项测试、ESLint及生产构建通过。浏览器访问被Work设置关闭，
未完成页面视觉验收与供应商真实调用；这不是《绍宋》正式数据已完成的声明。
