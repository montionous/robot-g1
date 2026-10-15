# 语音模块迁移记录

## 范围与来源

从用户提供的文本附件导入原项目 `/home/user/github-product/g1-dex3-care-vla` 中已收到的文件，保留 `speech/` 层级。此仓库当前承载语音与日常陪伴模块，不包含完整机器人项目。

原项目的 `AGENTS.md` 保存为 `docs/upstream-project-rules.md`，用于保留原团队的控制边界、停止条件和协作约定；其中的历史训练路线、绝对路径和情绪模块状态不代表本仓库已经具备这些组件。

原始源码只统一 CRLF/LF 和文件末尾换行，没有修改函数、参数、启动流程或依赖声明。附件中的文件分隔标题及“文件不存在”提示不属于源码，没有导入。

## 已收到的文件

- 公共源码：`speech/server.py`、`speech/speech_client.py`、`speech/speech/service.py`。
- 语音服务启动脚本：`speech/run_server.sh`。
- 四场景启动脚本：下表中的七个脚本。
- 原语音文档及依赖：`speech/README.md`、`speech/TEAM_USAGE.md`、`speech/requirements.txt`。
- 原项目规则快照：`docs/upstream-project-rules.md`。

合计保留 15 个原项目文件，其中 14 个位于 `speech/`，包含 3 个 Python 文件和 8 个 Shell 脚本。

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

## 两条语音调用路径

1. `speech_client.py` 的 `SpeechClient` 请求 `/health`、`/speak` 和 `/asr`。G1 录音、播放分别延迟导入 `g1_audio` 模块，播放使用 PCM bridge。
2. 内层 `speech/service.py` 直接导入云 TTS、播放和预设模块。其 `speak()` 调用 `play_wav()`；不能仅凭旧团队文档将它视为 G1 播放路径。兼容 `listen()` 引用旧项目的 `asr.recorder` 和 `asr.recognize`，不据此认定四场景仍依赖旧录音链。

当前客户端 `speak_g1()` 读取服务返回的 `audio_path`，并在客户端文件系统中查找 WAV。这要求客户端能访问对应文件路径；将服务移到另一台机器时，仅更改 URL 不能保证播放可用。

## 还缺少的直接依赖

- 内层语音包：`speech/speech/asr_cloud.py`、`tts_cloud.py`、`playback.py`、`presets.py`，以及实际存在的包初始化文件。
- G1 音频模块：`speech/g1_audio/g1_mic_recorder.py`、`g1_pcm_bridge.py` 及其引用文件。
- 会话配置：`speech/companion_recording_env.sh` 及其引用模块。上传前需隐去其中可能存在的真实个人信息或密钥。
- 上表引用的场景入口，以及它们引用的控制器、意图识别、数据库结构、内容目录和测试。
- G1 播放 bridge：默认查找项目根目录下的 `build/g1_companion_pcm_bridge`。其源码和构建配置尚未收到；官方 SDK 保持外部依赖，不复制 SDK 源码。

当前 `speech/requirements.txt` 仅声明 `dashscope>=1.25.17`。已收到代码还使用 `fastapi`、`pydantic`、`uvicorn`、`requests`；FastAPI 的文件与表单接口还需要 `python-multipart`。这些依赖的实际版本及其余场景依赖待核对，原依赖文件暂不改写。主机播放路径调用 `aplay`，联系家属脚本的健康检查调用 `curl`。

## 迁移时需要处理的本机约定

- `speech/run_server.sh` 写死原项目目录和 `speech/venv`，加载 `$HOME/.config/elder_companion/cloud.env`，设置端口 `8780`。
- 联系家属的两个启动脚本写死 `$HOME/github-product/g1-dex3-care-vla/speech`。
- 多数场景脚本使用当前环境的 `python3`，社交展示脚本则使用 `./venv/bin/python`，解释器选择尚未统一。
- 四场景的 `run_g1_demo.sh` 都先加载 `companion_recording_env.sh`，并追加老人 ID、会话日志和 `--record-mode live`。
- 社交展示脚本先刷新活动日程；确认目标数据库及写入行为后再执行。
- 联系家属启动脚本固定检查 `http://127.0.0.1:8780/health`。
- 原 README 同时包含早期 Windows、旧服药兼容接口和情绪联调内容，不能作为当前四场景的完整运行说明。

上述行为均保留原状，待源码和实际运行命令齐全后再作有针对性的调整。配置文件只记录路径和变量名，不导入密钥值。

## 验证状态

本批次执行文件内容一致性检查、Python AST 语法解析和 `bash -n`，不导入或执行业务模块。功能测试、HTTP 启动、云 ASR/TTS、数据库行为、真实拨号及 G1 录音/播放均未运行，当前文件集不足以完成这些验证。

后续继续按用户上传的文件分批导入和提交，保留两个版本的原有入口。未提供的源码不以占位实现补齐；机器人电脑上的现有工作区和其他成员改动保持原状。
