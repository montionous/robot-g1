# 语音模块迁移记录

## 范围与来源

从用户提供的文本附件导入原项目 `/home/user/github-product/g1-dex3-care-vla` 中已收到的文件，保留 `speech/` 层级。此仓库当前承载语音与日常陪伴模块，不包含完整机器人项目。

原项目的 `AGENTS.md` 保存为 `docs/upstream-project-rules.md`，用于保留原团队的控制边界、停止条件和协作约定；其中的历史训练路线、绝对路径和情绪模块状态不代表本仓库已经具备这些组件。

原始源码只统一 CRLF/LF 和文件末尾换行，没有修改函数、参数、启动流程或依赖声明。附件中的文件分隔标题、终端提示符、采集命令及“文件不存在”提示不属于源码，没有导入。

## 已收到的文件

- 服务及 G1 客户端：`speech/server.py`、`speech/speech_client.py`。
- 共享需求与会话模块：`speech/elder_need_registry.py`、`speech/decision_announcer.py`、`speech/companion_recording.py`、`speech/init_elder_need_db.py`。
- 动作客户端：`speech/robot_actions/action_client.py`、`speech/robot_actions/__init__.py`。
- 内层语音包：`speech/speech/` 下 9 个 Python 文件，含 ASR、TTS、播放、预设、包客户端、直接语音接口及娱乐回复模板。
- G1 音频组件：`speech/g1_audio/` 下 6 个 Python 文件，含单次/连续录音、滚动 ASR、播放封装和娱乐打断。
- 照护咨询：`speech/scenarios/care_consultation_support/` 下 25 个 Python 文件和含 35 条知识卡的 `care_knowledge.json`。两份同名源码附件内容相同，只导入一次。
- 娱乐陪伴：`speech/scenarios/companion_entertainment/` 下 15 个 Python 文件，以及用户提供的 `content_catalog.json`、`news_scripts.json`；未导入音频素材。
- 娱乐展示验收：`speech/test_companion_entertainment_showcase.py`，包含 15 项原有 unittest，保持断言原样。
- 语音服务启动及会话配置脚本：`speech/run_server.sh`、`speech/companion_recording_env.sh`。
- 四场景启动脚本：下表中的七个脚本。
- 原语音文档及依赖：`speech/README.md`、`speech/TEAM_USAGE.md`、`speech/requirements.txt`。
- 原项目规则快照：`docs/upstream-project-rules.md`。

合计保留 80 个原项目文件，其中 79 个位于 `speech/`，包含 64 个 Python 文件和 9 个 Shell 脚本。第二批再次提供的 `speech/speech/service.py` 与首批内容一致，没有覆盖出不同版本。

## 现用场景与废弃场景

现用场景以用户确认的四个目录为准：`care_consultation_support`、`companion_entertainment`、`social_activity_support`、`contact_family`。

用户已明确确认以下三个场景废弃：`elder_companion`、`caregiver_chat`、`short_companion_chat`。当前收到的源码未包含这三个场景目录，没有将其纳入现用场景入口。后续若收到这些目录，先检查共享依赖，再单独归档并保留来源。

第二批附件主要包含公共包与 G1 音频组件，不包含额外的 `scenarios/` 目录。`$HOME/.config/elder_companion/cloud.env` 是现有脚本共用的配置路径，不因与废弃场景同名而删除或改名。

| 模块 | 当前可确认的调用证据 | 整理状态 |
| --- | --- | --- |
| `speech/speech/asr_cloud.py`、`tts_cloud.py` | `server.py` 直接导入 | 公共语音服务依赖 |
| `speech/g1_audio/g1_mic_recorder.py`、`g1_pcm_bridge.py` | `speech_client.py` 的录音/播放方法延迟导入 | 已有 G1 客户端依赖 |
| `speech/speech/client.py` | 内层包 `__init__.py` 导出该 `SpeechClient` | 包公共接口；四场景是否使用待确认 |
| `speech/speech/service.py` 的 `listen()` | 注释明确为旧 `medication_robot` 兼容入口，依赖 `asr.*` | 旧兼容函数；不据此弃用整个文件 |
| `speech/speech/playback.py` | `service.py` 导入，支持外部播放器和本机播放回退 | 播放依赖；现用配置待确认 |
| `speech/speech/reply/companion_entertainment.py` | `reply/__init__.py` 导出 `generate_reply` | 娱乐回复模板；场景调用待确认 |
| `speech/g1_audio/entertainment_interrupt.py` | 导入现有 G1 录音及外层客户端，包含播放打断流程 | 场景调用待确认 |
| `speech/g1_audio/g1_live_asr.py`、`g1_continuous_recorder.py` | 前者依赖后者，后者复用麦克风常量和网卡选择 | 公共音频组件；场景调用待确认 |

共享模块保留原路径，避免移动后破坏尚未收到的场景代码的导入关系。只有得到用户确认或具体调用证据后，才进一步调整归属。

## 已从脚本确认的入口

以下描述脚本和源码内容，未启动语音场景。照护咨询通过 `g1_voice_demo.py --showcase` 切换展示模式；娱乐陪伴有独立的 `g1_voice_demo.py` 和 `g1_showcase_demo.py`；其余场景的版本入口仍待源码与实际命令核对。

| 场景 | 已导入的启动脚本 | 脚本引用的 Python 入口及状态 |
| --- | --- | --- |
| 照护咨询 | `run_care_api.sh` | `care_api.py`，已收到 |
| 照护咨询 | `run_g1_demo.sh` | `g1_voice_demo.py`，已收到 |
| 娱乐陪伴 | `run_g1_demo.sh` | `g1_voice_demo.py`，已收到 |
| 娱乐陪伴展示 | 尚未收到专用启动脚本 | `g1_showcase_demo.py`，已收到 |
| 社交活动 | `run_g1_demo.sh` | `g1_voice_demo.py`，未收到 |
| 社交活动展示 | `run_g1_showcase.sh` | 先运行 `refresh_activity_schedule.py`，再运行 `g1_showcase_demo.py`，均未收到 |
| 联系家属 | `run_g1_demo.sh` | `g1_voice_demo.py`，未收到 |
| 联系家属模拟通话 | `run_mock_call_server.sh` | `mock_call_server.py`，未收到 |

脚本均位于 `speech/scenarios/<场景目录>/`。本批已补齐娱乐两个语音入口顶层导入的 `robot_actions.RobotActionClient`，两入口的 `--help` 均能加载并正常退出；未启动语音或机器人流程。

照护咨询的 API、文本和 G1 语音入口的能力及收尾行为不同，详见 [照护咨询模块说明](CARE_CONSULTATION.md)。JSON 知识检索模块也尚未在本批控制器主链中接入，不把知识库文件已导入等同于运行链已使用。

娱乐陪伴版本、媒体目录与 JSON 清单的关系见 [娱乐陪伴模块说明](COMPANION_ENTERTAINMENT.md)。当前两个 G1 入口及文字入口通过 `LocalMediaLibrary` 扫描实际媒体目录；`content_catalog.json` 由另一条 `EntertainmentSession` 路径读取，保留原样，用途不据此定为废弃。

## 语音调用路径

1. 外层 `speech/speech_client.py` 的 `SpeechClient` 请求 `/health`、`/speak` 和 `/asr`，并提供 G1 录音与 PCM bridge 播放接口。内层 `speech/speech/client.py` 是另一个 HTTP 客户端，由内层包的 `__init__.py` 导出；二者保留原有接口，不合并或重命名。
2. 内层 `speech/speech/service.py` 直接调用云 TTS 和 `playback.play_wav()`。后者在 Windows 使用 `winsound`，其他平台优先使用 `G1_WAV_PLAYER` 指定的播放器，再回退 `aplay`/`paplay`；不能将此路径与外层客户端的 PCM bridge 播放等同。兼容 `listen()` 引用旧项目的 `asr.recorder` 和 `asr.recognize`，不据此认定四场景仍依赖旧录音链。
3. `g1_live_asr.py` 的 `G1RollingASR` 复用持续麦克风流，把重叠 WAV 窗口交给传入客户端的 `transcribe()`；不据此将其描述为厂商实时流式 ASR API。

当前客户端 `speak_g1()` 读取服务返回的 `audio_path`，并在客户端文件系统中查找 WAV。这要求客户端能访问对应文件路径；将服务移到另一台机器时，仅更改 URL 不能保证播放可用。

## 还缺少的直接依赖

- 社交活动、联系家属的主体入口，以及它们引用的控制器、意图识别、数据库结构、内容目录和测试。
- 娱乐陪伴的实际媒体。当前仓库的音乐、新闻、戏曲目录均为空；展示入口检查至少两首音乐、一条新闻、一段戏曲。展示 unittest 已收到，打断等其他验收脚本仍未上传。
- 动作执行器：项目根 `scripts/g1_elder_companion_motion_executor.py`、`scripts/g1_elder_companion_custom_action_executor.py` 及其依赖。动作客户端已收到，但默认引用原机器的 `tv` Python 环境和 `enp3s0`；源码可通过 `G1_ACTION_PYTHON`、`G1_ACTION_INTERFACE` 覆盖，尚未验证实机兼容。
- 老人数据基础：`elderly_person` 基表初始化和匿名演示种子尚未收到。`init_elder_need_db.py` 已收到，但只创建共享需求表及索引，不创建基表或 `speech/data/` 父目录；不能用真实老人数据库补迁移。
- 原项目根目录的 `care_console` 包：`companion_recording_env.sh` 执行 `python3 -m care_console.link`，传入老人 ID 和日志路径，默认控制台 URL 为 `http://127.0.0.1:8766`。尚未收到该模块，无法确认它对控制台连接的要求和失败处理。
- G1 播放 bridge：默认查找项目根目录下的 `build/g1_companion_pcm_bridge`。其源码和构建配置尚未收到；官方 SDK 保持外部依赖，不复制 SDK 源码。娱乐打断模块还要求该二进制支持 `--allow-interrupt`、`SIGUSR1` 和对应 JSON 回执，不能用任意同名播放器代替。
- 仅兼容 `service.listen()` 需要旧项目的 `asr.recorder`、`asr.recognize`；目前没有证据表明四场景仍调用它。

当前 `speech/requirements.txt` 仅声明 `dashscope>=1.25.17`。已收到代码还使用 `openai`、`fastapi`、`pydantic`、`uvicorn`、`requests`；FastAPI 的文件与表单接口还需要 `python-multipart`。这些依赖的实际版本及其余场景依赖待核对，原依赖文件暂不改写。

本批四个共享模块只使用标准库及彼此之间的导入；需求登记模块在导入时加载 `Asia/Shanghai` 时区，需要可用的系统时区数据。会话日志在实际调用时才创建，继续保存在忽略的运行目录内。

系统工具依赖：Qwen3 TTS 分支使用 `ffmpeg` 转换为 16 kHz 单声道 PCM WAV；主机播放可使用 `aplay`/`paplay`，联系家属脚本的健康检查使用 `curl`。原机器报告 Python 3.10.12；麦克风模块使用 `audioop`，该标准库模块已从 Python 3.13 移除，升级解释器需要单独验证。

云模块从环境读取 `DASHSCOPE_API_KEY`、`DASHSCOPE_WORKSPACE_ID`，配置文件和密钥值未导入。ASR 使用工作空间的 `cn-beijing.maas.aliyuncs.com/compatible-mode/v1` 路径；TTS 使用工作空间 HTTP API 或 `QWEN3_TTS_ENDPOINT` 指定路径，并下载返回的音频 URL。以上为源码事实，未发起云调用。

## 迁移时需要处理的本机约定

- `speech/run_server.sh` 写死原项目目录和 `speech/venv`，加载 `$HOME/.config/elder_companion/cloud.env`，设置端口 `8780`。
- 联系家属的两个启动脚本写死 `$HOME/github-product/g1-dex3-care-vla/speech`。
- 多数场景脚本使用当前环境的 `python3`，社交展示脚本则使用 `./venv/bin/python`，解释器选择尚未统一。
- 四场景的 `run_g1_demo.sh` 都先加载 `companion_recording_env.sh`，并追加老人 ID、会话日志和 `--record-mode live`。配置脚本要求有效的 `G1_ELDERLY_ID`，在项目根目录的 `runs/elder-companion-interaction` 下创建会话目录，并调用 `care_console.link`；这些运行记录已加入忽略范围。
- 社交展示脚本先刷新活动日程；确认目标数据库及写入行为后再执行。
- 联系家属启动脚本固定检查 `http://127.0.0.1:8780/health`。
- `playback.py` 的旧播放器默认路径为 `/home/unitree/medication_robot/bin/g1_play_wav`，可用 `G1_WAV_PLAYER` 覆盖。
- 麦克风模块用 `192.168.123.164` 作为网卡选择目标，接收 `239.168.123.161:5555` 的音频多播；与上游规则中的设备地址不完全一致，保留原值，等待现用机器验证。
- 原 README 同时包含早期 Windows、旧服药兼容接口和情绪联调内容，不能作为当前四场景的完整运行说明。

上述行为均保留原状，待源码和实际运行命令齐全后再作有针对性的调整。配置文件只记录路径和变量名，不导入密钥值。

## 验证状态

当前累计 64 个 Python 文件、9 个 Shell 脚本，执行导入内容一致性检查、Python AST 语法解析、`bash -n` 和三份 JSON 检查。重复的 `service.py` 和照护咨询重复源码附件单独核对一致。没有执行会话配置、刷新数据库、监听麦克风或启动播放。

本批还在 Python 3.12.14 下验证了 9 个模块导入：四个新共享模块，以及 `care_controller`、`g1_voice_demo`、`care_api`、`text_demo`、`test_showcase_offline_chain`。因当前机器缺少 `requests`，仅向 `/tmp/g1-care-import-deps-batch4` 安装 `requests==2.34.2` 及其依赖用于检查；这不是原机器人环境的版本声明，也未修改 `requirements.txt`。检查拦截数据库、出站连接和子进程调用；请求库的本地 IPv6 能力探测被拦截，业务模块未尝试这些操作。未调用任何场景函数、初始化函数或测试 `main()`。

已尝试 `python3 speech/scenarios/care_consultation_support/test_showcase_offline_chain.py`，退出码为 1，原因是前置检查找不到 `speech/data/elder_companion.db`；5 段场景验收均未执行。这是当前迁移缺少测试数据与依赖的阻断，尚无功能测试通过的结论。

本批补齐了该验收脚本的共享源码导入依赖，但数据库前置条件仍未改变，因此没有重复运行同一个会在前置检查停止的命令。

娱乐陪伴的 12 个控制与媒体模块导入通过；两个语音入口前批因缺 `robot_actions` 受阻，本批补齐真实动作模块后，分别执行 `--help` 加载并退出成功。新闻音频生成脚本只做静态检查，未导入或执行。前批已运行原有规则脚本的 14 个样例及文字入口的 5 轮输入；媒体为空时返回 `empty`/`not_found`，停止指令正常结束，未验证实际播放。

本批明确选择原有 `test_companion_entertainment_showcase` 套件运行，15 项实际执行：12 项通过、3 项失败、0 错误、0 跳过，测试退出码为 1。三项失败是分类结果与测试期望不同，详见娱乐模块文档；随后逐例核对，状态机均返回 `ignore` 且状态未改变。这些诊断不替代原测试，也没有把该套件记为通过。业务源码和测试断言均保持原样。

HTTP 启动、云 ASR/TTS、数据库业务行为、真实拨号及 G1 录音/播放均未验证。当前仍缺少其他场景、公共依赖、相关服务、PCM bridge 和运行配置，不能认定项目可独立运行。

后续继续按用户上传的文件分批导入和提交，保留两个版本的原有入口。未提供的源码不以占位实现补齐；机器人电脑上的现有工作区和其他成员改动保持原状。
