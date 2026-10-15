# G1 养老照护机器人：语音与日常陪伴

本仓库整理 `g1-dex3-care-vla` 项目中的 `speech/` 模块，覆盖照护咨询、娱乐陪伴、社交活动和联系家属四个场景。各场景的比赛展示版与完整版正在分别梳理。

**当前为分批导入阶段，还不能在新机器上独立运行。** 已导入收到的公共语音源码、云 ASR/TTS 实现、G1 音频组件、会话配置脚本、原有文档和启动脚本；四场景主体、照护控制台依赖及 PCM bridge 构建来源尚未收齐。

```text
speech/
├── server.py          # HTTP 语音服务：健康检查、TTS、ASR、音频下载
├── speech_client.py   # HTTP 客户端及 G1 录音、播放接口
├── speech/            # 云 ASR/TTS、预设、包客户端与直接语音接口
├── g1_audio/          # G1 录音、滚动识别、播放及娱乐打断
├── companion_recording_env.sh
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

用户已确认 `elder_companion`、`caregiver_chat`、`short_companion_chat` 三个场景废弃，本仓库当前未导入这三个场景目录。共享客户端、回复模板及兼容接口按调用证据记录状态，保留原路径。

导入保留原目录和程序逻辑，仅统一文本换行及文件末尾换行；Shell 启动脚本保留可执行权限。已有启动脚本仍包含原电脑的绝对路径、虚拟环境和本地配置约定，需完成依赖梳理后再调整。

目前验证范围是文件一致性、Python 语法和 Shell 语法；尚未验证云服务或机器人运行。机器人端的现有项目仍是实机验证基线。

密钥保存在本机配置中。录音、日志、数据库、虚拟环境和备份不作为本次源码导入内容。娱乐素材和测试数据后续按用途单独整理。
