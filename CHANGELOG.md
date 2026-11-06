# Changelog

所有值得记录的变更。版本号遵循 `MAJOR.MINOR`，技能未到 1.0 前不保证向后兼容。

## v0.2 — 2026-11-05

**新增**

- `scripts/align_words.py`：本地 faster-whisper 词级对齐，把歌曲转成 `alignedWords` JSON（含 `meta`：真实时长、首词/末词时间、前奏/尾奏、>2s 间隙、低置信词数），可选同时输出 SRT。
- `references/api_reference.md` 新增「本机实测」章节：Salpx 真实价目、`/suno/submit/MUSIC` 完整请求/返回结构、Wan3 整数时长约束、成片链接 24 小时过期、模型目录与价格接口。
- 技能改名为 `xiaom`（中文名**小m**），frontmatter 增加 `title` 与 `version`。

**修复**

- `mv_workflow.py make-srt` 对所有语言都用空字符串拼接，英文会粘成 `AndsomyfellowAmericans`。现在按字符集判断：中日韩不加空格，拉丁语系加空格。
- `align_words.py` 在 Windows 上无法加载 CUDA 库（`cublas64_12.dll is not found`）。现在自动注册 `site-packages/nvidia/*/bin`。

**已知限制**

- 对齐是 ASR 词级时间，不是强制对齐；中文带伴奏歌声的精度待验证。
- 视频时长必须是 2–30 的整数秒，浮点窗口需要向上取整后裁回。

## v0.1 — 2026-11-05

- 首个版本：8 阶段工作流（盘点 → 出歌 → 时间轴 → 分镜 → 关键帧 → 图音视频 → 口型验收 → 合成）。
- `scripts/mv_workflow.py`：分镜 manifest 离线校验（时长上限、时间连续性、lipsync 镜音频标记、重复编号）+ SRT 生成。
- `references/api_reference.md`：Salpx / Suno / Wan3 / Kie.ai 接口形态与验收指标。
