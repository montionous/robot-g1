# G1 Dex3 Care VLA 项目规则

## 项目目标与真源

### 当前竞赛业务覆盖（2026-09-02）

- 当前竞赛业务已从老人服药切换为“老人陪伴机器人”，Boss 当前负责情绪模块；唯一 active 业务真源是 `docs/16-老人陪伴赛道情绪模块真源.md`。
- 情绪 V1 在本机主动检测开心、悲伤和生气，平静只是默认状态；情绪模块产生策略，G1 内互动模块负责具体自然交互。
- 旧服药赛道的 P425、bal1753、A/B/C、bridge、训练与实机路线均是历史证据，不得成为当前情绪模块的运行、训练或验收入口。下文 P425 的“当前”只是原日期下的历史快照，不得覆盖本节。
- 效率优先：每个步骤必须直接改变比赛可演示结果、解除下一个闭环阻断或保全必需资产；否则取消或记为非当前债务。先跑最小本地视频端到端证据，不为提高离线信心堆叠无关测试、报告、抽象或训练。
- 预训练模型在同一 Prototype Gate 上未经证明不合格前，不自建数据集、不训练情绪模型。Trellis 历史任务状态漂移不阻断当前闭环，不在功能任务中批量清理。

本项目面向真实宇树 `G1 EDU+ CN / 23DoF`，主线是 SDK 贯穿实机接入、官方 XR 遥操、训练数据生成、策略接入、部署执行和运行诊断。产品从 0 建设不等于技术从 0 重写。

本项目按机器人竞赛工程而不是科研论文工程管理。第一验收是 G1 在现场完成可观察、可停止、可重复的真实任务；离线分数、测试数量、数据规模、训练资格和报告完整度只在它们直接解除下一次实机演示阻断时有价值。策略 checkpoint、推理和视觉输入最终部署在 G1 机载或随机器人运行的一侧，比赛演示不得依赖 A6000、SSH tunnel 或远端 HTTP。

事实冲突按以下顺序裁决：

1. 实机铭牌/BOM、当前源码与测试、运行日志、用户侧观察和 Git 状态；
2. 与当前设备/固件匹配的宇树官方文档、SDK、教程与示例；
3. `docs/README.md` 索引的当前文档和 `contracts/`；
4. 历史 Gate、archive 和旧会话仅作模式证据。

详细 Gate 数值、episode inventory 和历史报告留在 `docs/README.md` 及其索引文档；本文件只保留会改变当前实施的事实。

## 当前冻结事实

- 主机 `enp3s0 / 192.168.123.99/24` 与 G1 `192.168.123.161` 已验证连通；DDS Domain `0`、`rt/lowstate`、`unitree_hg::msg::dds_::LowState_` 已冻结。
- 官方 SDK checkout 为 `/home/user/github-product/unitree_sdk2`，commit `21d0a3b2c46ee48c8fdf2783becb6be3beb0a59b`；禁止复制 SDK 源码进本仓库。
- SDK-R0 通信/观测基线和 SDK-R1 机器人执行能力已闭合：双臂 continuous 与双手功能性开合为 `verified`；两侧 `thumb_0` 单关节保持 `partial`，不阻断功能型 24D Action。
- SDK-R2 统一 Observation/Action/ExecutionResult/Episode/runtime 已离线完成；SDK-R3 production transport/composition 已有实机生命周期和功能型 24D smoke 证据。
- 当前处于 SDK-R4/R5：正式遥操 owner 为官方 `/home/user/github-product/xr_teleoperate/teleop/teleop_hand_and_arm.py`，项目 bounded runtime 只保留安全回归、回放和异常诊断。
- 官方 XR 基线 commit 为 `7dc9aa1a6edbf4a9f4f887d8ab6fc449ea5135f6`；V3 控制语义、JPEG quality `50`、双手 `scaling_factor=1.5`、官方 Motion Mode (`motion=true` / `kTopicLowCommand_Motion`，固件侧平滑；one-shot touch_cup 仍为 Debug Mode `rt/lowcmd`) 与受门控 Dex3 直接目标基线固定为 `ef5d8856faa41a0c1e9eed4ac9094c6a66e834f4`。当前通用采集 runner 使用隔离诊断 checkout `/home/user/github-product/xr_teleoperate_latency_debug` 的 `cfe6d06e2eed5b3707e08757aa9fdcf9625488a4`（Televuer `9e946dc82261c22684ad6704b0b144fe7a3a5937`），只增加 bounded XR input sidecar；原 `/home/user/github-product/xr_teleoperate` 保持 clean 在 `ef5d8856...` 作为回退。独立连续性 qualification 使用 `/home/user/github-product/xr_teleoperate_input_stall_fix` 的 `69a6b624078d3edc97f4650535f4464c9999e22d`（V3 录制 live 30 Hz 命令，fresh 可落地后 guard 回 tracking，证据门闩仍等 after-observation），并启动前核对它、通用 runner 与正式回退均 clean；它不是候选 VLA controller。
- `g1_official_xr_adapter.py` 只会把完整 writer evidence、after-observation、对齐 RGB 和 success 标签投影为 `accepted`。历史 V2 仍要求 fresh Space hold；blue-cup V3 明确使用 `official_continuous_ik_v1`、不伪造 deadman，直到新的 blue-cup 实机 qualification 产生并验证首条 accepted EpisodeV2。
- EpisodeV2 是训练/部署唯一导出合同；官方 native `data.json`/JPEG 保持不可变 source，不直接充当训练合同。
- 竞赛主线以可重复、可停止的 G1 实机演示为第一验收。Pi0.5 后续必须将 checkpoint、推理和相机输入部署在 G1 本机侧；训练服务器、SSH tunnel 与远端 HTTP 仅是历史诊断证据，不是部署方案。模型仍只能输出受校验 action，真实写入继续走官方受限 controller，禁止直写 DDS。
- 旧服药赛道 P425、P511、Psi0、HEX、A/B/C、bridge、训练和实机路线均为 historical / read-only；不得成为当前情绪模块的运行、训练或验收入口。
- 详细身份、哈希、失败证据和恢复边界见 `contracts/README.md`、`contracts/pi05_p425_policy_path_v1.md`、`reports/2026-08-27_P425保守B+抓取方案归档.md` 及 `docs/README.md`；需要复核时按收据、合同和原始 artifact 定点读取。
- 重新启用任何历史路线必须新建独立候选任务并取得明确确认；历史 task/session pointer 不等于当前 active source。

当前停止路线：继续用固定微动作逼近自主触杯、让局部 `thumb_0` 缺口阻断 24D 遥操、建立平行 DDS/SDK/训练合同、把远端 Pi0.5 服务当作部署方案、让训练或策略直接访问 DDS topic、在新旧 checkpoint 同条件实机比较前先调整 VLA 策略或控制语义、在平滑 Gate 2 已过关后仍按 task/stats 字符串不一致连夜微调 Pi0.5。不得把已废弃的 A247/A267 或旧 runner 重新写成所有模型的强制前置；需要复用队友 runner 时在独立 checkout 中固定上游 revision、模型资产哈希、依赖环境与本次 execution profile，只通过最小 adapter 接入现有安全/runtime 合同，不能反向改写主仓历史 owner。

## 官方基线优先与差量适配

涉及宇树、XR、相机、SDK 或机器人控制时：

1. 固定官方入口、版本/commit、硬件 profile、运行模式、参数和原生格式；
2. 只做影响本次运行的兼容性与安全检查；
3. 尽快跑代表性官方端到端基线；
4. 按“直接复用 → wrapper/adapter → 可选最小 hook → 局部 patch → 有证据后自研替代”处理差距。

### 官方控制引用审计卡

凡以“参考官方/GitHub”支持实机控制结论、包装官方 controller，或比较两个同 topic 路径时，当前 task 的设计/报告必须逐项留下源码行号或运行 artifact：

1. checkout 路径、正式基线与实际 revision，以及各自 clean/dirty 状态；
2. 实际入口、完整相关 flags、设备 profile 和 mode API；
3. 最终 topic/service，以及每个 `mode/q/dq/tau/kp/kd` 字段、控制频率、target/重力项的来源和锁定关节；
4. feedback、slew/freshness、writer/returned-observation 判定，以及 stop/release/restore 语义；
5. 隔离 checkout 相对正式基线的 diff，并逐个说明所有控制相关文件。

README、脚本/类名、相同 topic、或单个 writer success 都不能替代任一项。缺项只能标为 `upstream_available`，不得声称控制语义可比、可替代或可用于实机适配；“同 topic”不等于“同控制器”。

状态分层记录：`upstream_available`、`local_compatible`、`supervised_operation_verified`、`training_qualified`。官方来源不能替代本机兼容、实机行为和数据资格证据。

首次有人监护的官方基线只由设备/profile、控制模式、网络/接口、限位、停止/恢复和原始数据保留阻断。时间戳、writer result、RGB 对齐等缺口只阻断相应训练导出阶段。

已有官方数据用于验证项目 profile、维度、字段语义和边界；无需重复证明官方实现存在。官方入口覆盖正式操作链后，自研 smoke 不再与其竞争 owner。

## Owner 与实现边界

- SDK 核心拥有 Observation、Action、ExecutionResult、Episode、门禁和 replay。
- 官方 `teleop_hand_and_arm.py` 拥有实时 XR 遥操与原始采集；项目 hook 只记录事实，不拥有控制语义。
- Device/Policy/Robot adapter 只做协议转换；脚本只做采集与接线。
- 遥操采集与策略部署复用同一 runtime、RobotAdapter、错误语义和 Episode owner。
- 本机策略部署的首要产物是可演示的实机闭环；训练导出是可选后续资产，不能反向主导控制架构或验收标准。
- 音频、VLA、视觉分别保持独立部署和独立验收入口；比赛 bridge 只编排结构化交接。更换一个模块时，其他已通过模块保持冻结，只复验该模块边界和一次完整闭环。
- Episode 保存 raw source、mapped action、最终 sent command、writer/RPC result、returned observation 和对齐质量；缺少字段时显式降级资格，禁止伪造。
- 外部输入检查维度、类型、长度、时间戳和有限值；队列、文件、重试和运行窗口有上界。
- 生成物改源并重生成；原始数据、运行日志、密钥和证书不提交 Git。

## 功利性执行

- 需要用户手动执行的命令优先提供单行、可直接复制的形式；仅在单行会损害正确性或可读性时分行。
- 最高优先级是形成可用、可记录、可停止的本机推理实机演示闭环；官方遥操和训练资格只补齐这一演示所需的差量。
- 已形成完整闭环后，最高优先级转为保全 reference baseline 并支持模块级替换。VLA 优化顺序固定为“旧模型同场景基线 -> 新模型直接替换 -> 实机对比 -> 按失败阶段决定是否补采 -> 重训再替换”；没有实机对比证据不改策略。
- 每个有真实任务目标的阶段，在完成最小安全/接口预检后必须优先安排一次受监督、有界实机端到端演示；成功与失败都是真实阶段结果。不得因继续积累离线测试、仿真结果或本机数据而推迟这条演示。
- 每个步骤应改变用户结果、capability、阶段准入、关键风险或主线必需资产；否则取消或记债。
- 已验证通信、topic、方向、限位和 writer 基础后，停止重复调试、微位移、阈值和只提高离线信心的 Gate；只修复已阻断下一次实机演示的具体问题。
- 局部失败先区分“诊断指标失败”与“真实工作流不可用”；反馈、最新观测重锚定、降级、日志/回放或人工恢复能吸收时继续主线。
- 同类尝试没有新增证据或没有改变下一步时立即换到代表性端到端验证。
- 小而有界的修改直接做；持久计划、额外 Agent、报告和文档只在跨 owner、高风险、不可逆或跨会话时启用。
- 不使用固定工具次数、文件数、覆盖率和 Session 阈值。

## 实机与安全门禁

只读连接、查询、订阅、日志分析、离线实现和测试可连续执行。以下状态变更需在执行前说明目的、边界、验收和停止条件，并取得该次明确确认：

- DDS publisher、动作 RPC、`ServiceSwitch`、模式切换和机载配置写入；
- 关节、Dex3、手臂、腰部或底盘命令；
- 已确认操作之外的新 topic、服务、动作范围、参数、频率或时长。

release/restore、模式/限位、有限值、资源上界、原始 artifact 和 checksum 始终保留。V2
保留 deadman；V3 是经用户明确批准的监督锁存例外，必须如实记录无 deadman、`r` 到 `q` 和
180 秒上界，不得伪造 freshness 或断连自动保持。一次确认只覆盖已描述的有界操作。

## 验收、文档与 Git

- 验收匹配风险：配置/文档做一致性检查；局部逻辑跑 owner 回归；实机、数据、安全、并发和部署扩大到相应证据。
- 对真实任务而言，离线测试、数据质量和 writer 成功都不能单独关闭阶段；只有有界实机演示结果，或已记录且不可在当前条件下消除的实机阻断，才能决定下一步。
- 完成声明必须列出本轮实际命令、日志、测试或用户侧证据；关键验收缺失时说明影响。
- 只有合同、架构边界、用户行为、部署或跨会话状态持久变化时，在收尾阶段统一更新中文真源；原始实机日志与哈希仍即时归档。
- 对抗式审查聚焦实机伤害、权限、数据伪真、无界资源、掉线恢复和错误训练资格；普通小修不生成泛化风险清单。
- 提交前检查 Git root、`git status --short`、staged paths、ignored 文件和嵌套仓库。
- 禁止 `git add .`、force-add ignored 文件、覆盖或吸入用户无关 dirty changes。
- 只有用户明确要求或当前任务进入提交阶段时精确 stage/commit；新的实机动作不因历史提交自动获得授权。
