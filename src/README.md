# SDK 核心与共享 G1 执行边界

> **状态：基础技术参考。** 当前老人陪伴情绪 V1 不使用本目录的 G1/DDS 执行链；只有未来经 Boss 明确启用 G1 互动接入时，才按这里的安全 owner 复用，不能启动旧服药策略。

当前实现包含 SDK 只读状态监视器、历史受限音频 runtime、版本化 24D Observation/Action/Execution/Episode、连续 supervisor/loop、功能型 24D Unitree adapter、production SDK/DDS transport/composition、runtime codec 和 EpisodeV2 bridge。功能型组合 24D 与 Quest→G1 bounded smoke 已有实机证据；正式连续遥操由仓库外官方 `xr_teleoperate/teleop/teleop_hand_and_arm.py` 拥有。Pi0.5 policy runtime 已有离线/只读输入回归，但 checkpoint、推理和相机尚未部署到 G1 本地侧，也没有 policy 实机任务资格。

源码工作的优先级由比赛演示决定：只修改阻断下一次 G1 本地任务的 owner。fake runtime、更多 Gate、离线测试或数据质量改进不能独立关闭阶段；模型与训练代码禁止直接访问 DDS。

## 文件说明与通信位置

先按通信方向理解代码，而不是按文件名猜测职责：

```text
G1 持续发布 LowState ─→ g1_state_monitor_main ─→ MonitorCore ─→ JSONL/报告
stdin JSONL ─→ CommandRuntimeCore ─→ Audio adapter ─→ G1 AudioClient
G1 rt/audio_msg ─→ PlaybackObserver ─→ runtime JSONL 对账
护理事件/人工确认 ─→ CareTaskCore ─→ 任务快照（完全离线）
Gate 6 右手 hand_state.jsonl ─→ g1_dex3_log_replay ─→ fake 对账 JSONL
G1 rt/dex3/right/state ─→ Gate 9B readonly adapter ─→ readonly diagnostic core ─→ JSONL episode
G1 RobotState ServiceList ─→ Gate 9B readonly adapter ─→ 原始服务状态 JSONL event
G1 rt/dex3/right/state ─→ Gate 10 state callback ─→ source_q / JSONL evidence
source_q ─→ g1_dex3_command_core 两段固定计划 ─→ HandCmd_ publisher ─→ G1 Dex3 bridge
G1 rt/dex3/right/state ─→ Gate 10 JSONL readback（第一段与最终 post）
historical teleop / policy frame ─→ g1_sdk_contract_runtime_core ─→ fake RobotCommandPort ─→ EpisodeV1 JSON
RobotCapabilityProfile JSON ─→ g1_robot_capability_profile_core ─→ fake RobotCommandPort preflight（partial 拒绝）
G1 LowState + left/right Dex3 state ─→ g1_upper_body_observation_core ─→ 24D 只读 JSONL（无 action/writer）
Quest/Policy mapped 24D Action ─→ g1_upper_body_execution_core ─→ fake port ─→ mapped/sent/result/observation episode
24D runtime final command ─→ g1_upper_body_unitree_adapter_core ─→ 功能 capability/14 路限位/完整 packet
完整 24D packet ─→ g1_upper_body_unitree_transport_core ─→ g1_upper_body_unitree_sdk_io ─→ 三路固定 DDS publisher
g1_upper_body_runtime ─→ confirmation-gated hold / functional / Quest / policy shared composition
```

| 文件 | 文件做什么、输入 → 输出 | owner / 通信边界 | 相关测试或运行入口 |
|---|---|---|---|
| `g1_state_monitor.hpp` | 定义 `StateSample`、快照、事件和 `MonitorCore` 合同。输入是投影后的 LowState，输出是统计与事件。 | 实体状态语义 owner；不含 SDK/DDS。 | `g1_state_monitor_test` |
| `g1_state_monitor.cpp` | 校验浮点值、计算频率、识别模式变化/断流。 | 纯本地核心，不发送命令。 | `g1_state_monitor_test` |
| `g1_state_monitor_main.cpp` | 订阅 `rt/lowstate`，把官方消息投影给核心，再打印 JSONL。 | 唯一 LowState DDS adapter；只读。 | `g1_state_monitor` |
| `g1_intent.hpp` | 定义两条冻结 Intent、解析结果、请求门禁和 adapter 抽象。 | 命令语义 owner；不含 SDK/DDS。 | `g1_intent_test` |
| `g1_intent.cpp` | JSON/中文输入 → Intent/错误码；执行 adapter 后得到 RPC 结果。 | 不决定网卡、topic 或 SDK 生命周期。 | `g1_intent_test` |
| `g1_intent_cli.cpp` | 一条结构化 Intent → 官方 AudioClient 一次调用 → JSON 输出。 | Gate 5C 一次性 SDK adapter。 | 实机 Gate 5C |
| `g1_chinese_command_cli.cpp` | 中文短句 → canonical Intent JSON。 | 完全离线，不初始化 SDK。 | 本地命令演示 |
| `g1_command_runtime.hpp` | 定义多行 JSONL 的请求缓存与结果合同。 | request ID 重放/冲突 owner。 | `g1_command_runtime_test` |
| `g1_command_runtime.cpp` | JSONL 请求 → 解析 → 门禁 → adapter → 有界缓存结果。 | 不持有 AudioClient、DDS 或线程。 | `g1_command_runtime_test` |
| `g1_runtime.hpp` | 定义播放周期、JSON 渲染和 SDK session 的可 fake 接口。 | runtime 通用基础设施 owner。 | `g1_runtime_test` |
| `g1_runtime.cpp` | 折叠 `play_state`、限制输入行、渲染输出、固定关闭顺序。 | 不直接订阅 DDS；消费 adapter 观测。 | `g1_runtime_test`、`g1_runtime_demo` |
| `g1_sdk_contract_runtime.hpp/.cpp` | 定义右手 V1 Observation/Action/ExecutionResult/Episode，执行 schema、deadman、时效、顺序与 preflight gate，并严格序列化/解析 episode。 | SDK-R2 唯一 fake/replay owner；SDK-R3 测试覆盖 fake device → runtime → fake port、recorded JSONL → fresh runtime replay，也验证 partial profile gate 会在 writer 前阻断；不含文件 I/O、Unitree SDK、DDS 或真实 writer。 | `g1_sdk_contract_runtime_test` |
| `g1_robot_capability_profile.hpp/.cpp` | 解析 capability profile 并查询 verified/partial/unknown。 | SDK-R1 能力事实 owner；由 SDK-R3 fake preflight 消费；不含文件 I/O、Unitree SDK、DDS 或动作语义。 | `g1_robot_capability_profile_test`、`g1_sdk_contract_runtime_test` |
| `g1_upper_body_observation.hpp/.cpp` | 定义 24D layout、有限值与三路 source age/skew gate。 | `upper_body_24d_v1` 只读 observation owner；不含 SDK/DDS/action/execution 语义。 | `g1_upper_body_observation_core` |
| `g1_upper_body_observation_main.cpp` | 订阅 LowState 与左右 Dex3 state，投影为有界 24D JSONL。 | 唯一 24D DDS 只读 adapter；无 publisher/RPC/ServiceSwitch。 | `g1_upper_body_observation_invalid_cli` + 实机检查点 |
| `g1_upper_body_execution.hpp/.cpp` | 定义 24D Action、ExecutionResult、同步 runtime、final sent action 与 in-memory episode。 | 24D 离线执行 owner；只暴露 RobotCommandPort 接口，不含 Unitree/DDS、Quest 字段、文件 I/O 或真实 writer。 | `g1_upper_body_execution_core` |
| `g1_upper_body_unitree_adapter.hpp/.cpp` | 消费完整 24D command，执行双臂/双手功能 capability、profile、模式、14 路手指限位和 Unitree packet 映射。 | 真实 RobotAdapter core；两侧 `thumb_0=partial` 不阻断功能动作；不初始化 DDS，不拥有 Quest/episode，不实现 channel/service 生命周期。 | `g1_upper_body_unitree_adapter_core` |
| `g1_upper_body_unitree_transport.hpp/.cpp` | 执行 factory/subscriber/service/publisher 生命周期、100 次 source adoption、三路 writer 聚合、100 次 arm release 和幂等 close。 | production transport 生命周期 owner；不拥有 capability、Quest、episode/profile 或设备映射。 | `g1_upper_body_unitree_transport_core` |
| `g1_upper_body_unitree_sdk_io.hpp/.cpp` | 固定 Domain 0、`enp3s0`、四路状态 source、三个命令 topic 与 `g1_arm_example` close/restore。 | Unitree SDK/DDS 薄接线；官方 SDK header 只进入该 production I/O 层。 | 全量构建；历史 current-pose smoke 已通过 |
| `g1_upper_body_runtime_main.cpp` | 解析 actual capability profile，组装 supervisor/runtime/adapter/transport，并按精确模式接收 hold、functional、Quest 或 policy Action。 | 唯一 production composition；confirmation 在 SDK 对象构造前校验，Policy/Quest 仍只能提交版本化 24D JSONL，不能直写 DDS。 | no-confirm 回归 + 已有 hold/functional/Quest 实机证据；policy 待 G1 本地实机验收 |
| `g1_sdk_runtime_main.cpp` | 初始化 DDS/AudioClient；命令发送后观察 `rt/audio_msg` 并输出 JSONL。 | Gate 5F 唯一连续实机 adapter；只允许两条冻结命令。 | `g1_command_runtime_cli` |
| `g1_official_asr.hpp/.cpp` | 严格解析 `rt/audio_msg` 的官方 ASR、非最终片段和播放状态 JSON。 | 外部音频消息合同 owner；无 SDK、DDS、TTS 或动作依赖。 | `g1_official_asr_core` |
| `g1_tts_probe.cpp` | PC2 本机固定短句 -> 一次 `TtsMaker` -> `play_state=1 -> 0` JSON。 | 一次性官方 TTS 实机 probe；无自由文本、音量、LED、麦克风模式、publisher、VLA 或动作接口。 | 本地构建 + PC2 实机固定播报 |
| `g1_voice_wake_mode.cpp` | 确认后请求 `voice` API 1008 `mode=1`，打开唤醒/麦克风；1007 回读。 | 一次性语音模式 probe；官方遥控器路径仍是 `L1+L2`。无 TTS、音量、LED、publisher、关节。 | `g1_voice_wake_mode` dry-run / 缺确认 64；实机须 `--confirm-g1-voice-wake-mode` |
| `g1_tts_phrase.hpp` / `g1_tts_phrase_bridge.cpp` | 11 个固定 phrase ID -> 固定中文短句 -> 一次 `TtsMaker` -> 播放周期 JSON。 | ASR 闭环唯一 TTS 文本 owner；未知 ID 在 SDK 初始化前拒绝，无自由文本、VLA 或动作接口。 | `g1_tts_phrase_core` + PC2 两轮人工实机验收 |
| `g1_companion_tts_phrase.hpp` / `g1_companion_tts_phrase_bridge.cpp` | 3 个陪伴赛道固定 `phrase_id` -> 固定中文短句 -> 一次 `TtsMaker` -> `play_state=1 -> 0` JSON。 | 当前情绪互动的独立 TTS owner；固定 `Domain 0 / enp3s0 / rt/audio_msg`，`--dry-run` 不初始化 SDK，实际播放必须精确确认参数，单条播放回读上界 10 秒；无自由文本、策略、VLA 或动作接口。 | `g1_companion_tts_phrase_core` + dry-run；实机播放待独立验证 |
| `g1_companion_pcm.hpp` / `g1_companion_pcm_bridge.cpp` | 本机服务 WAV -> 严格 PCM 16 kHz/单声道/16 位/15 秒校验 -> 官方 `PlayStream` + `PlayStop` JSON。 | 当前陪伴赛道 G1 扬声器 adapter；固定 `Domain 0 / enp3s0`，实际播放必须精确确认参数；不拥有 TTS、策略、模型或动作接口。 | `g1_companion_pcm_core` + dry-run；实机播放待验证 |
| `g1_care_task.hpp` | 定义护理任务、事件和结果的数据合同。 | 离线任务状态 owner；不含机器人接口。 | `g1_care_task_test` |
| `g1_care_task.cpp` | 任务创建/版本/事件重放 → 当前任务快照。 | 不发布命令，也不把播放观察当作物理完成。 | `g1_care_task_test` |
| `g1_dex3_state_monitor_main.cpp` | 订阅左右 `HandState_` → 每条回调 JSONL 原始记录 → 60 秒汇总。 | Gate 6 Dex3 只读 adapter；不含 `HandCmd_` 或 publisher。 | `g1_dex3_state_monitor` |
| `g1_dex3_command_core.hpp/.cpp` | 右手 7 个 `q` 与两路错误码 → 同位置请求 / 固定协同目标 / Gate 10 两段返回计划 → fake 对账/有界写入。 | Gate 7--10 命令语义 owner；不含 SDK、DDS 或 `HandCmd_`。 | `g1_dex3_command_core_test` |
| `g1_dex3_log_replay.hpp/.cpp` | Gate 6 右手 JSONL → 严格状态投影 → fake 对账 JSONL。 | Gate 7 只读日志回放 owner；不含 SDK、DDS 或实机写入。 | `g1_dex3_log_replay_test` |
| `g1_dex3_log_replay_main.cpp` | stdin JSONL → stdout JSONL。 | 离线 CLI adapter；用于 `tee` 保存回放结果。 | `g1_dex3_log_replay` |
| `g1_dex3_episode_log.hpp/.cpp` | 新目录 → `episode.jsonl` 逐行事件 + `summary.json`。 | Gate 7 实机 episode 文件 owner；不含 DDS/动作语义。 | `g1_dex3_episode_log_test` |
| `g1_dex3_right_hold_main.cpp` | 新鲜右手状态 → 固定 profile（保持、单关节、协同或 Gate 10 两段）→ 有界写入 → 全量状态/命令 episode + 状态回读。 | Gate 7--10 唯一实机 `HandCmd_` adapter；每种编译目标都有精确确认参数、固定右手 topic。 | `g1_dex3_command_core_test`、`g1_dex3_episode_log_test` + Gate 7--10 报告 |
| `g1_dex3_readonly_diagnostic.hpp/.cpp` | 已投影的右手状态 / ServiceList 原始字段 → 有界 JSONL state/service event。非有限浮点写 `null`，样本最多 6,000、服务最多 128、服务名最多 256 字节。 | Gate 9B JSONL 投影 owner；不含 SDK、DDS、`HandCmd_` 或写接口。 | `g1_dex3_readonly_diagnostic_test` |
| `g1_dex3_right_readonly_diagnostic_main.cpp` | 固定 direct `HandState_` 三秒 + 一次 ServiceList → 独立 episode。 | Gate 9B 唯一 SDK read-only adapter；只接受精确确认参数，未确认时 64 退出；不包含 publisher、服务开关或配置写入。 | `g1_dex3_right_readonly_diagnostic_no_confirm` + 后续独立实机 Gate |

每个头文件和主要实现区块均已加入中文注释：先读 `*.hpp` 了解 owner 和数据合同，再读同名 `*.cpp` 了解执行顺序，最后读 `*_main.cpp` 了解官方 SDK 如何接线。

该 collector 的唯一职责：

1. 订阅实机确认的状态 topic，显示消息摘要、频率、模式和接收年龄；
2. 根据消息生成首次接收、状态变化和断流等应用侧事件；
3. 将有界摘要写入可追溯报告；
4. 保证进程中不存在 publisher 或动作 RPC 调用。

`g1_state_monitor.cpp/.hpp` 拥有状态统计和事件语义；`g1_state_monitor_main.cpp` 只负责 HG `LowState_` 投影、SDK 接线与 JSONL 输出。ROS 2 adapter 在 SDK 直连状态链路通过后单独建立。

`g1_intent.cpp/.hpp` 拥有冻结意图和请求门禁；`g1_command_runtime.cpp/.hpp` 拥有重放、冲突和速率语义；`g1_runtime.cpp/.hpp` 拥有 JSONL 输出、播放周期与关闭顺序；`g1_sdk_runtime_main.cpp` 只接线官方 `AudioClient` 和 `rt/audio_msg`。`g1_command_runtime_cli` 已完成实机验收，仍只允许“查询音量”和“播报连接成功”。

`g1_care_task.cpp/.hpp` 不复用或扩展 SDK runtime；它只处理离线任务事件。任务 `completed` 表示收到人工确认，绝不推断实际服药。播放观测固定标记为 `unverified`，不能作为任务完成条件。

`g1_dex3_command_core.cpp/.hpp` 只确认“右手状态正常且位置均为有限数”时才生成同位置请求，并在 fake 端口中完成一次发送和严格回读对账。它还编码官方 Dex3 旋转示例的低增益 profile：`mode=0x90+index`、`dq/tau=0`、`kp=0.5`、`kd=0.1`；核心本身不连接 SDK 或 DDS。

`g1_dex3_log_replay` 只读取 Gate 6 的右手 `dex3_hand_state` JSONL。它拒绝非右手、非 7 电机、错误格式、`finite=false`、非有限位置和超长行；成功结果固定标记 `readback_source=input_snapshot_fake`。它从不连接或控制 G1/Dex3。

`g1_dex3_readonly_diagnostic.cpp/.hpp` 只拥有 Gate 9B 的**记录语义**：把 `HandState_` 已投影字段写成带 schema 的 JSONL，并把不可表示为标准 JSON 的非有限浮点变为 `null` + `finite=false`。它不根据 `reserve[]`、服务 `status/protect` 或位置变化宣称电机健康。`g1_dex3_right_readonly_diagnostic_main.cpp` 才接线 SDK：固定 direct right state 三秒、最多 6,000 条，并调用一次 `ServiceList`；在确认参数前退出，且没有 `HandCmd_` 或 publisher。

`g1_dex3_right_hold_main.cpp` 的 Gate 10 编译目标是一个两段**有限** adapter：callback 从
`rt/dex3/right/state` 取得 source；core 先编码固定协同 target，再编码逐项等于 source 的返回
target；adapter 为每次写入记录 `sequence_step`、attempt/result，并以直接状态作为物理证据。`writer_completed`
只说明本机 DDS 写入循环结束，最终 q 未回到 source 时不能写成物理返回成功。详细运行证据见
[`Gate 10 报告`](../reports/gate10_right_whole_hand_extension_return_20260720.md)。

Gate 7 回放（仅离线；输入文件必须是此前保存的 Gate 6 原始日志）：

```bash
/tmp/g1-gate7-build/g1_dex3_log_replay < /path/to/hand_state.jsonl | tee /tmp/g1-dex3-replay.jsonl
```

Gate 7A 首次右手保持（实机；只在 G1 已开机、吊架保护并进入调试模式后执行）：

```bash
d=/tmp/g1-dex3-gate7a-$(date +%Y%m%d-%H%M%S); mkdir -p "$d"; /tmp/g1-gate7-build/g1_dex3_right_hold --confirm-right-hold --log-dir "$d" | tee "$d/terminal.jsonl"; echo "$d"
```

构建和运行：

```bash
cmake -S . -B /tmp/g1-monitor-build \
  -DUNITREE_SDK2_ROOT=/home/user/github-product/unitree_sdk2
cmake --build /tmp/g1-monitor-build -j2
/tmp/g1-monitor-build/g1_state_monitor \
  --duration 60 --display-ms 1000 --timeout-ms 100
```

Gate 5F 历史本地 fixture（不连接 G1，不是当前比赛入口）：

```bash
cmake --build /tmp/g1-gate5f-build -j2
/tmp/g1-gate5f-build/g1_runtime_demo
```
