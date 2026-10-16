# G1 动作执行器与视觉情绪联调材料

## 本批来源与范围

本批从用户提供的源码包原样导入 9 个项目根 `scripts/` 文件：

- `g1_elder_companion_motion_executor.py`
- `g1_elder_companion_custom_action_executor.py`
- `g1_elder_companion_emotion_demo.py`
- `g1_elder_companion_emotion_preflight.sh`
- `g1_elder_companion_emotion_camera_dialogue_motion_run.sh`
- `g1_elder_companion_emotion_camera_dialogue_run.sh`
- `g1_elder_companion_emotion_camera_tts_opt_run.sh`
- `g1_elder_companion_emotion_camera_tts_run.sh`
- `g1_elder_companion_emotion_video_tts_run.sh`

导入保持原有文件名、参数和程序逻辑。本说明只记录静态调用关系与运行边界，不把源码存在等同于机器人已连接、动作已执行或现场效果已验收。

## 当前动作客户端使用的两个执行器

`speech/robot_actions/action_client.py` 固定定位下表两个脚本，并且只有在 `--robot-actions execute` 与对应的写入确认同时启用时才启动子进程；默认 `dry-run` 只构造请求，不加载 SDK、不启动执行器。

| 脚本 | 接受的已确认请求 | 动作边界 |
| --- | --- | --- |
| `g1_elder_companion_motion_executor.py` | `emotion_dialogue_motion_request`，动作 ID 仅 17（鼓掌）或 25（挥手） | 实际路径会初始化 DDS、调用 `G1ArmActionClient`，并可能向 `rt/dex3/*/cmd` 写入手部命令。任何动作源都要求 `--confirm-g1-companion-motion-executor`。 |
| `g1_elder_companion_custom_action_executor.py` | `emotion_dialogue_custom_action_request`，动作名仅 `open_palm_invite` | 实际路径会注册并调用自定义动作 API 7108，复用相邻 motion 执行器的 Dex3 手指控制。要求 `--from-stdin` 和 `--confirm-g1-companion-listen-invite-executor`。 |

客户端将 `greeting`、`goodbye`、`celebrate` 映射到 motion 执行器，将 `present`、`acknowledge` 映射到 custom 执行器。当前有直接调用证据的入口是娱乐普通版、娱乐展示版和社交活动展示版；照护咨询、联系家属和社交普通版没有 `RobotActionClient` 引用。

动作客户端默认使用原机器的 `/home/user/miniconda3/envs/tv/bin/python` 与 `enp3s0`。可通过 `G1_ACTION_PYTHON` 和 `G1_ACTION_INTERFACE` 覆盖；这只是源码参数约定，不代表替换后的环境已经兼容。

## 未接入四个场景的历史视觉情绪材料

`g1_elder_companion_emotion_demo.py` 和六个同前缀 Shell 脚本是独立的视觉情绪/实机联调材料。当前四个场景和 `RobotActionClient` 都没有直接引用它们；原 `speech/README.md` 仅保留 `emotion_demo.py` 与 `emotion_preflight.sh` 的手工示例。因此它们不属于默认启动路径，也不因前缀与已废弃场景相同而被删除。

视觉 demo 需要 OpenCV、NumPy、MediaPipe、模型文件以及相机或视频输入；按显式选项可写相机录像、标注视频或 dashboard JSONL。两个 dialogue wrapper 还串接 wake-mode、麦克风、云配置、护理工作台、本地对话服务、PCM bridge 与上述动作执行器。`emotion_preflight.sh` 会构建和测试 bridge。bridge 的主程序和上游构建清单现已收到，但仍缺其直接头文件、核心测试和完整 C++ 工程，因此该预检当前仍不可执行；原路径中的 `vedio/happy_1.mp4` 拼写也按源码保留。

## 本轮检查与未执行内容

归档在解压前通过成员路径和链接类型检查。三个 Python 文件通过 AST 语法解析，六个 Shell 文件通过 `bash -n`，导入后逐文件与附件对照。静态扫描没有发现凭据、私钥或令牌字面量。

没有导入或运行任何执行器、`--help`、`--inspect`、`--dry-run` 或 wrapper。特别是 motion 的 `--inspect` 也会初始化 DDS 订阅，不能作为离线检查。本轮没有初始化 Unitree SDK、访问 DDS、打开相机、访问云服务、启动护理工作台、调用 PCM bridge 或发送 G1/Dex3 命令。

真实使用前仍需要在机器人现场单独核对 SDK 版本、DDS 网卡、模式与站姿、动作范围、互斥控制和恢复条件，并遵守 [上游项目规则快照](upstream-project-rules.md) 中每次动作前的明确确认要求。
