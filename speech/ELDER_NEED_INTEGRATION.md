# 跨场景老人需求库

四个现用语音场景通过 `elder_need` 保存可供照护控制台查看的摘要。各场景自己的业务表仍保留完整记录；共享表只用于跨场景查看和个体化偏好，不替代活动报名、护理记录或通话日志。

| 场景 | 写入内容 | 后续使用 |
| --- | --- | --- |
| 护理咨询 | 每次咨询一条；风险、工作人员跟进状态和最新一轮表达会更新到同一条记录 | 控制台跟进 `in_progress` 的工作人员事项 |
| 娱乐陪伴 | 已接受的播放、换播和结束指令 | 只有成功完成且老人明确点名的音乐、戏曲会影响下次泛播放；按点播次数优先、最近一次打破平局 |
| 社交活动 | 活动查询、确认参加、候补或报名截止后的意愿 | 仅在“今天有什么活动”“最近有什么活动”这类泛查询中，优先展示历史上确认参加意愿更多的活动或类别；已有活动登记表会与共享历史合并，并按活动场次去重；明确查询不重排 |
| 联系家人 | 已确认的联系意图及高层处理结果 | 供控制台跟进未完成联系；不自动选择联系人，不保存原始联系语句、联系人姓名、电话号码或最终拨号授权原话 |

## 状态含义

- `completed`：机器人已完成该需求的当前处理，例如成功记录活动参加意愿。
- `in_progress`：仍需要后续处理，例如护理工作人员跟进、真实通话请求已被接受或安全演示已通过授权。
- `cancelled`：老人取消确认或场景在确认前结束。
- `failed`：没有匹配授权联系人、准备失败或没有得到明确确认。

## 初始化或更新索引

现有数据库无需迁移。部署本次代码后执行一次以下命令即可确保偏好读取索引存在；它不会删除老人、需求或场景数据：

```bash
cd /home/user/github-product/g1-dex3-care-vla/speech
source venv/bin/activate
python init_elder_need_db.py
```

正常版活动和联系家人默认写共享需求库，可用 `--no-need-write` 临时关闭。比赛展示版活动默认只读，只有显式传入 `--record-elder-needs` 才会写入，避免演示录音污染正式历史。


## 护理异常的数据库交接

护理检测到 `URGENT_ASSISTANCE` 后，先在同一事务内保存两处记录，再播报结果：

| 表 | 对接字段 |
| --- | --- |
| `elder_need` | `need_category=care`、`need_code=care_urgent_assistance`、`priority=urgent`、`status=detected`、`source_scene=CARE_CONSULTATION_SUPPORT` |
| `care_assistance_request` | 同一护理 `session_id`、`risk_level=external_route`、`status=pending`，包含老人原话和紧急求助摘要 |

共享记录保留现有 `dedupe_key=care:{session_id}`，中风险升级时更新同一条需求并复用仍为 pending 的工作人员事项。
`details_json` 提供 `target_scene=URGENT_ASSISTANCE`、`urgent_assistance=true`、
`assistance_request_id`、`matched_risk`、`latest_raw_text` 及 `reported_user_context`（仅老人最近表达，不把机器人追问当作症状）。

平台应同时关注新增记录和已有记录的 `updated_at`/优先级升级；按共享需求 ID 去重。
平台负责后续推送、呼叫工作人员、联系家人及处理状态回写。
数据库提交仅表示待办已落库，`notification_status=unconfirmed`，不代表已推送、接单或到场。
护理语音结束不会完成或取消紧急待办，也不会覆盖平台已回写的状态。
异常播报先用“您先别着急，刚才说的情况我已经认真听到了”简短安抚，再按实际入库回执说明处理情况。
不承诺工作人员已收到、马上到场或老人肯定没事；当前场景没有持续监听，也不播报“一直陪着您”等无法兑现的承诺。
两处记录任一写入失败会全部回滚，控制台及录制日志明确失败，机器人提示现场联系工作人员，不声称提交成功。

正常模式会入库；`--showcase` 默认仍只模拟，避免把排练当成真实告警。
确需验证平台联动时增加 `--record-urgent-needs`：只单独开启紧急事项正式入库，
普通护理演示和长期记忆仍遵循原只读设置。演示说明仅输出控制台。
本模块不拨号、不运行机械动作、不改变机器人运动模式。
