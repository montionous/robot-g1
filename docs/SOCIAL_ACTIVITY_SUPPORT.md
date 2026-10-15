# 社交活动模块说明

## 导入范围与入口

目录为 `speech/scenarios/social_activity_support/`。本批导入 21 个 Python 文件，此前已导入 `run_g1_demo.sh` 和 `run_g1_showcase.sh`。所有业务逻辑保留原样。

| 入口 | 源码用途 |
| --- | --- |
| `g1_voice_demo.py` | 普通语音版，使用 `ActivityController` 与 `ActivityIntentLLM`，接入公共会话记录 |
| `g1_showcase_demo.py` | 展示语音版，使用 `ShowcaseController`、状态门禁、可选语义匹配与动作客户端 |
| `text_demo.py` | 普通文字入口，默认使用真实 SQLite |
| `text_showcase_demo.py` | 展示文字入口，默认真实 SQLite；`--demo-data` 使用源码提供的内存 `DemoRepo` |

`run_g1_demo.sh` 加载公共会话环境和云配置后启动普通版。`run_g1_showcase.sh` 先调用会写库的日程刷新脚本，再使用 `speech/venv/bin/python` 启动展示版，不是只读预检。

普通版记录会话、ASR 和软件回执；展示版未导入 `companion_recording`，本批未见同样的会话录制链。普通版的 `--record-mode replay` 仍只是公共日志模式元数据，不自动阻止场景执行。

展示版默认 `--robot-actions dry-run`，只控制动作客户端，语音链仍需要真实依赖。`--no-llm` 仅关闭展示语义模型，不关闭 ASR/TTS、数据库或机器人连接；`--state-timeout` 默认 0，表示不自动超时。

## 保留的视频参考文件

同目录还收到 `g1_showcase_demo_video_baseline.py`、`showcase_controller_video_baseline.py`、`showcase_intent_video_baseline.py`。它们按原路径保存，没有自动移动到归档目录。

视频语音文件实际仍导入不带后缀的当前 `showcase_controller` 和 `showcase_intent`，不能仅凭三个文件名把它们视为一套独立冻结、已复现的视频基线。用户尚未确认其现用或归档定位。

## 控制流程与两个版本的区别

展示版状态为查询、选择、详情、确认、等待结束、结束。它允许在相应状态查询和选择活动、询问时间/地点/名额/报名、复述信息和表达参加意愿；错序意图会被状态门禁忽略。

展示分类先使用本地规则及状态门禁，规则无法识别时才调用模型兜底。可选的 `ActivitySemanticMatcher`、`RecentActivityQueryResolver` 把自然语言映射到数据库中的真实活动，并查询近期场次和下一场可参加活动；这些云与 SQL 路径本轮没有执行。

普通版可对满员活动记录候补意愿、对超过报名时间的活动生成工作人员询问记录。展示版直接拒绝代码中标记为满员、关闭或取消的场次；免报名活动只提供参加指引，需要报名的活动经过确认后才写入意愿与通知记录。

参加记录不是最终报名确认。两版的工作人员通知在本批代码中是 SQLite `staff_notification` 记录，未见实际发送通知的后端；也未见把社交活动记录同步到公共 `elder_need` 的调用。

## 数据库和脚本分工

固定数据库路径为 `speech/data/elder_companion.db`。它是共享数据路径，不随已废弃的同名场景一起删除。

| 文件 | 实际行为 |
| --- | --- |
| `init_activity_db.py` | 创建 `data/` 目录、四张活动表和三个索引，不创建 `elderly_person` 老人基表 |
| `seed_demo_activities.py` | 初始化活动表后清空 `staff_notification`、`social_activity_interest`、`social_activity_session`、`social_activity` 的全部记录，再写入演示数据 |
| `refresh_activity_schedule.py` | 依赖已有活动定义，根据运行日期插入或更新场次；发现重复匹配场次会停止 |
| `ensure_future_activity_sessions.py` | 根据已有活动定义增补或更新未来场次，也会写库 |

刷新脚本不删除历史场次，但会更新已有场次的结束时间、容量、登记人数、报名截止时间、状态等字段，不能将它当成只读检查。只运行建表脚本也不会自动得到活动目录和有效场次。

`ActivityRepository` 负责活动/场次查询、参加意愿和工作人员通知。当前真实仓库路径的当天查询会按本机当前时间过滤已结束场次；内存 `DemoRepo` 不是完整 SQLite 行为的替代。日期使用 `date.today()` 和 `datetime.now()`，演示数据跟随运行日期，本轮没有修改时区或日程数据。

本轮未调用任何数据库初始化、种子或刷新函数，没有创建或上传数据库。

## 本轮验证结果

- 21 个 Python 文件通过 Python 3.10 语法解析，导入内容与附件一致，仅统一文本换行。
- 21 个模块真实导入成功，没有业务网络、数据库或子进程调用。
- `g1_voice_demo.py`、`g1_showcase_demo.py`、`text_showcase_demo.py` 的 `--help` 均成功加载并退出，未启动业务流程。
- 使用前批临时 `requests` 依赖，运行了原有内存演练：

```bash
python3 speech/scenarios/social_activity_support/text_showcase_demo.py --demo-data --scripted --no-llm
```

原脚本 12 轮输入运行到 `done`，退出码为 0，没有访问 SQLite、云模型、音频或机器人。查询、选择及部分详情问答有实际输出，但中途发生下述偏差，不能认定完整参加流程通过。

## 已复现的规则流程偏差

按原样例输入：

1. “明天下午有什么活动？”：`query`，推荐后进入 `wait_select`。
2. “我想了解一下集体唱歌。”：`select`，进入 `selected_activity`。
3. “这个活动听起来挺不错的。”：实际返回 `query`，重新推荐并退回 `wait_select`。

第 3 句在脚本注释和模型提示词中被定义为应忽略的背景描述。当前 `ACTIVITY_HINTS` 含泛词“活动”，而查询兜底条件同时检查包含该提示词及“活动”，导致这句描述命中查询。分类函数优先返回明确的本地规则结果，这条路径不会再由模型修正。

原样例后面的“我没记住，你再完整说一遍”和“那我去参加”因此在 `wait_select` 被门禁忽略；最后结束指令仍正常结束。该偏差也已用真实分类器、控制器和源码内置 `DemoRepo` 单独复现，未修改业务逻辑或样例。

尚未收到 `speech/test_social_activity_showcase.py`，本批没有执行社交活动自动断言套件。近期语义查询、真实 SQLite、报名确认/候补、工作人员通知送达、ASR/TTS、手臂动作及实机闭环均未验证。娱乐展示此前的 12 通过/3 失败结果保持独立，不因社交文字脚本退出成功而改变。
