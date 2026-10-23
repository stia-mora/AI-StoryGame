# 素材与声音

- `story-cover.webp`：本仓库已有的 `frontend/public/assets/story-covers/hawkins-halloween-v1.webp`，逐字节复制；生成与使用记录见 `docs/design/player-imagery.md`。
- `player-choices-mobile.png`、`player-input-mobile.png`：2026-10-23 从本地 `/play/saves/1125` 手机宽度实际截取；未发送行动，未更改按钮、选项或费用。
- `player-action-excerpt.png`、`player-response-excerpt.png`：同一实际保存的第 4 回合行动及正文的短摘录，取自完整手机截图；用于已保存回合示例，不表示高亮 C 选项已执行。
- `art.js`：本片新绘制的确定性 Canvas 道具插画，不含新生成的人脸或人物图。
- `soundtrack.wav`：`soundtrack.py` 新写的器乐乐谱及程序合成；90 BPM，A 小调，无原剧录音或旋律采样。
- `sfx/click.mp3`、`sfx/impact.mp3`、`sfx/whoosh.mp3`：通过 HyperFrames `media-use resolve --local-only` 从其捆绑音效库取得；分别为 `click`、`impact-bass-1`、`whoosh`。项目运行时 `.media/manifest.jsonl` 保留取得记录。
- `gsap.min.js`：GSAP 3.14.2 官方 npm 包分发文件；用于本地确定性时间轴。
- 中文使用本机 Microsoft YaHei 字体；源工程声明 `local()`，不重新分发字体文件。
