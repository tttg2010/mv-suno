# Salpx / Suno / Wan3 实战参考

> 本文件记录工作流中已验证的接口形态与限制。调用前仍须以 Salpx 当前模型目录、价格接口和官方文档为准；不要把历史价格、任务 ID 或凭据复制到新项目。

## 0. 本机实测（2026-11-05，Salpx 官方网关）

- Base URL：`https://www.salpx.com/v1`（网关是 New API；站点文档在 `https://www.salpx.com/api-docs`）
- 凭据：Windows 用户级环境变量 `SALPX_API_KEY` 已配置。**不要把 key 写进本文件、日志或任务回执。**
- 模型发现：`GET /v1/models`（实测 158 个）。**价格：`GET /api/pricing`**（New API 原生接口，返回 `model_price` / `quota_type`），比网页价格页可靠，价格页是 JS 渲染取不到。
- 实测单价（人民币，`quota_type=1` 表示按次/按秒计费）：

| 模型 | 计价 | 单价 |
| --- | --- | --- |
| `suno_music` | 每次 | ¥0.09 |
| `suno_lyrics` | 每次 | ¥0.01 |
| `wan3.0-480p` | 每秒 | ¥0.21 |
| `wan3.0-720p` | 每秒 | ¥0.42 |
| `wan3.0-1080p` | 每秒 | ¥0.84 |
| `gpt-image-2.5-flare` | 每次 | ¥0.14 |
| `gpt-image-2` | 每次 | ¥0.10 |

  15 秒 480p 镜头约 ¥3.15；整片 8 镜 ≈ ¥25，报价时按此量级估算。

- **Wan3 时长必须是 2–30 的整数秒**。服务端报错原文：`duration 只接受 2/3/…/30 秒`。
  分镜 manifest 里的浮点窗口（如 14.8s）不能直接当 duration 提交：**先向上取整生成，再用 ffmpeg 裁回目标窗口**，裁切参数写进 receipt。这是本部署与"保留浮点精度"原则的冲突点，按此方式落地。
- `POST /v1/videos`：`prompt` 必填（缺失返回 `400 prompt is required`）；`metadata.parameters.audio`、`metadata.media`（`reference_image` / `reference_audio`）沿用历史实测形态。
- 视频任务：超时按 ≥600 秒设置；成片链接 **24 小时过期**（过期 403），拿到 URL 立刻下载落盘；生成失败/超时/审核不通过自动全额退款。
- 官方文档写明全能参考的媒体上限：参考图 ≤30 张，参考视频/音频**总时长** ≤30.2 秒，单素材 1.8–30.2 秒。技能内仍按参考音频 ≤15 秒设计（历史经验更保守），要放宽需先单镜实测。
- 图片：`POST /v1/images/generations`，返回 `data[0].b64_json` 或 `data[0].url`。
- 音乐（官方文档 `https://www.salpx.com/api-docs#music`，第 07 节，**不在 `/v1` 命名空间**）：
  - 提交 `POST /suno/submit/MUSIC`（路径大写）。`prompt`（自定义歌词，可带 `[Verse]` 标记）与 `gpt_description_prompt`（一句话描述）二选一；`tags` 或 `title` **任一非空即自动进入自定义模式**，没有 `custom_mode` 开关。
  - 可选 `make_instrumental`(bool)、`mv`（`V6` 默认 / `V6_MINI` 更快 / `V6_WILD` 更发散）、`continue_clip_id` / `continue_at`（续写，常规不用）。
  - 返回 `{"code":"success","data":"task_xxx"}`，**一次出 2 首**。
  - 查询：`GET /suno/fetch/{task_id}` 或批量 `POST /suno/fetch` + `{"ids":[...]}`。免费、不扣费；生成通常 20–60 秒，轮询 5 秒起、超时 ≥300 秒。
  - 返回：`status` 流转 `SUBMITTED → IN_PROGRESS（progress）→ SUCCESS / FAILURE（fail_reason）`；`data.clips` 是**以 clip_id 为键的对象**（不是数组），每首含 `audio_url`（MP3 直链）、`image_url`、`title`、`text`（歌词）、`metadata.tags`、`metadata.duration`。
  - 歌词：`POST /suno/submit/LYRICS`，同样返回 task_id，`data.clips[].text` 是歌词正文，`audio_url` 为空属正常。
  - 计费：提交时预扣，失败全额退款；上游文件保留约 **14 天**，`audio_url` 必须立刻转存。
  - 未开放：续写 Extend、翻唱 Cover、分轨、MIDI、转 WAV、音乐视频、人声消除（都要上传音频，当前无对应字段）。
- 账户额度：`GET /v1/dashboard/billing/subscription`、`GET /v1/dashboard/billing/usage`（`total_usage` 单位为美分）。

### 0.1 逐词时间戳：本地 faster-whisper（已装好，2026-11-05 实测）

Salpx 的 Suno 接口只返回 `text`（整首歌词）和 `metadata.duration`，**不返回逐词时间戳**，`/v1/models` 的 158 个模型里也没有任何 whisper / ASR 类模型（`omni_flash` 那几个是视频全能参考，不是音频）。所以第 3 步必须本地做。

**环境（已验证可用）**

| 项 | 值 |
| --- | --- |
| 解释器 | `C:\Users\admin\.workbuddy\binaries\python\envs\whisper\Scripts\python.exe`（Python 3.12.10 专用 venv） |
| 依赖 | faster-whisper 1.2.1 / ctranslate2 4.8.5 / onnxruntime 1.31.1 / numpy 2.5.4 |
| 模型缓存 | `C:\Users\admin\.cache\huggingface\hub\models--Systran--faster-whisper-small`（small，约 486MB） |
| GPU | ctranslate2 识别到 1 张卡，`float16` 基于 CUDA 可用 |

**两个必须知道的坑**

1. **`av` 必须锁 13.1.0**。faster-whisper 1.2.1 传了 `av.open(..., metadata_errors="ignore")`，PyAV 19 已删掉该参数，装新版会直接 `TypeError`。
2. **CUDA 运行库不在系统里**，靠 pip 的 `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` / `nvidia-cuda-runtime-cu12` 提供，DLL 在 `site-packages\nvidia\*\bin`，不在 PATH 上。`align_words.py` 已内置 `add_cuda_dll_dirs()` 自动注册；换脚本时若不注册会报 `Library cublas64_12.dll is not found`。

**用法**

```
"C:\Users\admin\.workbuddy\binaries\python\envs\whisper\Scripts\python.exe" `
  C:\Users\admin\.workbuddy\skills\xiaom\scripts\align_words.py 歌曲.mp3 `
  --lyrics 歌词.txt --language zh --srt out.srt
```

- 输出 `<歌名>.words.json`：`meta`（真实时长、首词/末词时间、前奏/尾奏、语音占比、>2s 间隙、低置信词数）+ `alignedWords`，可直接喂 `mv_workflow.py make-srt`。
- `--lyrics` 只是把歌词塞进 `initial_prompt` 做解码偏置，**不是强制对齐**：同音字仍可能错，时间仍来自声学模型。切镜前必须抽查。
- 模型下载走 `HF_ENDPOINT=https://hf-mirror.com`（已写入用户环境变量）；已缓存后可用 `HF_HUB_OFFLINE=1` 完全离线。
- **`HF_HUB_DISABLE_XET=1` 很关键**：不关掉 Xet 传输会卡在 0 字节不动（实测卡了 6 分钟）。关掉后走多线程 HTTP，约 6MB/s。

> 未验证：中文歌声（有伴奏）的实际对齐精度。首次拿到成品歌后，应先用 20–30 秒片段比对「识别文本 vs 原歌词」，再决定是否升级到 `large-v3`。

## 1. 认证与模型发现

- 推荐通过 `SALPX_API_KEY` 环境变量或本机安全凭据文件读取密钥。
- 不要把密钥放进提示词、日志、Skill、经验文档或 Git。
- Salpx 地址通常为 `https://www.salpx.com/v1`，但应以当前官方配置为准。
- 先发现可用模型与实时价格，再决定是否调用。重点确认：音乐模型（可能包括 Suno 接入）、`gpt-image-2.5-flare`、`wan3.0-480p`。
- Salpx 的 Suno 接入不等同于 Kie.ai 的 `ai-music-api/generate`。模型 ID、字段、费用和返回结构分别验证。

## 2. 图像接口（历史实测）

历史使用：`POST /v1/images/generations`。

图像返回可能在 `data[0].b64_json` 或 `data[0].url`。图生图时曾使用顶层 `images` 数组，其中元素为 base64 Data URI。请求和输出必须落盘，并记录模型、提示词版本与输入哈希。

静态关键帧只能表达构图与角色，不能证明视频阶段的推轨、横移、跟拍或口型同步。

## 3. Wan3 视频接口（历史实测）

历史使用：

- 提交：`POST /v1/videos`
- 查询：`GET /v1/videos/{task_id}`
- 成片链接常见于 `metadata.url`

曾实测的参考媒体形态：

```json
{
  "model": "wan3.0-480p",
  "duration": 15,
  "ratio": "16:9",
  "metadata": {
    "parameters": {"audio": true, "prompt_extend": false},
    "media": [
      {"type": "reference_image", "url": "data:image/png;base64,..."},
      {"type": "reference_audio", "url": "data:audio/wav;base64,..."}
    ]
  }
}
```

这只是历史实测样例，不是永恒 schema。当前请求前重新确认字段。

### 关键限制

- Wan3 输出可到 30 秒，但本项目的参考音频总时长上限为 15 秒；使用参考音频的镜头按 ≤15 秒设计。
- `reference_audio` 应是原曲对应的真实时间窗；如未做声部分离，应标为“带伴奏原声”，不要称“纯人声”。
- 不露嘴或不演唱的叙事镜头可以关闭音频参数并省略参考音频，但要确保画面不会出现明显唱歌动作。

## 4. 口型验收

至少同时进行两项：

1. 带声播放与逐字口型人工抽查；
2. 将原曲对应时间窗和生成视频音轨转为 16 kHz 单声道、去均值后计算相关性。

相关性只能判断生成视频是否沿用了输入音轨：历史经验中 `>0.90` 通常通过，约 `0.00` 表示模型自行生成音频。它不能替代逐字口型判定。

短的无字衬词镜头可能被模型忽略。可把参考音频向前扩充几秒生成，再裁回最终窗口；所有裁切、生成和验收信息都应写入 receipt。

## 5. Kie.ai / Suno 历史接口（仅供兼容迁移参考）

历史项目曾直接使用：

- 余额：`GET https://api.kie.ai/api/v1/chat/credit`
- 提交：`POST https://api.kie.ai/api/v1/jobs/createTask`
- 查询：`GET https://api.kie.ai/api/v1/jobs/recordInfo?taskId=...`

历史请求顶层模型为 `ai-music-api/generate`，内部曾使用 `model: "V6"`、`custom_mode`、`lyrics`、`style` 等字段。查询状态位于 `data.state`，成品在字符串形式的 `data.resultJson`，需要二次 JSON 解析。

这些字段属于 Kie.ai 历史实测，不得直接套用于 Salpx。临时音频 URL 必须在返回后及时下载。

## 6. 音乐时间轴与字幕

时间戳结果历史上包含：

```python
aligned = payload["data"]["data"]["alignedWords"]
# 每项：word / startS / endS / success
```

保存完整原始 JSON。以逐词边界分组，自动生成完整 SRT；不要把最后歌词时间误当成全曲时长。前奏和尾奏应由 `ffprobe` 的真实时长减去时间轴覆盖范围得到。

## 7. 费用、防重复和证据

- 价格随模型、时长、歌词长度和账户规则变化；每次生成前读取实时价格并让用户确认批量费用。
- 每镜保存请求体摘要、输入哈希、任务 ID、状态和输出文件。
- 超时先查询任务，不能直接重投。
- 不覆盖失败任务证据；重跑使用新版本号。
- 对旧风格、旧人物和新风格资产分别建目录并在 manifest 标记，防止合成时混用。

## 8. 已知问题

- 图像接口返回 base64 或 URL 的具体形式可能变化。
- 同一模型的生成音轨可能在某些镜头被重新生成；必须逐镜检查相关性。
- 软字幕（`mov_text`）不是烧录字幕；若 FFmpeg 没有 `subtitles` 滤镜，就同时提供独立 SRT 并如实说明。
- 不要用整数 `round()` 代替浮点时间窗，避免丢失词尾。
