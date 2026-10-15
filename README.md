# G1 养老照护机器人：语音与日常陪伴

本仓库整理 `g1-dex3-care-vla` 项目中的 `speech/` 模块，覆盖照护咨询、娱乐陪伴、社交活动和联系家属四个场景。各场景的比赛展示版与完整版正在分别梳理。

**当前为分批导入阶段，还不能在新机器上独立运行。** 已导入公共语音源码、云 ASR/TTS、G1 音频组件、共享需求/播报/会话记录、动作客户端、四场景启动脚本，以及照护咨询、娱乐陪伴和社交活动的主体代码及已收到的数据清单与测试。联系家属主体、本地媒体、老人基表与匿名演示数据、照护控制台、动作执行器及 PCM bridge 构建来源尚未收齐。

```text
speech/
├── server.py          # HTTP 语音服务：健康检查、TTS、ASR、音频下载
├── speech_client.py   # HTTP 客户端及 G1 录音、播放接口
├── speech/            # 云 ASR/TTS、预设、包客户端与直接语音接口
├── g1_audio/          # G1 录音、滚动识别、播放及娱乐打断
├── companion_recording_env.sh
├── companion_recording.py  # 有界会话记录
├── decision_announcer.py   # 可选决策播报
├── elder_need_registry.py  # 共享需求登记
├── init_elder_need_db.py
├── robot_actions/      # 动作请求及外部执行器客户端
├── scenarios/
│   ├── care_consultation_support/
│   ├── companion_entertainment/
│   ├── social_activity_support/
│   └── contact_family/
├── run_server.sh
├── requirements.txt
├── README.md          # 原项目说明，含早期使用方式
└── TEAM_USAGE.md      # 原团队接口说明
```

迁移状态、缺失依赖、场景入口和机器专用路径见 [语音模块迁移记录](docs/SPEECH_MIGRATION.md)。原项目规则保存为 [上游项目规则快照](docs/upstream-project-rules.md)，其中包含原项目的历史模块和设备约定。

照护咨询通过同一个 `g1_voice_demo.py` 的 `--showcase` 参数切换展示行为，入口、数据库边界和验证结果见 [照护咨询模块说明](docs/CARE_CONSULTATION.md)。展示模式仍会使用云模型并保存咨询消息。

娱乐陪伴有独立的 `g1_voice_demo.py` 和 `g1_showcase_demo.py`。当前主链扫描实际媒体目录，JSON 清单属于另一条内容实现；版本差异、播放依赖和文字演练结果见 [娱乐陪伴模块说明](docs/COMPANION_ENTERTAINMENT.md)。

社交活动也有独立的普通版与展示版，提供内存文字演练模式。入口、数据库脚本和已复现的背景描述误分类问题见 [社交活动模块说明](docs/SOCIAL_ACTIVITY_SUPPORT.md)。

用户已确认 `elder_companion`、`caregiver_chat`、`short_companion_chat` 三个场景废弃，本仓库当前未导入这三个场景目录。共享客户端、回复模板及兼容接口按调用证据记录状态，保留原路径。

导入保留原目录和程序逻辑，仅统一文本换行及文件末尾换行；Shell 启动脚本保留可执行权限。已有启动脚本仍包含原电脑的绝对路径、虚拟环境和本地配置约定，需完成依赖梳理后再调整。

目前已通过文件一致性、Python/Shell 语法、JSON 检查，以及相关模块加载和娱乐两个语音入口的 `--help` 检查。娱乐展示的原有 15 项测试已执行：12 项通过、3 项分类断言失败，差异与状态机拒绝结果已记录。媒体、照护演示数据库及执行器仍缺失，完整实机功能未验收；机器人端的现有项目仍是实机验证基线。

社交活动的 21 个模块导入和三个入口的 `--help` 检查通过。原有内存脚本的 12 轮样例运行到结束，但背景描述触发了重新查询，后续复述/参加被忽略，未认定完整参加流程通过。数据库初始化、种子和日程刷新均未执行。

密钥保存在本机配置中。录音、日志、数据库、虚拟环境和备份不作为本次源码导入内容。娱乐素材和测试数据后续按用途单独整理。
