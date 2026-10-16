# 娱乐陪伴模块说明

## 当前导入范围

目录为 `speech/scenarios/companion_entertainment/`。已导入 15 个 Python 文件、6 条目录项的 `content_catalog.json` 和 3 条固定播报稿的 `news_scripts.json`，以及 `run_g1_demo.sh`。公共 `speech/robot_actions/` 两个模块和 `speech/test_companion_entertainment_showcase.py` 也已补齐。保留原目录及程序逻辑，未导入媒体、备份或运行日志。

新闻稿按用户提供的项目素材保存，不属于联网新闻采集或本轮事实核验结果。现用代码与另一套目录实现分别记录，未据文件名擅自删除或归档代码。

## 普通版与比赛版

| 项目 | 普通版 | 比赛展示版 |
| --- | --- | --- |
| 入口 | `g1_voice_demo.py` | `g1_showcase_demo.py` |
| 启动脚本 | `run_g1_demo.sh` | 本批没有专用启动脚本，实际命令待补 |
| 控制器 | `EntertainmentController` | `ShowcaseController`，复用普通控制器执行媒体操作 |
| 交互范围 | 类别播放、作品搜索、下一条、继续、停止 | 固定顺序：音乐第一首 → 音乐第二首 → 新闻 → 戏曲 → 结束 |
| 指定作品 | 普通控制器可搜索 | 分类器可识别，但状态机未授权执行 |
| 共享需求写入 | 默认允许，`--no-need-write` 可关闭 | 默认不写，`--record-elder-needs` 可开启 |
| 公共会话日志 | 接入 `companion_recording` | 本批入口未接入该录制模块 |

比赛控制器按状态放行指令，非法指令静默忽略，允许提前结束。它运行前要求媒体目录至少包含两首音乐、一条新闻和一段戏曲。

两个入口都在顶层导入 `robot_actions.RobotActionClient`。本批补齐该包后，两入口的 `--help` 均加载并退出成功。源码中的 `--robot-actions` 默认值为 `dry-run`，只约束动作客户端；麦克风、ASR、云语音和播放流程仍会运行，不能作为整场景离线开关。

普通版支持普通话或陕西话；比赛版的互动使用陕西话、决策播报使用普通话。普通版的 `--request-seconds`、`--control-seconds` 在函数内被丢弃，仅保留参数兼容；实际滚动 ASR 配置为 4.5 秒窗口、0.5 秒步长、2 个 worker、12 秒缓冲。比赛版使用 `--listen-seconds` 设置窗口，默认 4.5 秒，状态超时默认 60 秒。

二者优先使用模型进行意图识别，调用不可用时有规则回退；模型低置信结果会忽略。比赛版还提供 `--no-llm`，该参数只影响意图分类，不关闭 ASR/TTS 或机器人连接。当前代码在合法操作前停止 ASR，反馈与启动媒体后重建识别器。

本批未包含四场景统一路由；娱乐入口处理媒体类别切换及当前场景结束，没有自动启动照护、社交或联系家属的调度链。

## 媒体与两份 JSON 的关系

当前普通版、展示版及 `text_demo.py` 均通过 `EntertainmentController → LocalMediaLibrary` 扫描：

```text
content/music/
content/news/
content/opera/
```

扫描按文件名排序，去除数字排序前缀后的文件名作为展示标题。这条运行路径不读取 `content_catalog.json`。

`content_catalog.json` 由独立的 `entertainment_logic.py → EntertainmentSession` 读取。其六条路径在当前云仓库中均无对应媒体；该实现未被本批 G1/文字入口引用，保留原样，不能据此判定整个文件已废弃。

`news_scripts.json` 供 `generate_news_audio.py` 使用，输出文件名为各条目的 `{id}.wav`，分别为 `asian_games_team.wav`、`china_basketball.wav`、`table_tennis_doubles.wav`。这些名字与目录清单中的 `sports_news_01.wav`、`sports_news_02.wav` 不同；当前主链扫描目录，不要求与该清单逐项对应，因此本轮没有自动改名。

新闻生成脚本在导入时创建 `content/news`，并要求 `DASHSCOPE_API_KEY`，只做了静态检查。`normalize_g1_wav.py` 会覆盖输入音频，本轮未调用归一化函数或脚本主程序。

## 录制、共享需求和播放边界

普通版使用 `companion_recording` 记录 ASR、语音请求/回执、媒体和动作结果。`--record-mode replay` 只设置日志模式元数据，仍执行同一个场景函数，不自动变成无机器人回放。

`EntertainmentNeedSession` 复用共享需求登记模块。普通版默认老人 ID 为 1，关联时以只读方式检查启用的老人记录；缺库或无有效老人时关闭需求关联/写入，娱乐流程可继续。明确作品点播历史可用于偏好选择，不能把任意关键词等同于作品偏好。

`G1MediaPlayer` 通过 `ffmpeg` 转成 16 kHz、单声道、16 bit PCM，限制 PCM 大小为 32 MiB，再调用项目根的 `build/g1_companion_pcm_bridge`。该类使用固定 bridge 路径，不复用 `SpeechClient` 的 `G1_PCM_BRIDGE` 环境覆盖。

媒体后台进程短时间内未退出即视为开始播放；这不能证明现场已听到声音。当前没有真正暂停/恢复接口，`continue` 保持现状，媒体自然结束也不自动播放下一首。

## 公共动作客户端

`RobotActionClient` 提供 `greeting`、`goodbye`、`present`、`acknowledge`、`celebrate` 五种请求，复用项目根目录的两个外部执行器，本身不直接调用 Unitree SDK 或 DDS。

- `off`：跳过动作。
- 默认 `dry-run`：构造和输出请求，不启动执行器。
- `execute`：还须 `confirm_writes=True` 才启动执行器；两个语音 CLI 也检查对应的执行与确认参数组合。

这描述的是代码参数门控，不代表动作执行、机器人兼容性或现场效果已经验证。本轮没有调用动作执行方法。

执行器源码现已提供：`scripts/g1_elder_companion_motion_executor.py` 与 `scripts/g1_elder_companion_custom_action_executor.py`。默认解释器是 `/home/user/miniconda3/envs/tv/bin/python`，默认网卡为 `enp3s0`，分别支持 `G1_ACTION_PYTHON` 和 `G1_ACTION_INTERFACE` 环境覆盖。两份脚本均依赖 Unitree SDK、DDS 和 G1/Dex3；本轮只做静态审查，没有运行其 CLI、初始化 DDS 或连接机器人。完整边界见 [G1 动作执行器说明](ROBOT_ACTIONS.md)。

源码的 `_motion_lock` 是客户端实例成员，只保证同一实例的互斥，不是不同客户端或不同进程之间的全局互斥。执行结果中的 `completed` 来自执行器进程退出码，本模块没有验证实际肢体动作完成。

## 仍需补齐的内容

- Unitree SDK、DDS/设备网络配置和现场安全验收，用于验证已收到的两个动作执行器能否真实执行；公共动作包和执行器源码均已收到，导入阻断已解除。
- 本地媒体及其目录、格式信息；当前云仓库三个媒体目录为空，未生成假音频补齐演示。
- `build/g1_companion_pcm_bridge` 的首批源码和上游构建清单已收到，但缺 `src/g1_companion_pcm.hpp`、`tests/g1_companion_pcm_test.cpp` 及完整 C++ 工程，当前不能配置或构建；还需要官方 SDK、`jsoncpp` 和 `ffmpeg`。本轮未验证转换或播放流程，详见 [G1 PCM bridge 说明](PCM_BRIDGE.md)。
- 老人基表及匿名演示数据，用于验证需求关联与写入；无需上传真实老人数据库。
- `test_entertainment_interrupt.py` 等其他已有验收脚本；展示套件 `test_companion_entertainment_showcase.py` 已收到并运行。

## 本轮验证结果

- 15 个 Python 文件通过 Python 3.10 语法解析；导入内容与附件一致，仅统一文本换行。
- 两份 JSON 可解析，分别检查 6 个唯一目录 ID 和 3 个唯一新闻稿 ID，未检查新闻事实。
- 使用前批临时 `requests` 依赖，12 个控制与媒体模块导入成功。`g1_media_player` 导入会创建忽略范围内的运行目录；其他业务函数未执行。
- 两个 G1 入口前批均因缺失 `robot_actions` 受阻。本批导入真实动作包后，两入口的 `--help` 均正常退出；没有启动场景或实机流程。
- 已运行原有 `entertainment_intent.py` 的 14 个打印样例，以及 `text_demo.py` 的 5 轮输入：无聊、音乐、点播、下一条、停止。程序完成，依次返回 `ask_category`、`empty`、`not_found`、`empty`、`stop`，并正常结束。

规则样例和文字流程是程序演练，不作为自动断言套件的通过结论。演练只创建了空媒体目录，未连接数据库、调用云模型、播放或发送机器人动作。

## 展示自动测试的实际结果

本批使用临时 `requests` 依赖，明确选择 `test_companion_entertainment_showcase` 运行，没有对全仓库做自动发现。15 项原有测试全部执行：12 项通过、3 项失败、0 错误、0 跳过，退出码为 1。两项纯状态机测试均通过；源码和断言未修改。

| 失败测试 | 测试期望分类 | 当前实际分类 |
| --- | --- | --- |
| `test_news_cannot_skip_next` | `other` | `switch_news` |
| `test_next_during_news_ignored` | `other` | `next_music` |
| `test_qinqiang_is_ignored` | `other` | `specific_media_request` |

`demo_intent.py` 的当前实现和注释将语义识别与状态授权分开：高置信模型结果先返回，是否允许执行交给 `ShowcaseController.handle()`。上述测试则在分类层断言结果必须为 `other`，两者约定不一致。

针对三例补做纯逻辑诊断，将实际分类结果交给对应状态的真实控制器，均得到 `ignore` 且状态保持不变。这说明这三例在已检查的状态机路径中仍被拒绝，不等于原测试通过，也不能替代实机验证。后续修改需统一测试与实现约定，本次迁移只记录差异。

测试和诊断使用原有 `FakeLLM` 与规则，没有创建真实云模型，也没有发起数据库、媒体、子进程或机器人动作调用。声音质量、实际打断、动作、媒体播放及比赛完整闭环均未验证。
