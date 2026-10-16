# 语音模块迁移记录

## 范围与来源

从用户提供的文本附件和源码包导入原项目 `/home/user/github-product/g1-dex3-care-vla` 中已收到的文件，保留 `speech/`、`care_console/`、相关根目录 `scripts/`，以及已收到的 `CMakeLists.txt`、`src/`、`tests/` 路径。此仓库当前承载语音、日常陪伴、护理工作台和已收到的动作/播放桥接源码，不包含完整机器人项目。

原项目的 `AGENTS.md` 保存为 `docs/upstream-project-rules.md`，用于保留原团队的控制边界、停止条件和协作约定；其中的历史训练路线、绝对路径和情绪模块状态不代表本仓库已经具备这些组件。

原始源码只统一 CRLF/LF 和文件末尾换行，没有修改函数、参数、启动流程或依赖声明。附件中的文件分隔标题、终端提示符、采集命令及“文件不存在”提示不属于源码，没有导入。

## 已收到的文件

- 服务及 G1 客户端：`speech/server.py`、`speech/speech_client.py`。
- 共享需求与会话模块：`speech/elder_need_registry.py`、`speech/decision_announcer.py`、`speech/companion_recording.py`、`speech/init_elder_need_db.py`。
- 共享老人/家属基表：`speech/data/init_db.py`，创建 `elderly_person`、`family_contact` 和 `contact_call_log`；若未找到名为 `王大爷` 的老人记录，会写入比赛示例老人和两名电话占位联系人。
- 动作客户端：`speech/robot_actions/action_client.py`、`speech/robot_actions/__init__.py`。
- G1 动作执行器：`scripts/g1_elder_companion_motion_executor.py`、`scripts/g1_elder_companion_custom_action_executor.py`，是动作客户端固定定位的两个脚本。
- 历史视觉情绪联调材料：`scripts/g1_elder_companion_emotion_demo.py`、`g1_elder_companion_emotion_preflight.sh` 及五个 `g1_elder_companion_emotion_*_run.sh`。它们未接入当前四个场景，保留原路径以记录原有独立联调链。
- 历史视觉情绪逻辑与测试：`speech/emotion_interaction.py`、`speech/emotion_dialogue.py`、两个 `speech/test_emotion_*.py`、`speech/test_entertainment_interrupt.py`，以及 `tests/` 下两个 emotion launcher 测试。它们属于同一条未接入四个现用场景的独立联调链；其中对话代码仍直接依赖已废弃且未迁移的 `scenarios/elder_companion`。
- G1 PCM bridge 源码快照：`CMakeLists.txt`、`src/g1_companion_pcm_bridge.cpp`、`src/g1_companion_pcm.hpp`、`src/README.md`、`tests/g1_companion_pcm_test.cpp`、`tests/assert_exit_64.cmake`、`tests/README.md`。bridge 明确列出的本地 C++ 输入已收到；根 CMake 仍属于未完整迁移的机器人项目。
- 内层语音包：`speech/speech/` 下 9 个 Python 文件，含 ASR、TTS、播放、预设、包客户端、直接语音接口及娱乐回复模板。
- G1 音频组件：`speech/g1_audio/` 下 6 个 Python 文件，含单次/连续录音、滚动 ASR、播放封装和娱乐打断。
- 照护咨询：`speech/scenarios/care_consultation_support/` 下 25 个 Python 文件和含 35 条知识卡的 `care_knowledge.json`。两份同名源码附件内容相同，只导入一次。
- 娱乐陪伴：`speech/scenarios/companion_entertainment/` 下 15 个 Python 文件，以及用户提供的 `content_catalog.json`、`news_scripts.json`；未导入音频素材。
- 娱乐展示验收：`speech/test_companion_entertainment_showcase.py`，包含 15 项分类与固定状态机 unittest，均已通过。
- 社交活动：`speech/scenarios/social_activity_support/` 下 21 个 Python 文件，包含普通版、展示版、日程脚本和三个 `video_baseline` 文件，全部保留原路径。
- 社交展示验收：`speech/test_social_activity_showcase.py`，包含原有用例及背景描述/具体活动查询的规则回归用例。
- 联系家属：`speech/scenarios/contact_family/` 下 11 个 Python 文件，包含语音/文字入口、电话后端、联系人逻辑与数据库访问、网页模拟通话服务和 `test_db.py`。
- 联系家属验收：`speech/test_contact_family_call_backend.py`、`speech/test_contact_family_dial_authorization.py`，分别包含 8 项后端测试和 11 项拨号授权测试，覆盖未创建输出目录的 real-client 接线。
- 项目根电话脚本：`scripts/g1_call_owner_once.sh`、`scripts/g1_contact_family_call.py`、`scripts/g1_phone_dial.py`，分别为 Shell 入口、G1/电话编排器和 Android HTTP 拨号 client。
- 语音服务启动及会话配置脚本：`speech/run_server.sh`、`speech/companion_recording_env.sh`。
- 四场景启动脚本：下表中的七个脚本。
- 护理工作台：`care_console/` 下 11 个运行 Python 文件、7 个 Python 测试、一个 Node 测试、6 个静态页面文件、`.gitignore` 和 `deploy/requirements.txt`。未收到其 README、审计/部署说明、systemd/Nginx 配置或任何 `runtime/` 内容。
- 原语音文档及依赖：`speech/README.md`、`speech/TEAM_USAGE.md`、`speech/requirements.txt`。
- 原项目规则快照：`docs/upstream-project-rules.md`。

合计保留 169 个原项目文件，其中 120 个位于 `speech/`、27 个位于 `care_console/`、12 个位于 `scripts/`、9 个位于项目根的 CMake/src/tests 路径，以及 1 份转换保存的上游 `AGENTS.md` 规则快照；包含 130 个 Python 文件和 16 个 Shell 脚本。第二批再次提供的 `speech/speech/service.py` 与首批内容一致，没有覆盖出不同版本。

## 现用场景与废弃场景

现用场景以用户确认的四个目录为准：`care_consultation_support`、`companion_entertainment`、`social_activity_support`、`contact_family`。

用户已明确确认以下三个场景废弃：`elder_companion`、`caregiver_chat`、`short_companion_chat`。当前收到的源码未包含这三个场景目录，没有将其纳入现用场景入口。后续若收到这些目录，先检查共享依赖，再单独归档并保留来源。

第二批附件主要包含公共包与 G1 音频组件，不包含额外的 `scenarios/` 目录。`$HOME/.config/elder_companion/cloud.env` 是现有脚本共用的配置路径，不因与废弃场景同名而删除或改名。

本批的七个 `g1_elder_companion_emotion_*` 文件及新增的情绪互动逻辑/测试，都是未接入当前四个场景的历史独立视觉情绪/实机联调材料。它们的文件名前缀或直接导入与已废弃场景有关，但没有据此删除、重新导入废弃目录或把它们当成当前默认入口；仅在保留的原 `speech/README.md` 中存在 `emotion_demo.py` 与 `emotion_preflight.sh` 的手工示例。详细边界见[历史视觉情绪互动链说明](EMOTION_MODULE.md)。

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

以下描述脚本和源码内容，未启动语音场景。照护咨询通过 `g1_voice_demo.py --showcase` 切换展示模式；娱乐陪伴和社交活动均有独立的 `g1_voice_demo.py` 与 `g1_showcase_demo.py`；联系家属当前语音主入口为 `g1_voice_demo.py`，另有两个文字输入演示入口。

| 场景 | 已导入的启动脚本 | 脚本引用的 Python 入口及状态 |
| --- | --- | --- |
| 照护咨询 | `run_care_api.sh` | `care_api.py`，已收到 |
| 照护咨询 | `run_g1_demo.sh` | `g1_voice_demo.py`，已收到 |
| 娱乐陪伴 | `run_g1_demo.sh` | `g1_voice_demo.py`，已收到 |
| 娱乐陪伴展示 | 尚未收到专用启动脚本 | `g1_showcase_demo.py`，已收到 |
| 社交活动 | `run_g1_demo.sh` | `g1_voice_demo.py`，已收到 |
| 社交活动展示 | `run_g1_showcase.sh` | 先运行 `refresh_activity_schedule.py`，再运行 `g1_showcase_demo.py`，均已收到 |
| 联系家属 | `run_g1_demo.sh` | `g1_voice_demo.py`，已收到，默认模拟拨号后端 |
| 联系家属模拟通话 | `run_mock_call_server.sh` | `mock_call_server.py`，已收到；当前语音主链未接入 |

脚本均位于 `speech/scenarios/<场景目录>/`。本批已补齐娱乐两个语音入口顶层导入的 `robot_actions.RobotActionClient`，两入口的 `--help` 均能加载并正常退出；未启动语音或机器人流程。

照护咨询的 API、文本和 G1 语音入口的能力及收尾行为不同，详见 [照护咨询模块说明](CARE_CONSULTATION.md)。JSON 知识检索模块也尚未在本批控制器主链中接入，不把知识库文件已导入等同于运行链已使用。

娱乐陪伴版本、媒体目录与 JSON 清单的关系见 [娱乐陪伴模块说明](COMPANION_ENTERTAINMENT.md)。当前两个 G1 入口及文字入口通过 `LocalMediaLibrary` 扫描实际媒体目录；`content_catalog.json` 由另一条 `EntertainmentSession` 路径读取，保留原样，用途不据此定为废弃。

社交活动版本、内存演练及数据库脚本见 [社交活动模块说明](SOCIAL_ACTIVITY_SUPPORT.md)。三个 `video_baseline` 文件保留原状，其中视频语音入口仍导入当前 `showcase_controller` 和 `showcase_intent`，未把这些文件认定为独立冻结基线或另一个现用场景。

联系家属入口、联系人绑定与拨号授权见 [联系家属模块说明](CONTACT_FAMILY.md)。当前语音入口只开放 `safe_stub` 和 `real`；后端类还保留会调用外部脚本的 `dry_run`，本轮没有执行外部脚本。旧网页模拟通话函数仍在源码中，当前主链不调用，不能以启动网页服务推定已接入。

## 动作执行器与历史视觉情绪链

`speech/robot_actions/action_client.py` 固定调用项目根的两个执行器。`motion` 请求仅接受已确认的 `emotion_dialogue_motion_request`，动作 ID 限制为 17（鼓掌）和 25（挥手）；`custom` 请求仅接受已确认的 `emotion_dialogue_custom_action_request`，动作名限制为 `open_palm_invite`。动作客户端将 `greeting`、`goodbye`、`celebrate` 映射到前者，将 `present`、`acknowledge` 映射到后者。

当前直接使用动作客户端的入口是娱乐普通版、娱乐展示版和社交活动展示版。照护咨询、联系家属和社交普通版没有该客户端引用。客户端默认 `dry-run`；只有同时指定执行模式与写入确认时才启动执行器。动作客户端的默认解释器与网卡仍是原机器的 `/home/user/miniconda3/envs/tv/bin/python` 和 `enp3s0`，可由 `G1_ACTION_PYTHON`、`G1_ACTION_INTERFACE` 覆盖。

两个执行器会在实际运行时初始化 Unitree SDK 和 DDS：motion 路径可调用 ArmAction 并向 Dex3 手指 topic 写入，custom 路径会注册自定义动作 API 并复用同一套 Dex3 控制逻辑。因此源码已收到不代表 SDK、网卡、G1/Dex3 兼容性或动作效果已验证。本轮未运行其任何 CLI，`--inspect` 也没有运行，因为它会订阅 DDS。详细文件范围、门控和历史视觉情绪材料见 [G1 动作执行器说明](ROBOT_ACTIONS.md)。

## 语音调用路径

1. 外层 `speech/speech_client.py` 的 `SpeechClient` 请求 `/health`、`/speak` 和 `/asr`，并提供 G1 录音与 PCM bridge 播放接口。内层 `speech/speech/client.py` 是另一个 HTTP 客户端，由内层包的 `__init__.py` 导出；二者保留原有接口，不合并或重命名。
2. 内层 `speech/speech/service.py` 直接调用云 TTS 和 `playback.play_wav()`。后者在 Windows 使用 `winsound`，其他平台优先使用 `G1_WAV_PLAYER` 指定的播放器，再回退 `aplay`/`paplay`；不能将此路径与外层客户端的 PCM bridge 播放等同。兼容 `listen()` 引用旧项目的 `asr.recorder` 和 `asr.recognize`，不据此认定四场景仍依赖旧录音链。
3. `g1_live_asr.py` 的 `G1RollingASR` 复用持续麦克风流，把重叠 WAV 窗口交给传入客户端的 `transcribe()`；不据此将其描述为厂商实时流式 ASR API。

当前客户端 `speak_g1()` 读取服务返回的 `audio_path`，并在客户端文件系统中查找 WAV。这要求客户端能访问对应文件路径；将服务移到另一台机器时，仅更改 URL 不能保证播放可用。

## 护理工作台与会话日志链接

`care_console.link` 是当前已确认的唯一场景接入点。四个普通 `run_g1_demo.sh` 会先 source `speech/companion_recording_env.sh`，后者创建本轮 `care-session.jsonl` 路径，并以 `--elderly-id`、`--interaction-log` 调用 `python3 -m care_console.link`；社交展示脚本不走这条链。链接器支持尚未创建的日志文件，按场景身份和日志路径在控制台中预先登记来源。

链接器只接受无路径、无认证信息的 `http://127.0.0.1:<port>` 或 `http://localhost:<port>` 地址，禁用代理和重定向。实际链接会读取控制台概览和来源列表，并向本机工作台写入老人绑定和日志来源；它不是只读检查。`companion_recording_env.sh` 使用 `set -e`，控制台未就绪、共享数据未准备或登记失败都会阻止普通 G1 入口继续启动。

工作台启动入口为 `python -m care_console`，其模块顶层会解析参数并启动 Uvicorn，不可作为普通导入检查目标。`create_app()` 被调用后会创建或迁移控制台自己的 SQLite 文件，默认还会启动同步任务；本轮没有调用它。工作台只读访问默认的 `speech/data/elder_companion.db`，需要其中的老人基表和 `elder_need` 表存在；它不修改该共享数据库。

`care_console/deploy/requirements.txt` 固定 FastAPI、Uvicorn 和 Pydantic 的运行时版本，保留为工作台独立依赖清单，不并入 `speech/requirements.txt`。`care_console/runtime/` 包含数据库、认证和运行产物，已在根 `.gitignore` 中整体忽略；其余认证文件也应保存在仓库外。

## 共享基表初始化

`speech/data/init_db.py` 是联系家属与照护场景共用的基础初始化脚本。它创建 `elderly_person`、`family_contact`、`contact_call_log` 三张表；若未找到名为 `王大爷` 的老人记录，会写入一名比赛示例老人和两名授权联系人。两个电话号码均为 `REPLACE_WITH_*_PHONE` 占位符，没有真实电话号码或密钥。

`.gitignore` 只为该初始化源码保留例外，`speech/data/` 中生成的 SQLite 文件仍被忽略。直接运行原脚本会在同目录创建 `elder_companion.db`；本次迁移没有在仓库生成或导入该文件，只使用临时 SQLite 路径验证过脚本。

该脚本使用 `CREATE TABLE IF NOT EXISTS`，以老人姓名判断是否已写入示例数据。它不会迁移旧 schema，也不会为已有同名老人补写缺失联系人。外键依赖每个 SQLite 连接启用 `PRAGMA foreign_keys = ON`。照护的个人档案种子固定使用 `elderly_id=1`；社交的一些控制器和入口也默认该 ID，且社交表不对该列建立外键。已有数据库中的同名老人若不是这个 ID，需要先核对身份映射。

若在受控的空演示库中做完整初始化，基础表应先于 `speech/init_elder_need_db.py`、照护场景的会话/记忆/个人档案初始化脚本执行；社交活动的 `init_activity_db.py` 可独立执行，之后再按需要执行活动种子和日程脚本。这里仅记录依赖顺序，并不在仓库中创建数据库。

## 还缺少的直接依赖

- 联系家属的 Shell 入口、编排器和 Android client 已收到；Shell 仍固定依赖原机器的 `speech/venv/bin/python`。编排器的原有自动测试尚未收到，实际编排和电话链仍未验证。
- 当前活动 SQLite 未初始化或填充；内存演练与已收到的展示测试不替代真实 SQL、报名记录、工作人员通知及日程刷新验收。
- 娱乐陪伴的实际媒体。当前仓库的音乐、新闻、戏曲目录均为空；展示入口检查至少两首音乐、一条新闻、一段戏曲。展示 unittest 已收到，打断等其他验收脚本仍未上传。
- 动作执行器源码已收到：项目根 `scripts/g1_elder_companion_motion_executor.py`、`scripts/g1_elder_companion_custom_action_executor.py`。仍缺可验证的 Unitree SDK/版本、DDS 与设备网络配置、现场安全前置条件和实机兼容性结果；动作客户端默认引用原机器的 `tv` Python 环境和 `enp3s0`，源码可通过 `G1_ACTION_PYTHON`、`G1_ACTION_INTERFACE` 覆盖。
- 历史情绪对话：`emotion_dialogue.py` 与 `test_emotion_dialogue.py` 仍缺 `speech/scenarios/elder_companion/elder_chat_client.py`、`end_request.py`，所以不能导入或运行；历史 launcher 还缺 wake-mode 脚本、两个本机虚拟环境、视觉模型和演示视频。`emotion_interaction.py --g1-bridge` 所需的固定 phrase bridge 源码也未收到。详见[历史视觉情绪互动链说明](EMOTION_MODULE.md)。
- 共享老人/家属基表初始化源码已收到，但仍缺已有 SQLite 数据库的迁移、同名老人联系人回填和稳定老人 ID 对齐方案。`init_elder_need_db.py` 只创建共享需求表及索引；照护完整链仍需其余会话、记忆和个人档案表及受控演示种子。
- 护理工作台源码、静态页、测试和运行时依赖清单已收到；尚缺原 README、审计/部署文档、systemd/Nginx 配置、真实控制台数据库、认证文件和受控启动配置。控制台与四场景的真实日志登记尚未验收。
- G1 播放 bridge：默认查找项目根目录下的 `build/g1_companion_pcm_bridge`。主程序、相邻头文件、核心测试和缺确认参数的 CTest 辅助脚本已收到；根 CMake 所引用的其余 C++ 项目文件仍未迁移，当前不能配置或构建。头文件静态确认的条件是 16 kHz、单声道、16 位 PCM、32 MiB 实际数据上限；实现没有 15 秒时长上限。官方 SDK、`jsoncpp` 和真实设备配置保持外部依赖，不复制 SDK 源码。娱乐打断模块仍要求最终二进制支持 `--allow-interrupt`、`SIGUSR1` 和对应 JSON 回执，不能用任意同名播放器代替。
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
- `care_console` 默认监听 `127.0.0.1:8766`，控制台入口还可接收工作台数据库、交互数据库、允许主机、部署模式和认证文件路径。未提供认证文件时云部署模式会拒绝启动；本轮没有启动任何工作台服务。
- 社交展示脚本先刷新活动日程；确认目标数据库及写入行为后再执行。
- 社交 `seed_demo_activities.py` 会清空四张活动相关表；`refresh_activity_schedule.py` 虽不删除历史场次，也会更新已匹配场次的人数、容量、截止时间和状态等字段。本轮均未执行。
- 联系家属启动脚本固定检查 `http://127.0.0.1:8780/health`。
- 根目录 `scripts/g1_call_owner_once.sh` 默认使用配对手机的私网 URL、原机器绝对 token 路径和 `speech/venv/bin/python`。`G1_PHONE_URL`、`G1_PHONE_TOKEN_FILE`、`G1_PHONE_RUNS_DIR` 分别覆盖 URL、token 路径和输出父目录，解释器仍固定。它将参数交给 `g1_contact_family_call.py`：无参数时向编排器传确认选项，Shell 本身不进行交互确认；编排器再要求现场精确语音“确认拨号”。
- `playback.py` 的旧播放器默认路径为 `/home/unitree/medication_robot/bin/g1_play_wav`，可用 `G1_WAV_PLAYER` 覆盖。
- 麦克风模块用 `192.168.123.164` 作为网卡选择目标，接收 `239.168.123.161:5555` 的音频多播；与上游规则中的设备地址不完全一致，保留原值，等待现用机器验证。
- 两个动作执行器默认 DDS 网卡为 `enp3s0`；`action_client.py` 默认用原机器的 `tv` Python 启动它们。历史视觉情绪的 dialogue wrapper 也固定这些原机路径，并额外依赖视觉虚拟环境、模型、PCM bridge、wake-mode 脚本、云配置和本机护理工作台；它们不作为四个现用场景的默认入口。
- 收到的根 `CMakeLists.txt` 默认将 `UNITREE_SDK2_ROOT` 指向 `/home/user/github-product/unitree_sdk2`，架构为 `x86_64`；这是可覆写的构建默认值，不是凭据。当前仓库只有其中一小部分目标源码，不能对根目录运行 CMake 配置。
- 原 README 同时包含早期 Windows、旧服药兼容接口和情绪联调内容，不能作为当前四场景的完整运行说明。

上述行为均保留原状，待源码和实际运行命令齐全后再作有针对性的调整。配置文件只记录路径和变量名，不导入密钥值。

## 验证状态

当前累计 123 个 Python 文件、16 个 Shell 脚本，执行导入内容一致性检查、Python AST 语法解析、`bash -n` 和三份 JSON 检查。重复的 `service.py` 和照护咨询重复源码附件单独核对一致。没有执行会话配置、刷新数据库、监听麦克风或启动播放。

本批九个动作执行器/情绪联调文件在解压前通过路径与链接类型检查，导入后逐文件与附件核对一致。三个 Python 文件只做 AST 语法解析，六个 Shell 文件只做 `bash -n`；静态审查未发现凭据字面量。没有导入或运行执行器 CLI、DDS、Unitree SDK、相机、视觉模型、云服务、PCM bridge、wake-mode、护理工作台或任何机器人动作。

本批七个历史情绪逻辑/测试 Python 文件在解压前通过路径与链接类型检查，导入后逐文件与附件核对一致，并完成 AST 语法解析。静态审查核对了事件校验、确认播放、娱乐打断和 launcher 门控；没有运行测试或 launcher。`test_entertainment_interrupt.py` 会创建本地 fake bridge 并启动进程，两个 launcher 测试会调用 Shell 拒绝分支；它们不替代真实 bridge、SDK、DDS、麦克风或现场播放验收。归档附带的两份长 Markdown 原件因含部署端点、内部路径和个人档案描述而未原样推送；没有发现密钥值，并以脱敏的[历史视觉情绪互动链说明](EMOTION_MODULE.md)记录其迁移边界。

两个 PCM bridge 归档合计七个文件在解压前通过路径和链接类型检查，导入后逐文件与附件核对一致。静态审查确认主程序支持 `--dry-run`、精确确认参数以及 `--allow-interrupt`/`SIGUSR1` 的 JSON 回执契约；相邻头文件的 WAV 校验与分块/停止逻辑、核心测试的内存级覆盖也已审阅。确认播放路径才会初始化 SDK；根 CMake 的大量本地依赖仍未收到。本轮没有运行 CMake、编译、CTest、bridge 可执行文件、SDK 或设备调用。

护理工作台附件在解压前通过路径和链接类型检查，导入后逐文件与附件一致。18 个工作台 Python 文件和静态资源检查通过；除会直接启动 Uvicorn 的 `care_console.__main__` 外，10 个运行模块在拦截 SQLite、子进程和 HTTP 调用的条件下导入成功。工作台原有 Node UI 测试 14 项全部通过。选择运行的 84 个 Python 测试中 83 项通过、1 项失败：删除后重建同一路径 JSONL 的恢复测试依赖 inode 复用，本环境检测到新 inode 后按源码重读仍保留的无效首行，因而持续报告“记录被拒绝”。该失败可重复，源码和原断言均未修改。未运行会启动 loopback server、Shell 子进程或 `python -m care_console` 子进程的两份工作台测试；没有启动 Uvicorn、创建仓库数据库、访问真实共享库或业务网络。

本批还在 Python 3.12.14 下验证了 9 个模块导入：四个新共享模块，以及 `care_controller`、`g1_voice_demo`、`care_api`、`text_demo`、`test_showcase_offline_chain`。因当前机器缺少 `requests`，仅向 `/tmp/g1-care-import-deps-batch4` 安装 `requests==2.34.2` 及其依赖用于检查；这不是原机器人环境的版本声明，也未修改 `requirements.txt`。检查拦截数据库、出站连接和子进程调用；请求库的本地 IPv6 能力探测被拦截，业务模块未尝试这些操作。未调用任何场景函数、初始化函数或测试 `main()`。

已尝试 `python3 speech/scenarios/care_consultation_support/test_showcase_offline_chain.py`，退出码为 1，原因是前置检查找不到 `speech/data/elder_companion.db`；5 段场景验收均未执行。基础初始化源码现已导入，但为避免在仓库创建数据文件，没有按默认路径执行；完整照护链还需要需求、会话、记忆和个人档案等表及种子。因此没有重复运行同一个会在前置检查停止的命令。

娱乐陪伴的 12 个控制与媒体模块导入通过；两个语音入口前批因缺 `robot_actions` 受阻，本批补齐真实动作模块后，分别执行 `--help` 加载并退出成功。当前云环境没有 `requests`，展示分类模块只在启用云 LLM 时要求该依赖，所以规则模式仍可导入和测试。新闻音频生成脚本只做静态检查，未导入或执行。前批已运行原有规则脚本的 14 个样例及文字入口的 5 轮输入；媒体为空时返回 `empty`/`not_found`，停止指令正常结束，未验证实际播放。

本轮执行 `test_companion_entertainment_showcase`：15 项实际执行，15 项通过、0 失败、0 错误、0 跳过。展示分类入口现按当前状态收敛模型和规则结果，固定流程外的输入返回 `other`；控制器仍保留执行前状态门禁。测试只使用内存 `FakeLLM` 和规则，没有业务网络、数据库、媒体、子进程或机器人动作调用。

社交活动的 21 个模块导入通过，普通语音、展示语音和文字展示入口的 `--help` 均正常退出。初次导入时，`text_showcase_demo.py --demo-data --scripted --no-llm` 的背景描述会误触发查询、打断已选活动上下文；本轮将具体活动查询限定为显式问法，背景描述现会保持 `other`，并保留正常“有没有唱歌活动”“那唱歌呢”查询。

本轮执行 `test_social_activity_showcase`：17 项实际执行，17 项通过、0 失败、0 错误、0 跳过。`test_background_speech_is_ignored` 现覆盖修复后的背景描述处理，新增回归测试保留具体活动的显式问法。当前云环境没有安装 `requests`，所以规则分类改为仅在启用云 LLM 时要求该依赖；套件使用内存仓库及模型 stub，没有业务网络、数据库或子进程调用。

联系家属的 10 个模块在拦截数据库、业务网络和子进程调用的条件下真实导入通过，三个演示入口的 `--help` 正常退出。请求库的本地 IPv6 探测单独拦截；没有业务调用尝试。`mock_call_server` 导入创建了忽略目录 `speech/runtime/mock_calls/`，未启动监听。`test_db.py` 顶层会查库并打印完整老人/联系人，因此只做语法和源码一致性检查，不导入或执行，也未使用全仓自动测试收集。没有创建仓库中的老人数据库。

前批在 Python 3.12.14 下明确选择两份联系家属原有 unittest，18 项实际执行：17 项通过、0 断言失败、1 错误、0 跳过，合并执行退出码为 1。其中 `test_dry_run_prepare` 在检查根目录 `scripts/g1_call_owner_once.sh` 时因文件缺失抛出 `CallBackendError`。本批导入用户提供的真实 Shell 源码后，重跑同样两份原套件：18 项全部通过、0 失败、0 错误、0 跳过，退出码为 0。当前优化新增未创建输出目录的后端回归用例后，联系家属两套测试合计为 19 项，全部通过。文件存在性条件已满足，`subprocess.run` 仍由测试 mock，并未执行 Shell 或编排器。

两个原有真实模式后端用例使用 `_run_phone_client` mock；新增输出目录用例 mock `subprocess.run`。授权状态用例使用原有合成联系人，电话字段为占位文本。审计未发现数据库、业务网络或子进程调用尝试，未读取电话 token 或创建老人数据库。测试尚未覆盖 `safe_stub`、owner 绑定、语音入口整条授权调用链和 Android client 的实际行为。

本批将 `init_db.py` 的 `DB_PATH` 临时指向独立 SQLite 文件，连续运行两次后确认三张表、1 名示例老人和 2 名联系人均未重复写入；`contact_family/db_access.py` 的联系人别名查询、通话日志写入和读取均可在同一临时库中工作。临时连接中无效外键写入触发 `IntegrityError`。审计没有发现业务网络或子进程调用，且没有在仓库创建数据库文件。

新收到的 Android client 只导入定义，未调用 `run()`、`main()` 或 HTTP/写盘函数；模块导入通过，没有数据库、网络或子进程调用。静态核对发现真实后端预先创建输出目录，而 client 的 `_write_result()` 要求新建同一路径，存在 `FileExistsError` 冲突。HTTP 操作先于结果写盘，故非零退出不证明未发拨号请求。该冲突和错误回执字段的局限已记录在联系家属说明，本轮未进行端到端复现或修改。

本轮补入 `g1_contact_family_call.py`，其定义导入、Python 3.10 语法和与附件的一致性检查均通过。用临时目录和注入的 mock 语音、电话、PCM 接口验证了 `dry_run`、`preflight`、未获现场确认和后端接受四条路径；没有运行 Shell、PCM bridge、G1 语音、手机 HTTP 或真实拨号。该编排器为 Android client 使用 `phone-preflight`、`phone-dial` 子目录，因此 Shell → 编排器 → client 这条链没有复用同一个输出目录；当前 `g1_voice_demo --call-backend real` 仍走直连 client 的冲突路径，未改动。

HTTP 启动、云 ASR/TTS、数据库业务行为、真实拨号及 G1 录音/播放均未验证。四个场景主体已收到，但仍缺少公共依赖、相关服务、完整 C++ 构建上下文和运行配置，不能认定项目可独立运行。

后续继续按用户上传的文件分批导入和提交，保留两个版本的原有入口。未提供的源码不以占位实现补齐；机器人电脑上的现有工作区和其他成员改动保持原状。
