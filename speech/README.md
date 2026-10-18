# Elder Speech Service v1

## 跨场景老人需求

四个现用场景的共享需求记录、活动偏好使用方式和隐私边界见
[ELDER_NEED_INTEGRATION.md](ELDER_NEED_INTEGRATION.md)。

四个场景的逐轮测试语句、头灯语义和安全启用方式见
[SCENE_TEST_UTTERANCES.md](SCENE_TEST_UTTERANCES.md)。

第一阶段先在 Windows 验证 Qwen-Audio-3.0-TTS-Flash。

## 1. 环境

```powershell
conda create -n elder_speech python=3.10 -y
conda activate elder_speech
pip install -r requirements.txt
```

## 2. 配置

```powershell
$env:DASHSCOPE_API_KEY="你的APIKey"
$env:DASHSCOPE_WORKSPACE_ID="你的WorkspaceID"
```

不要把 API Key 写入代码或提交 Git。

## 3. 普通话

```powershell
python test_tts.py "您好，请问今天感觉怎么样？"
```

## 4. 安抚 + 慢速

```powershell
python test_tts.py "您先别着急，我会陪着您。" --style comfort --speed 0.8
```

## 5. 四川话

```powershell
python test_tts.py "您今天感觉怎么样？" --dialect sichuan --style companion
```

## 6. 输出格式

固定请求 WAV / 16 kHz，便于后续接 Unitree G1。

Windows 使用 `winsound` 播放。

## 6.1 文件语音识别

在 `speech/` 目录中，当前 `speech_client.py` 可将音频文件交给本机语音服务的 `/asr`：

```python
from speech_client import SpeechClient

speech = SpeechClient()
result = speech.transcribe("elder.wav")

print("文字：", result["text"])
print("语言：", result["language"])
print("情绪：", result["emotion"])
print("中文情绪：", result["emotion_zh"])
print("ASR耗时：", result["asr_ms"], "ms")
```

`emotion` 和 `emotion_zh` 取决于 ASR 模型是否返回声学情绪，可能为 `None`。该客户端当前用于未配置 `X-Speech-Token` 的本机服务；文件 ASR 尚未接入视觉情绪判断或 G1 播报链。

## 7. 机器人播放边界

当前电脑保留策略、同学维护的 `speech_client.py` 和语音服务；服务按 `style`、`dialect`、语速等参数生成 WAV。电脑侧 `g1_companion_pcm_bridge` 只接收该本机 WAV，严格校验 PCM 16 kHz、单声道、16 位和最多 15 秒，再用官方 `AudioClient::PlayStream` 送到 **G1 扬声器**。G1 不接收 API key、模型、策略推理或机器人动作。

```python
./build/g1_companion_pcm_bridge --dry-run speech/output/已有的.wav
```

实际 PCM 播放只由电脑侧 bridge 发起，并需要该次实机确认；完成回执是 `PlayStream` 和 `PlayStop` 均返回 0，仍需现场听到 G1 出声。`style="companion"`、`style="comfort"`、`style="happy"` 和 `dialect="mandarin"` 由本机语音服务处理；`play_on_host=False`，因此不会从电脑扬声器播放。


## 8. 统一听取接口

将 `speech/` 复制进现有 `medication_robot` 后，队友可以：

```python
from speech.service import listen

result = listen()
print(result)
```

它会复用你现有的 `asr.recorder` 和 `asr.recognize`。

## 9. 情绪模块联调

先在项目根目录启动本机语音服务：

```bash
./speech/run_server.sh
```

另一个终端用已通过素材执行“情绪事件 -> 审核话术 -> TTS -> WAV”：

```bash
set -o pipefail; data/visual/venv-emotion/bin/python scripts/g1_elder_companion_emotion_demo.py --input vedio/happy_1.mp4 --max-seconds 60 | speech/venv/bin/python speech/emotion_interaction.py
```

默认只生成 WAV；显式增加 `--play-on-host` 才在语音服务主机播放。消费者校验 `emotion_strategy_v1`、在本进程内按 `event_id` 去重，并输出结构化回执。G1 交接的离线检查不需要启动语音服务：

```bash
./scripts/g1_elder_companion_emotion_preflight.sh
```

`--g1-pcm-bridge ./build/g1_companion_pcm_bridge --confirm-g1-companion-pcm --dialect mandarin` 才是有界实机播放路径：每次最多三条，按 `stable_face` / `possible` 从审核短句中随机选择，WAV 在 SDK 初始化前校验且每条最长 15 秒。2026-09-08 的旧 `TtsMaker` 相机回执只证明旧播放周期；PCM 普通话路线已有隔离场次的 G1 播放回执，并已并回正式相机命令。
