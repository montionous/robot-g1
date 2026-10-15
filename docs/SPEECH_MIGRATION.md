# 语音模块迁移记录

## 范围与来源

从用户提供的文本附件导入原项目 `/home/user/github-product/g1-dex3-care-vla` 中已收到的文件，保留 `speech/` 层级。此仓库当前承载语音与日常陪伴模块，不包含完整机器人项目。

原项目的 `AGENTS.md` 保存为 `docs/upstream-project-rules.md`，用于保留原团队的控制边界、停止条件和协作约定；其中的历史训练路线、绝对路径和情绪模块状态不代表本仓库已经具备这些组件。

原始源码只统一 CRLF/LF 和文件末尾换行，没有修改函数、参数、启动流程或依赖声明。附件中的文件分隔标题、终端提示符、采集命令及“文件不存在”提示不属于源码，没有导入。

## 已收到的文件

- 服务及 G1 客户端：`speech/server.py`、`speech/speech_client.py`。
- 内层语音包：`speech/speech/` 下 9 个 Python 文件，含 ASR、TTS、播放、预设、包客户端、直接语音接口及娱乐回复模板。
- G1 音频组件：`speech/g1_audio/` 下 6 个 Python 文件，含单次/连续录音、滚动 ASR、播放封装和娱乐打断。
- 语音服务启动及会话配置脚本：`speech/run_server.sh`、`speech/companion_recording_env.sh`。
- 四场景启动脚本：下表中的七个脚本。
- 原语音文档及依赖：`speech/README.md`、`speech/TEAM_USAGE.md`、`speech/requirements.txt`。
- 原项目规则快照：`docs/upstream-project-rules.md`。

合计保留 30 个原项目文件，其中 29 个位于 `speech/`，包含 17 个 Python 文件和 9 个 Shell 脚本。第二批再次提供的 `speech/speech/service.py` 与首批内容一致，没有覆盖出不同版本。

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

以下仅描述脚本内容，未实际执行。`g1_voice_demo.py` 是否属于完整版、各展示入口的比赛定位，仍需结合用户实际命令和场景源码确认。

| 场景 | 已导入的启动脚本 | 脚本引用的 Python 入口（尚未收到） |
| --- | --- | --- |
| 照护咨询 | `run_care_api.sh` | `care_api.py` |
| 照护咨询 | `run_g1_demo.sh` | `g1_voice_demo.py` |
| 娱乐陪伴 | `run_g1_demo.sh` | `g1_voice_demo.py` |
| 社交活动 | `run_g1_demo.sh` | `g1_voice_demo.py` |
| 社交活动展示 | `run_g1_showcase.sh` | 先运行 `refresh_activity_schedule.py`，再运行 `g1_showcase_demo.py` |
| 联系家属 | `run_g1_demo.sh` | `g1_voice_demo.py` |
| 联系家属模拟通话 | `run_mock_call_server.sh` | `mock_call_server.py` |

脚本均位于 `speech/scenarios/<场景目录>/`。娱乐陪伴的 `g1_showcase_demo.py` 在用户目录清单中出现，但源码和实际启动命令尚未收到。

## 语音调用路径

1. 外层 `speech/speech_client.py` 的 `SpeechClient` 请求 `/health`、`/speak` 和 `/asr`，并提供 G1 录音与 PCM bridge 播放接口。内层 `speech/speech/client.py` 是另一个 HTTP 客户端，由内层包的 `__init__.py` 导出；二者保留原有接口，不合并或重命名。
2. 内层 `speech/speech/service.py` 直接调用云 TTS 和 `playback.play_wav()`。后者在 Windows 使用 `winsound`，其他平台优先使用 `G1_WAV_PLAYER` 指定的播放器，再回退 `aplay`/`paplay`；不能将此路径与外层客户端的 PCM bridge 播放等同。兼容 `listen()` 引用旧项目的 `asr.recorder` 和 `asr.recognize`，不据此认定四场景仍依赖旧录音链。
3. `g1_live_asr.py` 的 `G1RollingASR` 复用持续麦克风流，把重叠 WAV 窗口交给传入客户端的 `transcribe()`；不据此将其描述为厂商实时流式 ASR API。

当前客户端 `speak_g1()` 读取服务返回的 `audio_path`，并在客户端文件系统中查找 WAV。这要求客户端能访问对应文件路径；将服务移到另一台机器时，仅更改 URL 不能保证播放可用。

## 还缺少的直接依赖

- 上表引用的场景入口，以及它们引用的控制器、意图识别、数据库结构、内容目录和测试。
- 原项目根目录的 `care_console` 包：`companion_recording_env.sh` 执行 `python3 -m care_console.link`，传入老人 ID 和日志路径，默认控制台 URL 为 `http://127.0.0.1:8766`。尚未收到该模块，无法确认它对控制台连接的要求和失败处理。
- G1 播放 bridge：默认查找项目根目录下的 `build/g1_companion_pcm_bridge`。其源码和构建配置尚未收到；官方 SDK 保持外部依赖，不复制 SDK 源码。娱乐打断模块还要求该二进制支持 `--allow-interrupt`、`SIGUSR1` 和对应 JSON 回执，不能用任意同名播放器代替。
- 仅兼容 `service.listen()` 需要旧项目的 `asr.recorder`、`asr.recognize`；目前没有证据表明四场景仍调用它。

当前 `speech/requirements.txt` 仅声明 `dashscope>=1.25.17`。已收到代码还使用 `openai`、`fastapi`、`pydantic`、`uvicorn`、`requests`；FastAPI 的文件与表单接口还需要 `python-multipart`。这些依赖的实际版本及其余场景依赖待核对，原依赖文件暂不改写。

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

当前累计 17 个 Python 文件、9 个 Shell 脚本，执行导入内容一致性检查、Python AST 语法解析和 `bash -n`，不导入或执行业务模块。第二批重复的 `service.py` 单独核对一致。没有执行会话配置、刷新数据库、监听麦克风或启动播放。

功能测试、HTTP 启动、云 ASR/TTS、数据库行为、真实拨号及 G1 录音/播放均未运行。当前缺少完整场景、相关服务、PCM bridge 和运行配置，不能认定项目可独立运行。

后续继续按用户上传的文件分批导入和提交，保留两个版本的原有入口。未提供的源码不以占位实现补齐；机器人电脑上的现有工作区和其他成员改动保持原状。
