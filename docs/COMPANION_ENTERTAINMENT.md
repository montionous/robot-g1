# 娱乐陪伴模块说明

## 当前导入范围

目录为 `speech/scenarios/companion_entertainment/`。本批导入 15 个 Python 文件、6 条目录项的 `content_catalog.json` 和 3 条固定播报稿的 `news_scripts.json`，此前已导入 `run_g1_demo.sh`。保留原目录及程序逻辑，未导入媒体、备份或运行日志。

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

两个入口都在顶层导入 `robot_actions.RobotActionClient`，当前仓库缺该包，因此导入和 `--help` 均受阻。源码中的 `--robot-actions` 默认值为 `dry-run`，只约束动作客户端；麦克风、ASR、云语音和播放流程仍会运行，不能作为整场景离线开关。

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

## 仍需补齐的内容

- `speech/robot_actions/` 的实际源码及其配置/依赖，用于解除两个语音入口的硬导入阻断。
- 本地媒体及其目录、格式信息；当前云仓库三个媒体目录为空，未生成假音频补齐演示。
- `build/g1_companion_pcm_bridge` 的源码与构建配置、官方 SDK 外部依赖。播放还需要 `ffmpeg`，本轮未验证其转换流程。
- 老人基表及匿名演示数据，用于验证需求关联与写入；无需上传真实老人数据库。
- 原项目的 `test_companion_entertainment_showcase.py`、`test_entertainment_interrupt.py` 等已有验收脚本；本批没有自动断言测试文件。

## 本轮验证结果

- 15 个 Python 文件通过 Python 3.10 语法解析；导入内容与附件一致，仅统一文本换行。
- 两份 JSON 可解析，分别检查 6 个唯一目录 ID 和 3 个唯一新闻稿 ID，未检查新闻事实。
- 使用前批临时 `requests` 依赖，12 个控制与媒体模块导入成功。`g1_media_player` 导入会创建忽略范围内的运行目录；其他业务函数未执行。
- 两个 G1 入口均尝试导入并明确阻于缺失的 `robot_actions`，没有以占位模块绕过。
- 已运行原有 `entertainment_intent.py` 的 14 个打印样例，以及 `text_demo.py` 的 5 轮输入：无聊、音乐、点播、下一条、停止。程序完成，依次返回 `ask_category`、`empty`、`not_found`、`empty`、`stop`，并正常结束。

规则样例和文字流程是程序演练，没有自动断言测试套件的通过结论。演练只创建了空媒体目录，未连接数据库、调用云模型、播放或发送机器人动作。声音质量、实际打断、动作、媒体播放及比赛完整闭环均未验证。
