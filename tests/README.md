# SDK 与安全合同辅助验收

> **当前业务测试 owner：** `g1_elder_companion_emotion_demo_test.py` 保护本地视频、时间稳定、证据融合、隐私录像和 `emotion_strategy_v1`；`speech/test_emotion_interaction.py` 保护事件校验、去重、稳定/确认话术库、普通话 TTS 参数和 G1 PCM bridge 调用；`g1_companion_pcm_test` 保护 G1 只接受有界的 PCM WAV。旧服药与 G1 Gate 测试只作历史/基础回归，不定义当前下一步。

```bash
data/visual/venv-emotion/bin/python -m unittest tests.g1_elder_companion_emotion_demo_test
data/visual/venv-emotion/bin/python -m unittest tests.g1_elder_companion_emotion_tts_run_test
cd speech && venv/bin/python -m unittest test_emotion_interaction.py
cd speech && venv/bin/python -m unittest test_emotion_dialogue.py
cmake --build build --target g1_companion_pcm_bridge g1_companion_pcm_test -j2
ctest --test-dir build -R 'g1_companion_pcm' --output-on-failure
```

下方测试用于保留 G1 接口、安全和历史证据边界，不是当前情绪模块的竞赛阶段终点。

历史 Gate fixture 可以继续保留，但不得因追求测试数量、覆盖率或离线指标把旧 G1/Pi0.5 路线重新变成当前任务。

当前测试覆盖 SDK 只读状态监视器：

`g1_medication_stage_flow_state_test.py` 保护下一次 A/B/C bridge 接线：它覆盖 A 三次无药重启/外洒人工复位/右侧放瓶，B/C 接杯超时与回桌、掉杯人工复位、180 秒上限、事件乱序、JSONL 重放和唯一成功播报请求。它只证明离线 reducer 合同，不证明视觉、VLA 或实机动作成功。

`g1_medication_stage_ab_live_bridge_test.py` 以假 launcher 验证一次整场确认后的 A→B 自动交接：只有同场 A 成功事实、A 进程正常退出且尚未到 180 秒 deadline 才会启动一次 B；A 失败、进程失败或 deadline 均阻断 B。它不执行 launcher，不证明实机任务成功。

`g1_medication_stage_isolated_vla_bridge_test.py` 保护 A 到 B 的最小接线：隔离 A 客户端只能在新建的 session/run 结果日志中写有序的抓取、正常倒药退出、右侧放瓶例程事实前缀；失败、旧日志、身份不符和 deadline 后事实不会启动 B，开场人工固定橙杯位置的 profile 也只能在 A 完成后出现。它同样不证明实机动作成功。

1. 静态检查证明运行路径不创建 publisher、不调用动作 RPC；
2. 网卡、DDS domain、topic、采集时长和输出路径配置校验；
3. 消息显示、频率、模式变化与断流规则事件的确定性测试；
4. 无 topic、消息中断、畸形值和用户中断时输出结构化失败；
5. 证据报告包含设备身份、采集参数、来源和采集时间。

Gate 5F 额外覆盖：

1. JSONL 多行处理、错误后继续、输入上界和 EOF；
2. 同 ID 重放、冲突拒绝和 TTS 速率限制不重复调用 fake adapter；
3. 播放周期仅接受新 `play_state=1 → 0`，超时与关闭均有确定性结果；
4. observer、adapter 与 `ChannelFactory` 的关闭顺序由 fake lifecycle port 验证。

Gate 6 额外覆盖：

1. 固定模板服药提醒的创建、播报请求、未严格关联的播放观测、等待确认与人工确认；
2. 任务创建和事件 ID 重放、同 ID 内容冲突、旧版本与非法状态转换；
3. 取消、超时、终态拒绝以及任务/事件缓存上界。

Gate 7 额外覆盖：

1. 右手状态错误或非有限位置时，fake 发布端口不被调用；正常状态只发送一次并严格回读对账；
2. Gate 6 JSONL 只接受右手、7 个有限位置、有效时间戳和两路无符号错误码；非零错误码由命令核心拒绝，非法/超长行输出结构化错误后可继续处理下一行；
3. 回放成功记录固定标识 `input_snapshot_fake`，不得被解释为实机命令后的状态。
4. 官方低增益 profile 的 7 个 mode、`q/dq/tau/kp/kd` 字段固定，fake 端口最多收到 5 次写入；第 3 次失败时不产生第 4 次写入。
5. episode 日志测试验证新目录创建、逐行 flush、summary 写入、含换行事件拒绝，以及已有 episode 目录拒绝混写。

Gate 9B 额外覆盖：

1. 固定 7 电机诊断投影完整保存手级 / 逐电机 `reserve[]`、sensor、温度和状态字段；
2. 非有限浮点转为 JSON `null` 并置 `finite=false`，非 7 电机事件不展开异常数组；
3. 状态采集固定最多 6,000 条；ServiceList 输出最多 128 项，单个服务名最多 256 字节并保留截断标志；
4. 未传确认参数的可执行文件以 usage / 64 退出，CTest 不连接 DDS、订阅状态或调用服务。

Gate 10 额外覆盖：

1. `MakeGate10RightWholeHandCloseReturnPlan()` 仅在 source 状态有效时生成两段命令；第一段为 Gate 8B 固定七关节 target，第二段 7 个 q 必须逐项等于 source；
2. fake 端口验证两段各固定 50 次、合计 100 次写入，并保留首次写入失败即停止的共享上界；
3. 任一 source 错误、非有限值或第一段候选越界时零写入；命令 core 不含 SDK/DDS；
4. `g1_dex3_right_whole_hand_close_return_100hz` 无确认参数以 usage / 64 退出，CTest 不连接 G1。

机器人可见响应和写入接口必须继续由单独合同、确认参数和实机 artifact 验收。离线测试只证明代码边界；当前决定性验收是 Pi0.5 在 G1 本地侧运行并完成有界任务。

实际命令：

```bash
cmake --build /tmp/g1-gate5f-build -j2
ctest --test-dir /tmp/g1-gate5f-build --output-on-failure
```
