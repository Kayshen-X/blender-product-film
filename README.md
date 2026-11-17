# Blender Product Film

用真实操作录屏和 Blender 做产品功能短片。支持直板和折叠机身，生成可改的 3D 场景、镜头、灯光、屏幕贴图和剪辑时间线。

A Codex skill and standalone Blender Python script for turning real UI footage into editable 3D product demos.

## 在 Codex 里用

```bash
git clone https://github.com/Kayshen-X/blender-product-film.git "${CODEX_HOME:-$HOME/.codex}/skills/blender-product-film"
```

在 Codex 里调用 `$blender-product-film`，并给出录屏和想展示的操作。也可以直接使用下面的脚本。

## 直接用 Blender

用 Blender 5.2 和一段恒定帧率的录屏。配置里的素材路径相对于 JSON 文件。这个例子用一段 24 fps、至少有 120 帧的 `capture.mp4`。

```json
{
  "product": "My App",
  "form": "foldable",
  "fps": 24,
  "shots": [
    {
      "title": "Edit and play",
      "clip": "capture.mp4",
      "frames": 120,
      "preview_at": 48,
      "hold_frames": 12
    }
  ]
}
```

在仓库目录运行以下命令。将 `film.json` 换成你的配置路径。如果 Blender 不在 PATH，把 `blender` 换成它的可执行文件路径。

```bash
blender -b --python-exit-code 1 --python scripts/make_film.py -- film.json ./film-output --preview
```

输出包括 `Product-Film.blend`、`Media/`、`timeline.json` 和 `Previews/`。打开 `01 · Product Stage` 可以改机身、镜头和灯光，在 `02 · Delivery` 预览剪辑并导出。

```bash
blender -b ./film-output/Product-Film.blend --scene '02 · Delivery' --render-anim
```

- [完整配置与可选字段](references/starter-scene.md)
- [录屏、对帧与交付检查](references/recording-and-delivery.md)

## 许可证

源代码和文档采用 [GPL-3.0-or-later](LICENSE)。仓库包含 Skill、脚本和文档。录屏、字体、配乐及图标由使用者提供。
