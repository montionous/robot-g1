# 赛前预生成固定话术

短而固定的机器人回复不必每次请求云端 TTS。四个现用场景各有一个
`prepared_prompts.json` 清单；运行时只在**文本、style、dialect 和语音参数完全一致**时播放对应的本地 WAV。没有匹配项、文件缺失或 WAV
格式不合格时，会安全地回退到原来的实时合成，并启用服务端短期缓存。

动态内容仍然实时合成，包括曲名、查询词、活动名称/时间/地点、联系人称谓和姓名、护理风险原因及家属原始语音。这样不会把过期或错误的个人化内容预先播报出来。

娱乐场景的陕西话条目独立于普通话条目。`g1_showcase_demo.py` 固定使用
`dialect="shaanxi"`；`run_g1_demo.sh` 现在也默认陕西话，可通过
`G1_ENTERTAINMENT_DIALECT=mandarin` 或末尾的 `--dialect mandarin` 临时覆盖。

## 生成

在机器人连接的电脑上，先在一个终端启动本地语音服务：

```bash
cd /home/user/github-product/g1-dex3-care-vla/speech
./run_server.sh
```

另开一个终端。先只生成并试听娱乐场景的陕西话和普通话固定提示：

```bash
cd /home/user/github-product/g1-dex3-care-vla/speech
source venv/bin/activate
python tools/generate_prepared_prompts.py \
  --manifest scenarios/companion_entertainment/prepared_prompts.json
python tools/generate_prepared_prompts.py \
  --manifest scenarios/companion_entertainment/prepared_prompts.json \
  --check
```

确认陕西口音、停顿和音量满意后，生成全部四个场景的固定话术：

```bash
cd /home/user/github-product/g1-dex3-care-vla/speech
source venv/bin/activate
python tools/generate_prepared_prompts.py
python tools/generate_prepared_prompts.py --check
```

生成器复用正在运行的语音服务，因此会使用当时的 TTS 模型、声线、style 和
dialect。每个 WAV 会校验为 16 kHz、单声道、PCM 16 位，并以临时文件原子替换。

## 存储和更新

生成物位于 `speech/runtime/prepared_audio/`，该目录已被 Git 忽略，不会把老人数据、运行日志或音频产物提交到仓库。可用
`G1_PREPARED_AUDIO_DIR` 把它放到其他磁盘。

文件名包含话术、方言、语音参数和 `voice_profile` 的指纹；清单改字、改方言或改
`voice_profile` 后，旧 WAV 不会再次被命中，会先回退实时合成。修改 TTS 模型或声线后，应重新生成相关清单并在实机上试听。`--force` 可强制重新生成已有条目；默认生成只补缺失或无效的文件。
