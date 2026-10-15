# 队友调用说明

所有模块统一通过 `speech.service` 调用，不直接调用 DashScope。

## 机器人说话

```python
from speech.service import speak

speak("您好，我是您的陪伴机器人。")
```

安抚：

```python
speak(
    "您先别着急，我会陪着您。",
    style="comfort",
)
```

突发异常：

```python
speak(
    "您先不要移动，我已经通知护理人员了。",
    style="emergency",
)
```

陪伴：

```python
speak(
    "我可以陪您聊一会儿。",
    style="companion",
)
```

四川话：

```python
speak(
    "您今天感觉怎么样？",
    dialect="sichuan",
    style="companion",
)
```

高级控制：

```python
speak(
    "您先别着急。",
    dialect="mandarin",
    speed=0.82,
    pitch=0.95,
    volume=80,
    emotion="calm",
)
```

## style

- `normal`
- `companion`
- `comfort`
- `emergency`
- `happy`

## 团队规则

1. 其他模块不保存或读取 API Key。
2. 其他模块不直接修改模型和 Workspace 地址。
3. 新增方言/语气只修改语音模块内部映射。
4. 方言效果以实际测试为准；稳定的“同一音色跨多方言”建议后续使用声音复刻音色。


## 老人语音输入（机器人项目中）

把 `speech/` 目录放入现有 `medication_robot` 后：

```python
from speech.service import listen

result = listen()

print(result["text"])
print(result["emotion"])
print(result["audio_path"])
```

当前返回：

```python
{
    "text": "老人转写内容",
    "emotion": None,
    "audio_path": "...wav",
    "ok": True,
}
```

上面的 `listen()` 是旧服药路线的兼容入口，当前仍可能返回 `emotion=None`。当前文件 ASR 使用 `speech_client.py` 的 `SpeechClient.transcribe("elder.wav")`，其 `/asr` 返回可携带 `text`、`language`、`emotion`、`asr_ms`，并由客户端补 `emotion_zh`；它尚未接入视觉情绪 V1 或 G1 播报链。
