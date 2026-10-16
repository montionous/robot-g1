# G1 PCM bridge

## 已收到的源码快照

本批按原路径保存以下五个文件：

- `CMakeLists.txt`
- `src/g1_companion_pcm_bridge.cpp`
- `src/README.md`
- `tests/assert_exit_64.cmake`
- `tests/README.md`

这不是可独立构建的工程。bridge 主程序直接包含但当前缺失的 `src/g1_companion_pcm.hpp`；根 CMake 还声明了未迁移的 `tests/g1_companion_pcm_test.cpp` 以及完整机器人项目的许多其他目标。因此不能在当前仓库根目录运行 CMake 配置，也不能把 `build/g1_companion_pcm_bridge` 视为已可生成。

保留的上游 `src/README.md` 还链接到未收到的 `reports/gate10_right_whole_hand_extension_return_20260720.md`；该原始链接保持不改，不作为当前源码快照的完整性声明。

## 已确认的调用契约

`src/g1_companion_pcm_bridge.cpp` 在静态审查中与现有调用方匹配：

| 调用方 | 需要的 bridge 行为 |
| --- | --- |
| `speech/g1_audio/g1_pcm_bridge.py`、`SpeechClient.play_g1()` | `--confirm-g1-companion-pcm <wav>`，成功时输出 JSON `status: "completed"`。 |
| `scripts/g1_contact_family_call.py` | `--dry-run <wav>`，输出 `kind: "g1_companion_pcm_bridge"`、`status: "dry_run"`。 |
| `speech/g1_audio/entertainment_interrupt.py` | `--confirm-g1-companion-pcm --allow-interrupt <wav>`，先输出 `ready`，响应 `SIGUSR1`，再输出 `completed`、`interrupted` 或 `failed`，并包含 `app_name`、`wav_path`、`play_result`、`stop_result`。 |
| `scripts/g1_elder_companion_emotion_preflight.sh` | 期望 CMake 目标 `g1_companion_pcm_bridge`、`g1_companion_pcm_test` 及名称匹配 `g1_companion_pcm_` 的 CTest。 |

主程序在 `--dry-run` 路径只读取和解析 WAV，不初始化 SDK。确认播放路径才会初始化 Unitree ChannelFactory（固定 Domain 0、网卡 `enp3s0`）与 `AudioClient`，并调用 `PlayStream`/`StopStream`。这些是收到主程序可直接确认的控制流；WAV 的具体格式、时长和字节上限实现在缺失的 `g1_companion_pcm.hpp` 中，尚未独立验证。

## 外部与未收到的依赖

构建目标需要系统 `jsoncpp`，以及外部 Unitree SDK2 的头文件、静态库和 DDS 动态库。上游 CMake 的默认 `UNITREE_SDK2_ROOT` 是 `/home/user/github-product/unitree_sdk2`，可通过 CMake cache 覆盖；SDK 源码、构建产物、虚拟环境、密钥和设备配置没有导入。

下一批需要精确补充：

```text
src/g1_companion_pcm.hpp
tests/g1_companion_pcm_test.cpp
```

收到后仍只进行静态审查，直到完整 C++ 构建上下文和现场设备条件可用。

## 本轮检查边界

归档路径和链接类型检查通过，五个文件逐一与附件一致，静态扫描未发现凭据字面量。没有运行 CMake、编译、CTest、bridge、Unitree SDK、DDS、G1 音频播放或任何机器人命令。
