# G1 养老照护机器人：语音与日常陪伴

本仓库整理 `g1-dex3-care-vla` 项目中以 `speech/` 为主、并包含其依赖 `care_console/` 的源码，覆盖照护咨询、娱乐陪伴、社交活动和联系家属四个场景。各场景的比赛展示版与完整版正在分别梳理。

**当前为分批导入阶段，还不能在新机器上独立运行。** 已导入公共语音源码、云 ASR/TTS、G1 音频组件、共享需求/播报/会话记录、动作客户端、四场景启动脚本和主体代码，以及已收到的数据清单与测试。电话 Shell 入口、编排器、Android HTTP client、共享老人/家属基表初始化源码、动作执行器源码、PCM bridge 的主程序、相邻头文件和核心测试源码，以及护理工作台的源码、静态页、测试和独立运行时依赖清单已收到；根 CMake 的其余 C++ 工程、Unitree SDK 与实机运行配置仍未验证。初始化源码只含电话占位符的比赛示例，生成的数据库不纳入仓库。

历史视觉情绪互动链的逻辑与测试已保存，但它直接依赖已废弃且未迁移的 `elder_companion` 模块，不属于四个现用场景的入口。依赖、动作边界和验证限制见[历史视觉情绪互动链说明](docs/EMOTION_MODULE.md)。

```text
speech/
├── server.py          # HTTP 语音服务：健康检查、TTS、ASR、音频下载
├── speech_client.py   # HTTP 客户端及 G1 录音、播放接口
├── speech/            # 云 ASR/TTS、预设、包客户端与直接语音接口
├── g1_audio/          # G1 录音、滚动识别、播放及娱乐打断
├── emotion_interaction.py # 历史情绪策略到语音互动
├── emotion_dialogue.py    # 历史多轮情绪对话（依赖未迁移模块）
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

care_console/
├── link.py            # 场景启动前登记本轮交互日志
├── server.py          # 本地护理工作台 HTTP 应用
├── static/            # 工作台静态页面
├── test_*.py          # 原有 Python 测试
└── deploy/requirements.txt

scripts/
├── g1_elder_companion_motion_executor.py        # G1/Dex3 动作执行器
├── g1_elder_companion_custom_action_executor.py # 自定义邀请动作执行器
└── g1_elder_companion_emotion_*                  # 历史视觉情绪联调材料

CMakeLists.txt                                    # 上游完整机器人项目的构建清单快照
src/g1_companion_pcm_bridge.cpp                   # PCM bridge 主程序
src/g1_companion_pcm.hpp                          # WAV 解析与分块播放核心
tests/g1_companion_pcm_test.cpp                   # PCM 核心测试源码
tests/assert_exit_64.cmake                        # bridge 缺确认参数的 CTest 辅助脚本
```

迁移状态、缺失依赖、场景入口和机器专用路径见 [语音模块迁移记录](docs/SPEECH_MIGRATION.md)。PCM bridge 的现有代码、缺口和调用契约见 [G1 PCM bridge 说明](docs/PCM_BRIDGE.md)。动作执行器的调用边界、历史情绪材料和验证限制见 [G1 动作执行器说明](docs/ROBOT_ACTIONS.md)。护理工作台的边界、日志登记和验证状态见 [护理工作台模块说明](docs/CARE_CONSOLE.md)。原项目规则保存为 [上游项目规则快照](docs/upstream-project-rules.md)，其中包含原项目的历史模块和设备约定。

照护咨询通过同一个 `g1_voice_demo.py` 的 `--showcase` 参数切换展示行为，入口、数据库边界和验证结果见 [照护咨询模块说明](docs/CARE_CONSULTATION.md)。展示模式仍会使用云模型并保存咨询消息。

娱乐陪伴有独立的 `g1_voice_demo.py` 和 `g1_showcase_demo.py`。当前主链扫描实际媒体目录，JSON 清单属于另一条内容实现；版本差异、播放依赖和文字演练结果见 [娱乐陪伴模块说明](docs/COMPANION_ENTERTAINMENT.md)。

社交活动也有独立的普通版与展示版，提供内存文字演练模式。入口、数据库脚本和展示版分类边界见 [社交活动模块说明](docs/SOCIAL_ACTIVITY_SUPPORT.md)。

联系家属当前语音入口默认使用 `safe_stub` 模拟拨号；真实拨号需要联系人绑定与最终明确授权。文字模拟、主机语音演示、旧网页通话路径及导入检查的区别见 [联系家属模块说明](docs/CONTACT_FAMILY.md)。模拟拨号仍不等于整个语音场景离线运行。

用户已确认 `elder_companion`、`caregiver_chat`、`short_companion_chat` 三个场景废弃，本仓库当前未导入这三个场景目录。共享客户端、回复模板及兼容接口按调用证据记录状态，保留原路径。

导入保留原目录和程序逻辑，仅统一文本换行及文件末尾换行；Shell 启动脚本保留可执行权限。已有启动脚本仍包含原电脑的绝对路径、虚拟环境和本地配置约定，需完成依赖梳理后再调整。

目前已通过文件一致性、Python/Shell 语法、JSON 检查，以及相关模块加载和娱乐两个语音入口的 `--help` 检查。娱乐展示的原有 15 项测试已执行：12 项通过、3 项分类断言失败，差异与状态机拒绝结果已记录。已收到的 PCM bridge 源码只完成静态审查；根工程仍不具备构建条件。媒体、照护演示数据库及动作执行器的 SDK/设备配置仍未完成，完整实机功能未验收；机器人端的现有项目仍是实机验证基线。

社交活动的 21 个模块导入和三个入口的 `--help` 检查通过。展示版曾把“这个活动听起来挺不错的”这类背景描述误判为查询；现在只在存在明确提问信号时把具体活动名称作为查询，并加入离线回归测试。数据库初始化、种子和日程刷新均未执行。

联系家属的 10 个模块导入和三个入口的 `--help` 检查通过；`test_db.py` 导入会查询并打印完整联系人，已跳过运行。未启动模拟通话服务、访问真实老人数据库或发起拨号。共享基表初始化脚本只在临时 SQLite 中验证过幂等建表、联系人查询、通话日志读写和外键，没有在仓库生成数据库文件。

补齐电话 Shell 入口和编排器后，联系家属的离线后端与授权测试覆盖模拟和 real-client 参数接线。真实后端测试均未访问手机；`real` 直连路径现在会把未创建的目录交给 Android client 原子创建，避免重复创建输出目录，详见联系家属说明。

护理工作台源码现已入库，但没有启动 HTTP 服务、创建工作台数据库或接入真实交互日志。`care_console.link` 只允许连接本机控制台；该控制台未就绪时，四个普通 G1 场景的启动脚本会在进入语音入口前停止。

密钥保存在本机配置中。录音、日志、数据库、虚拟环境、护理工作台运行目录和备份不作为本次源码导入内容。娱乐素材和测试数据后续按用途单独整理。
