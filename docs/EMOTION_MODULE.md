# 历史视觉情绪互动链

## 范围与状态

本仓库已保存以下历史独立联调链的七个 Python 文件：

- `speech/emotion_interaction.py`、`speech/emotion_dialogue.py`
- `speech/test_emotion_interaction.py`、`speech/test_emotion_dialogue.py`
- `speech/test_entertainment_interrupt.py`
- `tests/g1_elder_companion_emotion_tts_run_test.py`
- `tests/g1_elder_companion_emotion_tts_opt_run_test.py`

用户已确认 `elder_companion` 是废弃场景。即使这些文件仍直接引用该目录，它们也只作为未接入四个现用场景的历史视觉情绪/实机联调材料保存，不能视为当前默认入口，也不会因此重新导入废弃场景。

同一归档中的 `scripts/README.md` 和 `docs/16-老人陪伴赛道情绪模块真源.md` 未原样推送：其中包含部署端点、内部路径和个人档案描述。这里以不含这些信息的说明保留代码来源、依赖和验证边界。

## 代码路径与控制边界

视觉端输出 `emotion_strategy_v1` JSONL 后，`emotion_interaction.py` 会验证事件、去重并从三类策略中选择话术。它可只输出固定 phrase JSONL，也可通过 `SpeechClient` 生成 WAV；PCM 播放只有同时指定 bridge 路径和 `--confirm-g1-companion-pcm` 时才会调用确认播放命令，单进程最多三条。

`emotion_dialogue.py` 在 `dialogue` 与 `motion` 演示模式间切换。它本身不初始化 Unitree SDK、DDS 或直接写机器人命令：伤心 `listen_hold` 分支只输出 `emotion_dialogue_custom_action_request`，动作演示仅在明确口头肯定后输出 `emotion_dialogue_motion_request`。外层历史 launcher 将这些 JSON 行交给已另行保存的执行器，因此现场动作仍须遵守 launcher 和执行器的独立确认条件。

对话模式可调用本地语音服务、麦克风录音、本地陪聊 API、PCM bridge 和会话记录。故事或笑话回复可委托现有的 `play_interruptible_wav`，该路径使用 PCM bridge 的 `--allow-interrupt`/`SIGUSR1` 合同。运行时的控制 stdout 不包含转写正文，但 console 与会话记录可保存对话文本；未在本轮启动或创建这些记录。

## 当前缺件

| 部分 | 当前状态 |
| --- | --- |
| 多轮对话 | `emotion_dialogue.py` 和其测试直接导入未收到的 `speech/scenarios/elder_companion/elder_chat_client.py`、`end_request.py`，所以当前不能导入或运行。 |
| 历史 launcher | 仍缺 wake-mode 脚本、本机两个虚拟环境、视觉模型和演示视频；完整根 CMake、SDK、DDS 与现场设备条件也未具备。 |
| 固定 phrase bridge | `emotion_interaction.py --g1-bridge` 引用未收到的 `g1_companion_tts_phrase_bridge` 源码。现有 wrapper 使用 PCM bridge，这条旧路径尚未复现。 |
| PCM 播放 | bridge 的直接源码已收到，但完整根工程仍不能构建。当前核心限制是 32 MiB 数据，不存在代码级 15 秒时长上限，详见 [PCM bridge 说明](PCM_BRIDGE.md)。 |

`emotion_dialogue.py` 的直接 CLI 与历史 launcher 使用不同的本地陪聊服务配置；两者都只记录源码现状，不构成当前环境的可运行部署说明。

## 验证边界

七个 Python 文件均通过 AST 语法解析并逐文件与附件一致。静态审查核对了事件校验、确认播放参数、娱乐打断协议和 launcher 的确认门控；未运行这些测试或 launcher。`test_entertainment_interrupt.py` 会建立本地 fake bridge 并启动进程，两个 launcher 测试也会调用 Shell 拒绝分支，因此没有把它们当成纯离线导入检查执行。

历史 wrapper 和原始说明中仍有“每条 WAV 最长 15 秒”的写法；这与当前 PCM 核心源码不一致，不能作为实际时长保证。
