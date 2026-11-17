# SPDX-License-Identifier: GPL-3.0-or-later

"""Create a Blender product film from a brief and real, constant-rate footage."""

import argparse
import json
import math
from pathlib import Path
import shutil
import sys

import bpy
from mathutils import Matrix, Vector

WIDTH, HEIGHT = 1920, 1080


def parse_brief():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brief", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    args.brief = args.brief.resolve()
    args.output = args.output.resolve()
    brief = json.loads(args.brief.read_text(encoding="utf-8"))
    if not isinstance(brief.get("product"), str) or not brief["product"].strip():
        parser.error("product must be a non-empty name")
    shots = brief.get("shots")
    if not isinstance(shots, list) or not shots:
        parser.error("supply at least one shot with clip, frames, and title")
    if brief.get("form", "slab") not in {"slab", "foldable"}:
        parser.error("form must be slab or foldable")
    fps = brief.get("fps", 24)
    if not isinstance(fps, int) or not 1 <= fps <= 60:
        parser.error("fps must be an integer between 1 and 60")

    def asset(value):
        path = (args.brief.parent / value).resolve()
        if not path.is_file():
            parser.error(f"asset is missing: {path}")
        return path

    for field in ("font", "logo", "score"):
        if brief.get(field):
            brief[field] = asset(brief[field])
    for index, shot in enumerate(shots, 1):
        if not isinstance(shot.get("frames"), int) or shot["frames"] < 1:
            parser.error(f"shot {index} needs a positive frames value")
        hold = shot.get("hold_frames", 6)
        if not isinstance(hold, int) or hold < 0:
            parser.error(f"shot {index} needs a non-negative hold_frames value")
        shot["hold_frames"] = hold
        shot["clip"] = asset(shot["clip"])
    return args, brief, fps


def title_lines(value):
    return value.splitlines() if isinstance(value, str) else value


def linear_color(value):
    digits = value.removeprefix("#")
    if len(digits) != 6:
        raise ValueError(f"expect a six-digit RGB hex color, received {value}")
    rgb = [int(digits[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    return (*(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb), 1)


def emission(name, tint, strength=1.0):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    shader = nodes.new("ShaderNodeEmission")
    shader.inputs["Color"].default_value = linear_color(tint)
    shader.inputs["Strength"].default_value = strength
    out = nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(shader.outputs[0], out.inputs[0])
    return material


def metal(name, tint, metallic, roughness):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    shader = material.node_tree.nodes["Principled BSDF"]
    shader.inputs["Base Color"].default_value = linear_color(tint)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Coat Weight"].default_value = 0.3
    return material


def make_object(scene, name, data=None, parent=None, location=(0, 0, 0)):
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    obj.parent = parent
    obj.location = location
    return obj


def mesh_object(scene, name, verts, faces, material, parent, location):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    mesh.materials.append(material)
    return make_object(scene, name, mesh, parent, location)


def rounded_outline(w, h, radius):
    edges = [
        (w / 2 - radius, h / 2 - radius, 0),
        (-w / 2 + radius, h / 2 - radius, 90),
        (-w / 2 + radius, -h / 2 + radius, 180),
        (w / 2 - radius, -h / 2 + radius, 270),
    ]
    return [
        (x + radius * math.cos(angle), y + radius * math.sin(angle))
        for x, y, direction in edges
        for angle in (math.radians(direction + step * 15) for step in range(7))
    ]


def plate(scene, name, parent, material, size, depth, location, radius=0.38):
    w, h = size
    outline = rounded_outline(w, h, min(w / 2, h / 2, radius))
    n = len(outline)
    verts = [(x, y, z) for z in (-depth, 0) for x, y in outline]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    faces.extend((i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n))
    obj = mesh_object(scene, name, verts, faces, material, parent, location)
    bevel = obj.modifiers.new("Soft machined edges", "BEVEL")
    bevel.width = min(0.063, depth * 0.35)
    bevel.segments = 3
    obj.modifiers.new("Weighted highlights", "WEIGHTED_NORMAL")
    return obj


def panel(scene, name, parent, material, size, location, radius=0):
    w, h = size
    xy = rounded_outline(w, h, radius) if radius else [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    obj = mesh_object(scene, name, [(x, y, 0) for x, y in xy], [tuple(range(len(xy)))], material, parent, location)
    uv = obj.data.uv_layers.new(name="Display")
    for i, (x, y) in enumerate(xy):
        uv.data[i].uv = (x / w + 0.5, y / h + 0.5)
    return obj


def tube(scene, name, parent, material, points, radius):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = radius
    curve.bevel_resolution = 3
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for node, p in zip(spline.points, points):
        node.co = (*p, 1)
    curve.materials.append(material)
    return make_object(scene, name, curve, parent)


def animate(obj, frame, key, value):
    setattr(obj, key, value)
    obj.keyframe_insert(data_path=key, frame=frame)


def pose(obj, frame, location, angles):
    animate(obj, frame, "location", location)
    animate(obj, frame, "rotation_euler", tuple(math.radians(v) for v in angles))


def facing(location, target):
    backward = (Vector(location) - Vector(target)).normalized()
    right = Vector((0, 1, 0)).cross(backward).normalized()
    up = backward.cross(right)
    return Matrix((right, up, backward)).transposed().to_euler()


def aim(cam, frame, location, target, lens):
    animate(cam, frame, "location", location)
    animate(cam, frame, "rotation_euler", facing(location, target))
    animate(cam.data, frame, "lens", lens)


def backdrop(name, tint):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    tex = nodes.new("ShaderNodeTexCoord")
    distance = nodes.new("ShaderNodeVectorMath")
    distance.operation = "DISTANCE"
    distance.inputs[1].default_value = (0.67, 0.52, 0)
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = linear_color(tint)
    ramp.color_ramp.elements[1].position = 0.60
    ramp.color_ramp.elements[1].color = linear_color("#050912")
    shader = nodes.new("ShaderNodeEmission")
    out = nodes.new("ShaderNodeOutputMaterial")
    links.new(tex.outputs["UV"], distance.inputs[0])
    links.new(distance.outputs["Value"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], shader.inputs[0])
    links.new(shader.outputs[0], out.inputs[0])
    return material


def stage(scene, index, start, name, tint):
    root = make_object(scene, name, location=(index * 42, 0, 0))
    panel(scene, "Studio gradient", root, backdrop(name, tint), (36, 21), (0, 0, -3.7))
    cam = make_object(scene, name + " camera", bpy.data.cameras.new(name), root)
    cam.data.clip_start = 0.1
    scene.timeline_markers.new(name, frame=start).camera = cam
    return root, cam


def animate_lights(scene, root, start, end, target, warm):
    settings = [
        ("Moving key", "#A7D8FF", (1, 7, 8), (8, 5, 6), (4, -4, 5), 1240),
        ("Moving rim", warm, (9, -4, 4), (6, -2, 5), (9, 4, 4), 760),
    ]
    for name, tint, first, mid, last, peak in settings:
        data = bpy.data.lights.new(name, "AREA")
        data.shape, data.size, data.size_y = "RECTANGLE", 5.5, 1.35
        data.color = linear_color(tint)[:3]
        lamp = make_object(scene, name, data, root)
        for frame, pos, intensity in [(start, first, peak * 0.37), ((start + end) // 2, mid, peak), (end, last, peak * 0.55)]:
            animate(lamp, frame, "location", pos)
            animate(lamp, frame, "rotation_euler", facing(pos, target))
            animate(data, frame, "energy", intensity)


def texture_material(name, image, start=None, duration=None, alpha=False):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.extension = "EXTEND"
    if start is not None:
        tex.image_user.frame_start = start
        tex.image_user.frame_duration = duration
        tex.image_user.use_auto_refresh = True
    shader = nodes.new("ShaderNodeEmission")
    out = nodes.new("ShaderNodeOutputMaterial")
    links.new(tex.outputs["Color"], shader.inputs["Color"])
    if alpha:
        material.surface_render_method = "DITHERED"
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        mask = nodes.new("ShaderNodeMixShader")
        links.new(tex.outputs["Alpha"], mask.inputs[0])
        links.new(transparent.outputs[0], mask.inputs[1])
        links.new(shader.outputs[0], mask.inputs[2])
        links.new(mask.outputs[0], out.inputs[0])
    else:
        links.new(shader.outputs[0], out.inputs[0])
    return material


def add_text(scene, root, text, position, size, material, font, max_width, centered=False):
    curve = bpy.data.curves.new(text, "FONT")
    curve.body = text
    curve.size = size
    curve.align_x = "CENTER" if centered else "LEFT"
    if font:
        curve.font = font
    curve.materials.append(material)
    obj = make_object(scene, text, curve, root, position)
    bpy.context.view_layer.update()
    if obj.dimensions.x > max_width:
        obj.scale = (max_width / obj.dimensions.x,) * 3
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.convert(target="MESH")
    obj.select_set(False)


def select_font(brief):
    if brief.get("font"):
        return bpy.data.fonts.load(str(brief["font"]))
    display_fields = [brief["product"], str(brief.get("intro", "")), brief.get("intro_note", "")]
    display_fields += [str(shot.get("title", "")) + shot.get("note", "") for shot in brief["shots"]]
    if not any(ord(c) > 255 for c in "".join(display_fields)):
        return None
    candidates = [
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return bpy.data.fonts.load(str(candidate))
    raise RuntimeError("supply a CJK-capable font in the brief")


def heading(scene, root, lines, note, product, materials, font, logo=None):
    white, muted, accent = materials
    if logo:
        panel(scene, "Product mark", root, logo, (0.74, 0.74), (-9.35, 3.55, 0.21))
    add_text(scene, root, product, (-8.78 if logo else -9.74, 3.35, 0.2), 0.58, white, font, 7.95)
    for index, label in enumerate(title_lines(lines)[:2]):
        add_text(scene, root, label, (-9.74, 1.46 - index * 1.72, 0.23), 1.47, white if index == 0 else accent, font, 8.6)
    if note:
        add_text(scene, root, note, (-9.71, -1.55, 0.2), 0.43, muted, font, 8.3)
    tube(scene, "Accent rule", root, accent, [(-9.70, -2.08, 0.13), (-7.78, -2.08, 0.13)], 0.015)


def device(scene, root, size, screen, materials):
    shell, bezel, accent = materials
    w, h = size
    plate(scene, "Metal device body", root, shell, (w + 0.26, h + 0.26), 0.31, (0, 0, 0), 0.48)
    plate(scene, "Glass surround", root, bezel, (w + 0.092, h + 0.092), 0.095, (0, 0, 0.041))
    panel(scene, "Display", root, screen, (w, h), (0, 0, 0.064), 0.27)
    tube(scene, "Rim glint", root, accent, [(-w * 0.39, h / 2 + 0.08, 0.047), (w * 0.39, h / 2 + 0.08, 0.047)], 0.014)


def hero_device(scene, root, form, finish, materials):
    shell, bezel, accent = materials
    rig = make_object(scene, "Feature device", parent=root)
    pose(rig, 1, (4.83, 0.14, 0.37), (21, -23, -16))
    pose(rig, finish * 0.67, (4.67, 0.18, 0.75), (10, -13, -5))
    pose(rig, finish, (4.92, 0.22, 0.63), (8, -5, 1))
    glass = backdrop("Hero display glass", "#29425E")
    if form == "slab":
        device(scene, rig, (5.8, 8.25), glass, materials)
        return
    left = make_object(scene, "Left panel", parent=rig, location=(-2.04, 0, 0))
    pivot = make_object(scene, "Hinge", parent=rig)
    right = make_object(scene, "Right panel", parent=pivot, location=(2.04, 0, 0))
    for part in (left, right):
        device(scene, part, (3.78, 5.92), glass, materials)
    tube(scene, "Titanium hinge spine", rig, shell, [(0, -2.81, -0.075), (0, 2.81, -0.075)], 0.103)
    animate(pivot, 1, "rotation_euler", (0, math.radians(-112), 0))
    animate(pivot, finish * 0.56, "rotation_euler", (0, math.radians(-24), 0))
    animate(pivot, finish, "rotation_euler", (0, math.radians(-5), 0))


def main():
    args, brief, fps = parse_brief()
    output = args.output
    media = output / "Media"
    media.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.name = "01 · Product Stage"
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 12
    scene.render.fps = fps
    scene.render.resolution_x, scene.render.resolution_y = WIDTH, HEIGHT
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Standard"
    scene.world.use_nodes = True
    sky = scene.world.node_tree.nodes["Background"]
    sky.inputs[0].default_value = (0.07, 0.11, 0.17, 1)
    sky.inputs[1].default_value = 0.45

    product, font = brief["product"], select_font(brief)
    tint, warm = brief.get("accent", "#6CEAFF"), brief.get("warm_accent", "#FFB083")
    white = emission("White captions", "#F2F7FF", 1.06)
    muted = emission("Slate captions", "#9DB4D3")
    accent = emission("Edge accent", tint, 1.43)
    secondary = emission("Warm edge accent", warm, 1.32)
    shell = metal("Sapphire titanium", "#6482A0", 0.86, 0.23)
    bezel = metal("Midnight glass", "#182843", 0.44, 0.25)
    logo = None
    if brief.get("logo"):
        image = bpy.data.images.load(str(brief["logo"]))
        image.pack()
        logo = texture_material("Product logo", image, alpha=True)

    intro_end = fps * 3
    hero, cam = stage(scene, 0, 1, "Opening", "#152D4D")
    heading(scene, hero, brief.get("intro", [product, "Product demo"]), brief.get("intro_note", ""),
            product, (white, muted, accent), font, logo)
    hero_device(scene, hero, brief.get("form", "slab"), intro_end, (shell, bezel, accent))
    aim(cam, 1, (7.9, 3.0, 12.2), (4.1, 0.1, 0.42), 37)
    aim(cam, intro_end * 0.64, (1.46, 1.3, 23.3), (0.1, 0.04, 0.2), 33.8)
    aim(cam, intro_end, (3.01, 1.0, 17.7), (2.4, 0.03, 0.21), 33.6)
    animate_lights(scene, hero, 1, intro_end, (4.8, 0.1, 0), warm)

    preview_frames = [1, max(1, int(intro_end * 0.64))]
    timeline = [{"scene": "Opening", "start": 1, "end": intro_end}]
    start = intro_end + 1
    entrance_frames = max(5, round(fps / 4))
    for index, shot in enumerate(brief["shots"], 1):
        clip_start = start + entrance_frames
        end = clip_start + shot["frames"] + shot["hold_frames"] - 1
        name = f"Shot {index:02d}"
        root, cam = stage(scene, index, start, name, "#1C304C")
        highlight = accent if index % 2 else secondary
        heading(scene, root, shot["title"], shot.get("note", ""), product,
                (white, muted, highlight), font, logo)
        target = media / f"shot-{index:02d}{shot['clip'].suffix.lower()}"
        if shot["clip"] != target:
            shutil.copyfile(shot["clip"], target)
        image = bpy.data.images.load(str(target), check_existing=False)
        if image.source != "MOVIE" or not all(image.size):
            raise RuntimeError(f"Blender could not read movie {target}")
        source_width, source_height = image.size
        ratio = source_width / source_height
        image.filepath = f"//Media/{target.name}"
        screen = texture_material("Real operation footage", image, clip_start, shot["frames"])
        w, h = (8.85, 8.85 / ratio) if ratio >= 8.85 / 10.5 else (10.5 * ratio, 10.5)
        rig = make_object(scene, "Recorded display", parent=root)
        direction = 1 if index % 2 else -1
        pose(rig, start, (4.76, 0.04, -0.15), (8, -18 * direction, -2 * direction))
        pose(rig, clip_start + 2, (4.56, 0.08, 0.45), (2.0, -4.5 * direction, 0))
        pose(rig, end, (4.61, 0.08, 0.52), (1.9, 2.0 * direction, 0))
        device(scene, rig, (w, h), screen, (shell, bezel, highlight))
        aim(cam, start, (-1.5 * direction, 1.1, 24.2), (0.3, 0.06, 0.2), 33)
        aim(cam, clip_start + 4, (0.36, 0.61, 22.4), (0.28, 0.07, 0.18), 33)
        aim(cam, end, (0.55, 0.62, 22.0), (0.31, 0.07, 0.18), 33)
        animate_lights(scene, root, start, end, (4.6, 0.08, 0.45), warm)
        offset = min(max(int(shot.get("preview_at", shot["frames"] // 2)), 0), shot["frames"] - 1)
        preview_frames.append(clip_start + offset)
        timeline.append({"scene": name, "start": start, "end": end, "clip_start": clip_start, "clip": f"Media/{target.name}"})
        start = end + 1

    last = start + fps * 2 - 1
    root, cam = stage(scene, len(brief["shots"]) + 1, start, "End", "#1B4154")
    if logo:
        panel(scene, "Product mark", root, logo, (2.45, 2.45), (0, 1.28, 0.22), 0.35)
    add_text(scene, root, product, (0, -1.98 if logo else -0.10, 0.23), 1.42, white, font, 12.0, centered=True)
    aim(cam, start, (0.82, 0.96, 17.9), (0.0, 0.52, 0.22), 34)
    aim(cam, last, (-0.48, 0.8, 22.2), (0.0, 0.04, 0.17), 34)
    timeline.append({"scene": "End", "start": start, "end": last})
    preview_frames.append(last - 2)

    scene.frame_start, scene.frame_end = 1, last
    delivery = bpy.data.scenes.new("02 · Delivery")
    delivery.frame_start, delivery.frame_end = 1, last
    delivery.view_settings.view_transform = "Standard"
    render = delivery.render
    render.resolution_x, render.resolution_y, render.resolution_percentage = WIDTH, HEIGHT, 100
    render.fps = fps
    render.image_settings.media_type = "VIDEO"
    render.image_settings.file_format = "FFMPEG"
    render.ffmpeg.format, render.ffmpeg.codec = "MPEG4", "H264"
    render.ffmpeg.constant_rate_factor = "HIGH"
    render.filepath = "//Product-Film-"
    sequence = delivery.sequence_editor_create()
    shot_track = sequence.strips.new_scene("Product film", scene, 1, 1)
    shot_track.scene_input = "CAMERA"
    if brief.get("score"):
        render.ffmpeg.audio_codec = "AAC"
        sound = sequence.strips.new_sound("Score", str(brief["score"]), 2, 1)
        sound.sound.pack()
        sound.volume = 0.78
    if font and font.users == 0:
        bpy.data.fonts.remove(font)
    scene.frame_set(preview_frames[1])
    delivery.frame_set(preview_frames[1])
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "Product-Film.blend"), compress=True, relative_remap=False)
    metadata = {"fps": fps, "frames": last, "width": WIDTH, "height": HEIGHT, "sound": bool(brief.get("score")), "shots": timeline}
    (output / "timeline.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.preview:
        previews = output / "Previews"
        previews.mkdir(exist_ok=True)
        scene.render.resolution_percentage = 50
        scene.render.image_settings.file_format = "PNG"
        for frame in preview_frames:
            scene.frame_set(frame)
            scene.render.filepath = str(previews / f"Frame-{frame:04d}.png")
            bpy.ops.render.render(scene=scene.name, write_still=True)


if __name__ == "__main__":
    main()
