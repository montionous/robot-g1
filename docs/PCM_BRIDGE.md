# G1 PCM bridge

## 已收到的源码快照

两个源码包按原路径保存以下七个文件：

- `CMakeLists.txt`
- `src/g1_companion_pcm_bridge.cpp`
- `src/g1_companion_pcm.hpp`
- `src/README.md`
- `tests/g1_companion_pcm_test.cpp`
- `tests/assert_exit_64.cmake`
- `tests/README.md`

bridge target 明确列出的本地源码、相邻头文件和核心测试源码现已收到：主程序包含 `g1_companion_pcm.hpp`，`g1_companion_pcm_test` 也有对应的 C++ 源文件。但根 `CMakeLists.txt` 仍是完整机器人项目的构建清单，声明了仓库中未迁移的许多其他目标和源码。因此当前仓库根目录仍不能配置或构建，`build/g1_companion_pcm_bridge` 不能视为已生成。

保留的上游 `src/README.md` 还链接到未收到的 `reports/gate10_right_whole_hand_extension_return_20260720.md`；该原始链接保持不改，不作为当前源码快照的完整性声明。

## 已确认的调用契约

`src/g1_companion_pcm_bridge.cpp` 在静态审查中与现有调用方匹配：

| 调用方 | 需要的 bridge 行为 |
| --- | --- |
| `speech/g1_audio/g1_pcm_bridge.py`、`SpeechClient.play_g1()` | `--confirm-g1-companion-pcm <wav>`，成功时输出 JSON `status: "completed"`。 |
| `scripts/g1_contact_family_call.py` | `--dry-run <wav>`，输出 `kind: "g1_companion_pcm_bridge"`、`status: "dry_run"`。 |
| `speech/g1_audio/entertainment_interrupt.py` | `--confirm-g1-companion-pcm --allow-interrupt <wav>`，先输出 `ready`，响应 `SIGUSR1`，再输出 `completed`、`interrupted` 或 `failed`，并包含 `app_name`、`wav_path`、`play_result`、`stop_result`。 |
| `scripts/g1_elder_companion_emotion_preflight.sh` | 期望 CMake 目标 `g1_companion_pcm_bridge`、`g1_companion_pcm_test` 及名称匹配 `g1_companion_pcm_` 的 CTest。 |

主程序在 `--dry-run` 路径只读取和解析 WAV，不初始化 SDK。确认播放路径才会初始化 Unitree ChannelFactory（固定 Domain 0、网卡 `enp3s0`）与 `AudioClient`，并调用 `PlayStream`/`StopStream`。

头文件静态确认的 WAV 条件为 RIFF/WAVE、PCM format 1、单声道、16 kHz、16 位、`block_align=2`、`byte_rate=32000`、非空 data payload，且实际 PCM 数据不超过 32 MiB。实现允许 streaming 风格的超大 RIFF/data 声明，但实际 payload 仍受该字节上限约束。

当前实现**没有 15 秒时长上限**。在 32,000 B/s 下，32 MiB 约为 1048.6 秒；因此保留的上游说明中“最多 15 秒”的表述不能作为当前源码已验证的限制。`PlayCompanionPcm` 由 bridge 以 96,000 字节（约 3 秒）分块调用，每次等待最多 20 ms 后检查取消；正常、取消和播放失败的路径都会调用停止回调。

`tests/g1_companion_pcm_test.cpp` 是只使用内存回调与 `assert` 的核心测试源码。它覆盖分块、等待、取消、播放/停止错误与异常清理，以及有效/无效 WAV、streaming 声明和 32 MiB 上限；没有覆盖 CLI JSON、`--dry-run` 或 Unitree 客户端。本轮未编译或运行该测试。

## 外部与未收到的依赖

bridge 构建目标还需要系统 `jsoncpp`，以及外部 Unitree SDK2 的头文件、静态库和 DDS 动态库。上游 CMake 的默认 `UNITREE_SDK2_ROOT` 是 `/home/user/github-product/unitree_sdk2`，可通过 CMake cache 覆盖；SDK 源码、构建产物、虚拟环境、密钥和设备配置没有导入。

完整的根 CMake 还引用未迁移的机器人 C++ 源和测试文件。即使 PCM 的直接源码现已齐全，仍需收到完整构建上下文后才能考虑配置或构建；之后还需在机器人现场单独处理 SDK、DDS 网络和音频安全条件。

## 本轮检查边界

两个归档的成员路径和链接类型检查通过，七个文件逐一与附件一致，静态扫描未发现凭据字面量。没有运行 CMake、编译、CTest、bridge、Unitree SDK、DDS、G1 音频播放或任何机器人命令。
