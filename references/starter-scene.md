# Blender 起步工程

`scripts/make_film.py` 会用真实录屏搭一个可改的 16:9 产品演示工程。适用于先搭出灯光、镜头和剪辑，再调整设计的场景。用可靠的本机 Blender 路径，按本次交付选择目录。脚本在 Blender 5.2 上验证。

## 配置与运行

将如下 JSON 按素材内容调整，保存为 `film.json`。相对路径以 JSON 所在目录解析。 `frames` 填目标帧率下实际可用的帧数。可选 `preview_at` 为实录内最需要看清的帧，首帧是 0。

```json
{
  "product": "OpenPencil",
  "intro": ["折叠时", "继续设计"],
  "intro_note": "iPhone Duo 功能演示",
  "form": "foldable",
  "fps": 24,
  "accent": "#6CEAFF",
  "warm_accent": "#FFB083",
  "font": "/absolute/path/to/a/CJK-font.ttc",
  "logo": "openpencil-logo.png",
  "score": "music.wav",
  "shots": [
    {
      "title": ["合盖时", "工具在右边"],
      "note": "原生工具栏与形状菜单",
      "clip": "outer.mp4",
      "frames": 150,
      "preview_at": 45
    },
    {
      "title": ["半折时", "上屏预览"],
      "note": "下屏继续编辑",
      "clip": "inner.mp4",
      "frames": 132,
      "hold_frames": 12,
      "preview_at": 70
    }
  ]
}
```

`form` 可用 `slab` 或 `foldable`，默认 `slab`。`logo`、`font`、`score` 可省略。有中文时可用已安装的 CJK 字体，找不到就传实际字体路径。标题转成几何以便换电脑打开，改字可修改 JSON 重建或在 Blender 中替换文字对象。片尾根据产品名生成，配乐从第一帧开始，可在剪辑场景调整。

```bash
"$blender" -b --python-exit-code 1 \
  --python "$skill_dir/scripts/make_film.py" -- film.json ./film-output --preview
```

生成 `Product-Film.blend`、含视频的 `Media/`、`timeline.json` 和可选 `Previews/`。从预览检查构图和操作画面，素材命名不同时可使用对应的 `timeline.json`。修改或删除测试配置后，使用 Blender 打开 `01 · Product Stage` 调模型、灯光、镜头和场景标记，用 `02 · Delivery` 做最终输出。将生成目录与原始录屏分开，便于移动工程。

```bash
"$blender" -b ./film-output/Product-Film.blend --scene '02 · Delivery' --render-anim
```

全片渲染结束再抽帧确认。要移动工程，把 `Product-Film.blend` 与 `Media/` 放在一起，运行 [交付检查](recording-and-delivery.md)。
