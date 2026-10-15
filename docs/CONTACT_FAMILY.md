# 联系家属模块说明

## 导入范围与入口

目录为 `speech/scenarios/contact_family/`，已导入 11 个 Python 文件、`run_g1_demo.sh` 和 `run_mock_call_server.sh`。两份原测试位于 `speech/test_contact_family_call_backend.py` 和 `speech/test_contact_family_dial_authorization.py`；本轮补入根目录 `scripts/g1_call_owner_once.sh` 和 `scripts/g1_phone_dial.py`。所有业务逻辑和测试断言保留原样。

| 入口 | 源码实际行为 |
| --- | --- |
| `g1_voice_demo.py` | G1 全语音入口，执行联系人查询、联系人确认、电话准备、最终拨号授权和通话日志；默认 `safe_stub` |
| `text_demo.py` | 文字参数演示，联系人确认后打印模拟接通结果并写入 `connected_demo` 日志，不调用电话后端 |
| `contact_family_db_demo.py` | 文字参数加主机 TTS 的演示，固定连接 `http://127.0.0.1:8780`，使用 `play_on_host=True`，模拟接通并写库 |

不能仅凭文件名把它们直接对应为比赛版和完整版；以上是本批源码能确认的三个入口及其行为。`text_demo.py` 和数据库演示也需要真实 SQLite 表和老人、联系人数据，并非独立的无依赖演示。

`g1_voice_demo.py` 默认老人 ID 为 1，可用 `--elderly-id` 或 `--elder-id` 指定。使用 `--record-log` 时必须显式提供老人 ID；入口接入公共会话记录、ASR 和语音回执。日志中的播放返回值不证明现场实际听到声音。

## 当前语音主流程

主流程先检查语音服务，再读取当前老人，随后执行：

```text
G1录音与ASR
→ 联系家人意图识别
→ 数据库匹配已启用、已授权的联系人
→ 联系人确认
→ 电话准备
→ 最终拨号授权
→ 通话后端
→ SQLite服务记录
```

联系人不明确时允许补问一次；联系人确认与最终拨号授权各有最多两次机会。取消、未获明确确认、联系人不匹配、绑定失败、准备失败等分支可能写入通话日志，不能把运行演示当作只读检查。

`ContactFamilySession` 只处理意图、联系人匹配和会话状态，不负责 ASR、TTS 或实际拨号。联系人确认接受“对”“是的”等规则表达，优先检查否定；最终拨号授权使用另一套更严格的规则。

最终授权会去除空白和指定的常见中英文标点，只有剩余内容精确等于“确认拨号”才允许继续。“好的”“可以”“确认”均不授权；“取消”“取消拨号”“不拨打”“不打了”“算了”“不用了”为明确取消，其余输入仍等待授权。

## 电话后端与授权边界

`ContactCallBackend` 位于 `call_backend.py`。类支持三种模式，构造函数默认 `dry_run`；语音入口的 `--call-backend` 当前只开放 `safe_stub` 和 `real`，入口默认值为 `safe_stub`。

| 模式 | `prepare()` | `dial()` |
| --- | --- | --- |
| `safe_stub` | 直接返回本地准备完成，不调用电话脚本、不读取 token | 返回模拟结果，`external_dial_requested=False` |
| `dry_run` | 执行根目录 `scripts/g1_call_owner_once.sh --dry-run`，检查返回 `planned` 且未请求外拨 | 本地返回计划结果，不执行电话脚本 |
| `real` | 执行根目录 `scripts/g1_phone_dial.py --preflight` | 读取 token，执行同一 client 并传入 `--confirm-g1-phone-dial` |

默认 `safe_stub` 仅限制电话后端。完整语音入口仍会访问语音服务、使用 G1 录音和播放、读取并写入数据库。它不等于整个场景的离线模拟。

真实模式要求 `G1_PHONE_URL`、可用的电话 client，以及 `G1_PHONE_TOKEN_FILE` 指向的非空 token 文件；默认 token 路径为 `$HOME/.config/g1-phone-dial/token`。这些配置由部署环境提供，不应把 token 内容写进仓库。

真实模式通过 `phone_binding.binding_summary()` 检查 `G1_PHONE_OWNER_DB_CONTACT_ID`。只有当前选中联系人的数据库 ID 与该配置一致才允许进入后续准备，映射目标固定为 Android 联系人 `owner`；当前代码没有把数据库中的任意电话号码传给电话 client。

最终授权和联系人绑定由 `g1_voice_demo.run_scene()` 执行，`ContactCallBackend.dial()` 本身不验证会话状态或联系人绑定。直接调用后端类的方法不具备入口的完整授权检查。

真实准备和拨号会创建 `runs/contact-family-phone/` 下的输出目录。代码解析 client 的 JSON 合同输出，也兼容旧 `key=value` 文本。`ok` 或子进程退出码为 0 仅说明请求流程完成；主入口对 `operation_state=accepted` 播报正在联系，不能将其解释为电话已经接通。

根目录两个电话脚本已收到。独立 Android client 使用 HTTP，不直接调用 ADB；Shell 引用的 `scripts/g1_contact_family_call.py` 尚未收到。源码事实和静态接线问题见下节，真实 HTTP 和手机端实现均未验证。

`real_phone_backend.py` 另保留一个 `RealPhoneBackend` wrapper，调用 `g1_call_owner_once.sh` 的 `--dry-run`、`--preflight` 或无参数入口。当前主语音入口没有导入或使用这个 wrapper，不能把它与当前 `ContactCallBackend` 主链混为一条已验证流程。

## 根目录电话脚本与接线问题

`scripts/g1_call_owner_once.sh` 固定使用 `speech/venv/bin/python`，启动尚未收到的 `scripts/g1_contact_family_call.py`。它保留原机器的私网手机 URL 和绝对 token 文件路径，可用 `G1_PHONE_URL`、`G1_PHONE_TOKEN_FILE`、`G1_PHONE_RUNS_DIR` 分别覆盖手机 URL、token 文件和输出父目录；源码没有包含 token 值。

Shell 接受 `--dry-run` 或 `--preflight` 并转发给编排器，无参数时直接传入 `--confirm-g1-contact-family-call` 和 token 文件路径。Shell 本身没有交互确认；旧 `RealPhoneBackend` 中“脚本自身仍会要求现场确认”的注释不能由这份 Shell 证实，下层是否另有确认需收到编排器后核对。Shell 只创建输出父目录，不提前创建本次运行的输出子目录。

`scripts/g1_phone_dial.py` 只依赖 Python 标准库，CLI 必须从三个互斥动作中选一个：

| 动作 | 源码行为 |
| --- | --- |
| `--dry-run` | 校验 URL、生成 `planned` 结果并写入输出目录，不请求手机 |
| `--preflight` | 请求 `GET /health`，校验 HTTP 200、schema、`kind=health`、已配置和权限就绪；不传 token、不请求拨号 |
| `--confirm-g1-phone-dial` | 要求至少 32 字符且无空白的 token，向 `/dial` 发送带 Bearer token 的 POST，固定 `contact_id=owner` |

URL 校验要求 `http`、私有或回环 IP 字面量和显式端口，拒绝凭据、额外路径、query 和 fragment。这是初始 URL 的代码检查，未验证 HTTP 服务、响应或手机端行为。请求超时设为 3 秒；拨号结果要求 HTTP 202 和匹配的 `accepted` 合同，不表示实际接通。

独立 client 使用 `g1_android_phone_dial_v1` schema，后端示例中的编排器合同为 `g1_contact_family_call_v1`；当前后端解析器提取字段但不强制校验 schema，不能将两者视为已经核对完成的同一个协议。

静态核对发现输出目录约定冲突：`ContactCallBackend._new_output_dir()` 先创建本次输出目录，随后 client 的 `_write_result()` 再使用 `mkdir(..., exist_ok=False)` 创建同一路径。两份当前源码直接接线时会发生 `FileExistsError`；client 的 `main()` 只捕获 `DialError`，不处理该异常。

client 在 HTTP 操作后写结果，因此真实预检可能已经请求 `/health` 才写盘失败；单独调用真实拨号路径时，也可能已发送 `/dial` 请求再报错。正常语音入口会先准备，准备失败会停止后续拨号。上述冲突由源码静态确认，本轮没有请求手机或进行端到端复现，也没有修复原逻辑。

失败回执还有限制：client 的 `DialError` 路径以 `arguments.confirmed` 填写 `external_dial_requested`，即使 URL 校验失败、尚未发送 HTTP，也可能为 `True`；`main()` 的错误 stdout 又不包含这个字段。失败退出或该字段均不能单独证明请求是否实际发出。原有后端测试 mock 整个 client 调用，未覆盖这些接线问题。

## 保留的网页模拟通话路径

`call_service.py` 的 `MockCallService` 是 HTTP client，默认地址为 `http://127.0.0.1:8790`。它支持创建来电、轮询接听状态、挂断、标记未接听，以及上传老人录音、轮询并下载家属音频。下载音频会创建临时 WAV 文件。

`mock_call_server.py` 提供 FastAPI 服务及 `/family` 家属网页。直接运行文件会监听 `0.0.0.0:8790`。该演示服务的 API 没有实现身份鉴权；来电和音频索引保存在内存，音频文件写入 `speech/runtime/mock_calls/`，重启不会从目录恢复内存状态。网页使用浏览器麦克风录音；非 WAV 上传依赖 `ffmpeg` 转换为 16 kHz、单声道、16 位 PCM WAV。

`g1_voice_demo.py` 中仍保留 `perform_mock_call()` 和 `run_simple_voice_call()`：可创建网页来电，播放铃声，调用 `g1_audio/g1_mic_recorder.py` 录制老人语音并上传，再播放家属回复。当前 `run_scene()` 没有调用这些函数，启动 mock server 不会自动让主入口使用网页通话。

保留路径还有一处静态可见的调用缺口：`perform_mock_call()` 在已接听分支调用 `run_simple_voice_call()` 时，没有提供其必需的 `announce_decisions` 关键字参数。该路径若直接启用会触发 `TypeError`，本轮保留原样。当前 `safe_stub`、`real` 主流程不走此分支。

`--call-result` 仅为旧启动脚本保留兼容，源码明确不再控制呼叫结果。`--followup-seconds`、`--call-timeout`、`--call-rounds`、`--elder-turn-seconds`、`--family-turn-timeout` 仍被接收并传入 `run_scene()`，但当前主流程未使用这些参数；不能据此宣称当前入口已支持网页多轮通话。

## 数据库、导入副作用与依赖

`db_access.py` 固定使用 `speech/data/elder_companion.db`，这仍是共享数据路径，不随废弃的同名场景删除。本批没有建表或种子脚本，需要已有的 `elderly_person`、`family_contact` 和 `contact_call_log`。

联系人查询只返回 `authorized=1` 且 `enabled=1` 的记录，按主要联系人优先、ID 升序排列，使用关系、姓名、JSON 别名在输入文字中做子串匹配。查询老人时要求 `enabled=1`。`create_call_log()` 写入老人 ID、联系人 ID、原始需求文字、关系、确认结果和状态；当前主语音入口不把最终拨号授权语句写入这条服务日志。

SQLite 连接使用普通可写连接。数据库文件不存在且父目录存在时，连接可先创建空文件再在查询时失败；缺库检查不能通过直接运行演示或导入数据库测试完成。

| 文件 | 导入时的行为 |
| --- | --- |
| `mock_call_server.py` | 顶层创建 `speech/runtime/mock_calls/`，定义应用和路由；导入本身不启动监听 |
| `test_db.py` | 无主入口保护，导入就连接数据库、执行查询并打印老人及联系人完整字典，可能包含完整电话 |
| 其余本批模块 | 本文件顶层主要为定义、常量和导入；两个语音相关入口还调整模块搜索路径，业务流程由显式调用触发 |

`test_db.py` 不应作为普通安全导入目标或对真实数据库自动收集执行。它没有自动断言，也不能将其打印输出视作功能测试通过。

本模块的第三方 Python 依赖包括 `requests`、`fastapi`、`uvicorn`、`pydantic`。语音入口另依赖已有 `speech_client.py`、`decision_announcer.py`、`companion_recording.py` 和 G1 音频组件；网页非 WAV 音频转换依赖系统 `ffmpeg`。这些导入关系不代表仓库当前依赖清单已经覆盖全部运行要求。

## 尚待补齐与验证

- 仓库根目录 `scripts/g1_contact_family_call.py` 及其依赖；Shell 还固定使用本机 `speech/venv/bin/python`。
- 老人基表、家属联系人表、通话日志表的建表脚本和匿名演示数据。
- 用户确认各入口的现用、比赛或归档定位，以及网页模拟通话路径是否计划重新接入。
- 真实 SQLite 业务链、网页音频交换、云 ASR/TTS、G1 音频、Android 预检、拨号请求与实机接通情况。

## 本轮验证结果

- 11 个 Python 文件通过 Python 3.10 语法解析，内容与附件一致，仅统一文本换行。
- 除 `test_db.py` 外的 10 个模块真实导入成功，未尝试业务网络、数据库或子进程调用。请求库的本地 IPv6 能力探测单独拦截；`mock_call_server` 按源码创建了忽略的运行目录，没有启动服务。
- `g1_voice_demo.py`、`text_demo.py`、`contact_family_db_demo.py` 的 `--help` 均加载并正常退出，没有进入场景函数。
- `test_db.py` 只做语法和内容一致性检查，没有导入、执行或自动收集。

上述导入验证使用 Python 3.12.14 和前批临时安装的 `requests==2.34.2`，不代表原机器人环境版本，也未改写依赖清单。没有拨号、启动服务或访问、创建老人数据库。

## 原有后端与拨号授权测试

本轮在 Python 3.12.14 下明确选择两个原测试模块运行，不进行全仓自动收集。这两份测试只需要 Python 标准库。

| 原测试文件 | 实际结果 | 覆盖内容 |
| --- | --- | --- |
| `test_contact_family_call_backend.py` | 7 项全部通过 | 非法模式、JSON/旧文本解析、`dry_run` 准备/拨号、`real` 底层 client 参数转发 |
| `test_contact_family_dial_authorization.py` | 11 项全部通过 | 精确授权、空格标点归一化、泛化肯定/扩展句拒绝、取消和授权状态转换 |

最新合计 18 项实际执行，18 通过、0 失败、0 错误、0 跳过，合并执行退出码为 0。前批曾因缺少 `scripts/g1_call_owner_once.sh`，使 `test_dry_run_prepare` 抛出 `CallBackendError`；本轮导入用户提供的真实源码后，文件存在性条件已满足，后续子进程仍由原测试 mock。本轮没有执行 Shell 或缺失的编排器，也没有修改测试断言或业务代码。

两个 `real` 用例 mock 整个 `_run_phone_client`，只验证参数转发与结果处理，不读取 token、不访问手机。授权状态测试手动放入合成联系人并设置初始状态，电话字段为 `placeholder`，没有查询真实联系人。受控执行未尝试数据库连接、业务网络或子进程调用。

这些用例没有覆盖 `safe_stub`、owner 联系人绑定、语音入口的“绑定—准备—授权—拨号”整体接线，或真实 client 的命令、token、异常和超时行为。后端类自身仍不验证会话授权，不能由这些单元测试推定整条电话链已经完成验收。

本轮新增脚本通过 Python 3.10 语法解析或 `bash -n`，与附件内容一致，仅统一文本换行，Shell 保留可执行权限。Android client 的定义导入成功，未调用业务函数；没有运行电话脚本的入口、读取 token、请求手机或创建老人数据库。
