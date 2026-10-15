# 照护咨询模块说明

## 当前导入范围

目录为 `speech/scenarios/care_consultation_support/`。已收到 25 个 Python 文件、`care_knowledge.json` 和此前导入的两个启动脚本。保留原目录和业务逻辑，只统一文本换行；没有导入真实数据库、运行日志或废弃场景。

以下结论来自本批源码审查，不代表现用机器的运行验证。

## 入口与展示模式

| 入口 | 源码行为 |
| --- | --- |
| `g1_voice_demo.py` | G1 语音场景，包含语音识别、护理交互、决策播报、录制和会话收尾 |
| `g1_voice_demo.py --showcase` | 同一语音入口的展示模式，本批没有独立的 `g1_showcase_demo.py` |
| `care_api.py` | HTTP 入口，源码监听 `0.0.0.0:8810`，活动咨询对象保存在进程内 |
| `text_demo.py` | 终端文本交互入口 |
| `test_showcase_offline_chain.py` | 使用模型替身和数据库副本的五阶段离线验收脚本 |

API 提供 `GET /health`、`POST /v1/care/chat`、`POST /v1/care/session/{session_id}/end`。SQLite 保存会话消息，但进程内咨询对象不在重启后恢复。

`run_g1_demo.sh` 将参数传给语音入口，并加载公共会话配置；该脚本本身不默认增加 `--showcase`。语音入口和测试显式将 `speech/` 加入模块查找路径；API 与文本入口需要运行环境保证共享模块可导入。

| 行为 | 普通语音模式 | `--showcase` |
| --- | --- | --- |
| 咨询会话与消息 | 写数据库 | 仍写数据库 |
| 会话来源 | `runtime` | `showcase` |
| 工作人员关注事项 | 按条件创建记录 | 模拟创建 |
| 共享 `elder_need` | 按条件写入/更新 | 不写入 |
| 长期护理记忆 | 按条件持久化 | 预览，不正式存储 |
| 云模型与 G1 语音 | 仍需实际依赖 | 仍需实际依赖 |
| 连续空识别 | 达到条件后结束 | 等待老人主动结束，不按该次数自动结束 |

因此，展示模式不等同于离线模拟或完全无写入。现有 `--max-rounds` 用于模型上下文轮次预算，源码不再据此强制终止咨询。

## 模块关系

- `care_controller.py`：咨询状态、风险升级、个体化护理、结束意图和共享需求桥接。
- `care_intent.py`、`care_risk.py`：规则意图、领域识别与风险分类。
- `care_intent_llm.py`、`care_end_intent_llm.py`、`llm_client.py`：场景语义识别、结束语义判断及护理回复模型。
- `care_prompt.py`：主链策略上下文和 `DOMAIN_KNOWLEDGE`。
- `care_personalization.py`、`care_memory.py`：读取个体档案、护理基线及历史，构建个体化信息和规则。
- `care_need_bridge.py`：复用公共 `elder_need_registry` 的跨场景需求接口。
- `care_memory_persistence.py`、`care_session_finalize.py`：会话结束后的共享需求收尾、记忆提取、存储或预览。
- `care_profile_announcement.py`、`care_memory_announcement.py`：个体档案和记忆结果的播报文本。
- `care_db.py`：咨询会话、消息和工作人员关注记录。

G1 入口调用 `finalize_care_session()` 收尾；API 和文本入口当前只调用 `finish_session()`，不能将三个入口的长期记忆和共享需求收尾能力视为相同。

控制器可返回 `CONTACT_FAMILY`、`URGENT_ASSISTANCE` 转场标识。本批入口据此返回或结束当前咨询，未见自动启动联系家属场景或实际发送工作人员通知的执行链；创建关注记录不等于通知已送达。

## 知识库的实际接入状态

`care_knowledge.json` 含 35 条知识卡、7 个领域，`care_knowledge.py` 提供加载、检索及提示格式化功能。当前收到的控制器和策略提示主链使用 `care_prompt.py` 内的 `DOMAIN_KNOWLEDGE`，未见其调用 JSON 检索模块。

本轮只保留和校验知识库结构，不改变知识来源，也不据文件已入库宣称知识检索已接入主链。

## 数据库与缺失依赖

代码固定查找 `speech/data/elder_companion.db`。该数据库名称是共享数据约定，与已废弃的同名场景分别处理。

已补齐的共享源码：

- `speech/elder_need_registry.py`：需求桥接的顶层导入依赖，影响控制器入口。
- `speech/decision_announcer.py`、`speech/companion_recording.py`：G1 入口及离线验收的导入依赖。
- `speech/init_elder_need_db.py`：建立共享需求表 `elder_need` 和三个索引；不创建 `data/` 父目录或 `elderly_person` 基表。
- `speech/data/init_db.py`：建立 `elderly_person`、`family_contact` 和 `contact_call_log` 基表，并在未找到比赛示例老人时写入电话占位符联系人。

老人基表初始化源码已收到，但本仓库没有生成默认数据库；现有照护离线验收仍缺需求、会话、记忆和个人档案等表及受控演示种子。

共享需求登记模块提供需求的创建、查询、更新、历史和频次查询。决策播报默认关闭，启用后才调用 `speech.speak_g1()`。会话记录模块按调用创建权限为 `0600` 的 JSONL 文件，单行上限 64 KiB、单文件上限 8 MiB；软件播放回执保留 `physical_heard="unknown"`，不能据回执认定现场已经听见声音。

录制的 `mode` 字段支持 `live`/`replay`，但 `run_recorded_scene()` 仍调用传入的场景函数；仅选择 `--record-mode replay` 不会自动阻止语音或实机执行。这与 `--showcase` 的业务写入开关分别处理。

本批已收到的数据库脚本分工：

| 文件 | 源码作用 |
| --- | --- |
| `speech/init_elder_need_db.py` | 建立共享需求表及三个索引，开启 WAL；需要已存在的 `data/` 目录，后续写入需求还需老人基表和记录 |
| `init_care_db.py` | 建立咨询会话、消息、工作人员关注三张表 |
| `init_care_memory.py` | 补会话来源/记忆开关列，建立长期记忆表 |
| `init_care_memory_occurrence.py` | 建立护理记忆历史明细 |
| `init_personal_care_profile.py` | 建立个人病史、护理基线、护理事件表 |
| `seed_personal_care_profile.py` | 向老人 ID 1 写入演示档案，包含更新及删除特定演示事件的操作 |

`care_memory_ingestion` 提取记录表由 `care_memory_persistence.init_memory_persistence()` 在运行时创建。单独执行 `init_care_db.py` 不足以满足 `care_db.create_session()` 所需的列和完整运行结构。本轮没有执行初始化或种子脚本；后续在独立匿名测试库核对初始化顺序，不直接修改机器人原库。

公共语音服务和 G1 PCM bridge 等前批次记录的依赖仍需补齐。`care_console.link` 源码已收到：它只连接本机工作台，并在普通 G1 场景启动前登记本轮交互日志；本轮没有启动工作台、创建其数据库或连接真实日志。云模型从环境读取现有 DashScope 配置，未上传密钥。

## 本轮验证结果

两份同名源码附件逐字节相同，按一份导入。25 个 Python 文件通过 Python 3.10 语法解析，JSON 可解析、知识卡 ID 唯一；导入内容与附件一致，仅统一换行。

补齐四个公共模块后，在 Python 3.12.14 中加装临时 `requests==2.34.2`，9 个共享模块和照护入口的导入检查通过。没有执行数据库连接、云请求、场景函数、初始化脚本或机器人操作；该检查仅证明已收到的导入链能加载，不证明业务功能通过。

尝试的原有验收命令：

```bash
python3 speech/scenarios/care_consultation_support/test_showcase_offline_chain.py
```

该命令退出码为 1，在前置检查处报告缺少 `speech/data/elder_companion.db`。五阶段业务断言尚未执行，不能报告离线验收通过。

这是前一批的实际运行结果。本批已补入基表初始化源码，但为避免在仓库创建数据文件没有按默认路径执行；完整照护验收还需要其余数据库初始化和受控演示种子，因此没有重复运行。

该脚本按设计检查个体档案调用、风险升级、主动结束、记忆预览和数据库写入边界；它使用离线模型替身，并从只读源数据库备份到临时副本。完整执行仍需上述公共模块及包含所需档案的匿名演示数据库。

真实云模型、ASR/TTS、API 请求、正式记忆存储、工作人员通知、转场执行和机器人行为均未验证。本轮完成的是源码整理及静态核对。
