# 《万圣夜，别松手》C 版宣传片

用户选定的「地下室里的下一步」：地图、对讲机与调查感。40 秒，1080×1920，30 fps；器乐配乐与动作音效版，无旁白。

## 文件

- `STORYBOARD.md`：11 镜内容与取材边界。
- `SPEC.md`：画幅、色板、节奏、文字与声音规格。
- `index.html`、`compositions/`：HyperFrames 可逐镜调整的时间轴。
- `assets/art.js`：新绘制的确定性道具场景；现有封面与玩家截图在 `assets/`。
- `soundtrack.py`：原创器乐配乐与取得音效的混音脚本。
- `assets/CREDITS.md`：素材来源。
- `REVIEW.md`、`审片/`：测量、画面复核与独立审片记录。
- `发布文案.md`：配套发布文案。

渲染文件：`renders/hawkins-halloween-c-final.mp4`。最终通过技能交付检查的副本位于仓库 `output/promo/hawkins-halloween-20261023/delivery/`。生成文件及本地状态不进入 Git。

## 重新制作

需要 FFmpeg、Python、Node.js；本机中文字体使用 Microsoft YaHei 的 `local()` 声明。

```powershell
uv run --with numpy python soundtrack.py
python build_project.py
npx hyperframes check --json
npx hyperframes preview --background
npx hyperframes render --quality delivery --fps 30 --output renders/hawkins-halloween-c-final.mp4
```

`build_project.py` 重建逐镜 HTML，并从本机已安装的 `huashu-art-motion/scripts/engine` 复制一份独立的 QA 适配工程到 `output/`。它使用同一份场景绘制函数；最终 MP4 由 HyperFrames 的分镜时间轴渲染。种子固定，时间是唯一动画输入。

截图来自 `/play/saves/1125` 的现有第 4 回合；素材中保留真实选项、文案和费用。制作未提交任何玩家行动，未消耗玩家积分。剧情片段的宣传表现与实际界面实录分段标注。
