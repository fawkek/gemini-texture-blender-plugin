bl_info = {
    "name": "Gemini Texture Generator",
    "author": "Igor Shevchenko",
    "version": (1, 1, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Gemini Tex",
    "description": "Generate Gemini textures, preview them, save them locally, build helper maps, and apply them in Blender",
    "category": "Material",
}

import base64
import json
import math
import os
import re
import tempfile
import urllib.error
import urllib.request
from datetime import datetime

import bpy
from bpy.props import BoolProperty
from bpy.props import EnumProperty
from bpy.props import FloatProperty
from bpy.props import PointerProperty
from bpy.props import StringProperty


API_KEY_URL = "https://aistudio.google.com/app/apikey"
ADDON_ID = __name__
FREE_IMAGE_MODEL = "gemini-2.0-flash-preview-image-generation"
PAID_IMAGE_MODEL = "gemini-2.5-flash-image"
DEFAULT_MODEL = FREE_IMAGE_MODEL
MODEL_ALIASES = {
    "gemini-2.5-flash-preview-image": PAID_IMAGE_MODEL,
    "gemini-2.5-flash-image-preview": PAID_IMAGE_MODEL,
}
def default_output_dir():
    return os.path.join(os.path.expanduser("~"), "BlenderGeminiTextures")


def blend_relative_output_dir():
    if not bpy.data.filepath:
        return ""
    blend_dir = os.path.dirname(bpy.data.filepath)
    return os.path.join(blend_dir, "Textures")


def get_prefs():
    return bpy.context.preferences.addons[ADDON_ID].preferences


def ensure_output_dir():
    prefs = get_prefs()
    preferred_dir = blend_relative_output_dir() or prefs.output_dir or default_output_dir()
    output_dir = bpy.path.abspath(preferred_dir)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def get_settings(context):
    return context.scene.gemini_texture_settings


def image_basename():
    return datetime.now().strftime("gemini_texture_%Y%m%d_%H%M%S")


def prompt_slug(prompt):
    words = re.findall(r"[A-Za-zА-Яа-я0-9]+", prompt or "")
    words = [word.lower() for word in words[:2] if word]
    if not words:
        return "gemini_texture"
    return "_".join(words)


def build_asset_base_name(prompt):
    slug = prompt_slug(prompt)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{slug}_{timestamp}"


def get_history_base_paths():
    output_dir = ensure_output_dir()
    entries = []
    if os.path.isdir(output_dir):
        for file_name in sorted(os.listdir(output_dir), reverse=True):
            if file_name.endswith("_base.png"):
                entries.append(os.path.join(output_dir, file_name))
    return entries


def find_history_index(current_path):
    entries = get_history_base_paths()
    if not entries:
        return entries, -1

    if current_path in entries:
        return entries, entries.index(current_path)

    if current_path and os.path.exists(current_path):
        return entries, 0

    return entries, 0


def normalize_model_name(model_name):
    model_name = (model_name or "").strip()
    if not model_name:
        return FREE_IMAGE_MODEL
    return MODEL_ALIASES.get(model_name, model_name)


def resolve_model_name(settings):
    if settings.model_preset == "FREE_2_FLASH_IMAGE":
        return FREE_IMAGE_MODEL
    if settings.model_preset == "PAID_25_FLASH_IMAGE":
        return PAID_IMAGE_MODEL
    return normalize_model_name(settings.model_name)


def cleanup_image_reference(image):
    if image and image.users == 0:
        try:
            bpy.data.images.remove(image)
        except RuntimeError:
            pass


def clear_generated_images(settings):
    cleanup_image_reference(settings.preview_image)
    cleanup_image_reference(settings.normal_image)
    cleanup_image_reference(settings.roughness_image)
    cleanup_image_reference(settings.metallic_image)

    settings.preview_image = None
    settings.normal_image = None
    settings.roughness_image = None
    settings.metallic_image = None
    settings.preview_image_path = ""
    settings.normal_image_path = ""
    settings.roughness_image_path = ""
    settings.metallic_image_path = ""
    settings.base_name = ""


def load_existing_image(path, name):
    image = bpy.data.images.load(path, check_existing=False)
    image.name = name
    return image


def build_prompt(settings):
    prompt = settings.prompt.strip()
    if not prompt:
        raise ValueError("Введите текстовый промпт.")

    hints = [
        "Create a high quality PBR-friendly texture for 3D material use.",
        "Avoid text, logos, labels, frames, perspective, and floating objects.",
        "Keep the texture evenly lit and suitable for material authoring.",
    ]

    if settings.seamless:
        hints.append("The texture must be perfectly seamless and tileable on all sides.")

    if settings.size_mode == "FIXED_1024":
        hints.append("Generate a square 1:1 texture intended for 1024x1024 output.")
    else:
        hints.append(
            f"Use aspect ratio {settings.aspect_ratio.replace('_', ':')} while keeping the texture useful for surfaces."
        )

    return f"{prompt}\n\n" + " ".join(hints)


def request_gemini_image(settings):
    api_key = get_prefs().saved_api_key.strip()
    if not api_key:
        raise ValueError("Укажите Gemini API key в Add-on Preferences.")

    model = resolve_model_name(settings)
    if model == PAID_IMAGE_MODEL and not settings.allow_paid_model:
        raise ValueError(
            "Выбрана платная модель Gemini 2.5 Flash Image. "
            "Включите галочку подтверждения paid model или переключитесь на FREE модель."
        )

    payload = {
        "contents": [{"parts": [{"text": build_prompt(settings)}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": "1:1"
                if settings.size_mode == "FIXED_1024"
                else settings.aspect_ratio.replace("_", ":")
            },
        },
    }

    if settings.size_mode == "FREE" and model.startswith("gemini-3"):
        payload["generationConfig"]["imageConfig"]["imageSize"] = settings.free_image_size

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(format_http_error(exc.code, details, model)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error while calling Gemini API: {exc}") from exc

    data = json.loads(raw)
    for candidate in data.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])

    raise RuntimeError("Gemini не вернул изображение. Попробуйте другой промпт или модель.")


def format_http_error(status_code, details, model):
    try:
        payload = json.loads(details)
    except json.JSONDecodeError:
        return f"Gemini API error {status_code}: {details}"

    error = payload.get("error") or {}
    message = (error.get("message") or "").strip()

    if status_code == 429:
        return (
            "Лимит Gemini исчерпан для проекта/модели.\n"
            f"Модель: {model}\n"
            "Что это значит: квоты считаются на проект, а не на отдельный API key.\n"
            "Что сделать: подождать сброса лимита, проверить AI Studio Rate Limits, "
            "или перейти на paid tier/другой проект."
        )

    if message:
        return f"Gemini API error {status_code}: {message}"
    return f"Gemini API error {status_code}"


def save_bytes_and_load_image(image_bytes, file_path, image_name):
    with open(file_path, "wb") as handle:
        handle.write(image_bytes)
    return load_existing_image(file_path, image_name)


def create_preview_image(settings, image_bytes):
    output_dir = ensure_output_dir()
    clear_generated_images(settings)

    base_name = build_asset_base_name(settings.prompt)
    preview_path = os.path.join(output_dir, f"{base_name}_base.png")
    image = save_bytes_and_load_image(image_bytes, preview_path, f"{base_name}_base")

    settings.base_name = base_name
    settings.preview_image = image
    settings.preview_image_path = preview_path
    return image


def load_texture_set_from_base_path(settings, base_path):
    if not base_path or not os.path.exists(base_path):
        raise RuntimeError("Выбранная генерация не найдена.")

    output_dir = os.path.dirname(base_path)
    file_name = os.path.basename(base_path)
    if not file_name.endswith("_base.png"):
        raise RuntimeError("Нужен файл базовой текстуры с суффиксом _base.png.")

    base_name = file_name[:-9]
    clear_generated_images(settings)

    settings.base_name = base_name
    settings.preview_image_path = base_path
    settings.preview_image = load_existing_image(base_path, f"{base_name}_base")

    normal_path = os.path.join(output_dir, f"{base_name}_normal.png")
    roughness_path = os.path.join(output_dir, f"{base_name}_roughness.png")
    metallic_path = os.path.join(output_dir, f"{base_name}_metallic.png")

    if os.path.exists(normal_path):
        settings.normal_image_path = normal_path
        settings.normal_image = load_existing_image(normal_path, f"{base_name}_normal")
        settings.normal_image.colorspace_settings.name = "Non-Color"

    if os.path.exists(roughness_path):
        settings.roughness_image_path = roughness_path
        settings.roughness_image = load_existing_image(roughness_path, f"{base_name}_roughness")
        settings.roughness_image.colorspace_settings.name = "Non-Color"

    if os.path.exists(metallic_path):
        settings.metallic_image_path = metallic_path
        settings.metallic_image = load_existing_image(metallic_path, f"{base_name}_metallic")
        settings.metallic_image.colorspace_settings.name = "Non-Color"


def save_image_to_path(image, path):
    image.filepath_raw = path
    image.file_format = "PNG"
    image.save()


def ensure_image_saved(image, fallback_path):
    if not image:
        return
    path = image.filepath_raw or image.filepath or fallback_path
    path = bpy.path.abspath(path)
    save_image_to_path(image, path)


def get_material_name(settings):
    base_name = settings.base_name or "GeminiTexture"
    return f"{base_name}_mat"


def assign_image_node(nodes, links, image, label, location, colorspace, projection=None):
    node = nodes.new("ShaderNodeTexImage")
    node.label = label
    node.name = label
    node.location = location
    node.image = image
    node.image.colorspace_settings.name = colorspace
    if projection:
        node.projection = projection
        node.projection_blend = 0.1
    return node


def ensure_material_for_object(obj, settings, use_box_projection=False):
    base_image = settings.preview_image
    if base_image is None:
        raise RuntimeError("Сначала сгенерируйте текстуру.")

    material_name = get_material_name(settings)
    material = bpy.data.materials.get(material_name)
    if material is None:
        material = bpy.data.materials.new(name=material_name)

    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output_node = nodes.new("ShaderNodeOutputMaterial")
    output_node.location = (650, 0)
    bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf_node.location = (350, 0)
    texcoord_node = nodes.new("ShaderNodeTexCoord")
    texcoord_node.location = (-900, 0)
    mapping_node = nodes.new("ShaderNodeMapping")
    mapping_node.location = (-650, 0)

    vector_output_name = "Object" if use_box_projection else "UV"
    projection_mode = "BOX" if use_box_projection else None

    base_node = assign_image_node(
        nodes,
        links,
        base_image,
        "Base Color",
        (-350, 140),
        "sRGB",
        projection=projection_mode,
    )
    links.new(texcoord_node.outputs[vector_output_name], mapping_node.inputs["Vector"])
    links.new(mapping_node.outputs["Vector"], base_node.inputs["Vector"])
    links.new(base_node.outputs["Color"], bsdf_node.inputs["Base Color"])

    if settings.roughness_image:
        roughness_node = assign_image_node(
            nodes,
            links,
            settings.roughness_image,
            "Roughness",
            (-350, -60),
            "Non-Color",
            projection=projection_mode,
        )
        links.new(mapping_node.outputs["Vector"], roughness_node.inputs["Vector"])
        links.new(roughness_node.outputs["Color"], bsdf_node.inputs["Roughness"])

    if settings.metallic_image:
        metallic_node = assign_image_node(
            nodes,
            links,
            settings.metallic_image,
            "Metallic",
            (-350, -260),
            "Non-Color",
            projection=projection_mode,
        )
        links.new(mapping_node.outputs["Vector"], metallic_node.inputs["Vector"])
        links.new(metallic_node.outputs["Color"], bsdf_node.inputs["Metallic"])

    if settings.normal_image:
        normal_tex_node = assign_image_node(
            nodes,
            links,
            settings.normal_image,
            "Normal",
            (-350, -460),
            "Non-Color",
            projection=projection_mode,
        )
        normal_map_node = nodes.new("ShaderNodeNormalMap")
        normal_map_node.location = (80, -460)
        links.new(mapping_node.outputs["Vector"], normal_tex_node.inputs["Vector"])
        links.new(normal_tex_node.outputs["Color"], normal_map_node.inputs["Color"])
        links.new(normal_map_node.outputs["Normal"], bsdf_node.inputs["Normal"])

    links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])

    material_index = None
    for idx, slot in enumerate(obj.data.materials):
        if slot == material:
            material_index = idx
            break

    if material_index is None:
        obj.data.materials.append(material)
        material_index = len(obj.data.materials) - 1

    return material, material_index


def apply_material_to_current_selection(context, settings, create_uv_if_missing=False):
    obj = context.active_object
    if obj is None or obj.type != "MESH":
        raise RuntimeError("Выберите mesh-объект.")

    original_mode = obj.mode
    use_box_projection = create_uv_if_missing and not obj.data.uv_layers
    material, material_index = ensure_material_for_object(
        obj,
        settings,
        use_box_projection=use_box_projection,
    )

    if original_mode == "OBJECT":
        if create_uv_if_missing and not obj.data.uv_layers:
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.02)
            bpy.ops.uv.cube_project(cube_size=1.0, correct_aspect=True, clip_to_bounds=False)
        else:
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
    else:
        bpy.ops.mesh.select_mode(type="FACE")
        if create_uv_if_missing and not obj.data.uv_layers:
            bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.02)
            bpy.ops.uv.cube_project(cube_size=1.0, correct_aspect=True, clip_to_bounds=False)

    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.object.material_slot_assign()

    mesh = obj.data
    if original_mode == "EDIT":
        import bmesh

        bm = bmesh.from_edit_mesh(mesh)
        selected_faces = [face for face in bm.faces if face.select]
        if not selected_faces:
            raise RuntimeError("В Edit Mode выберите хотя бы один полигон.")
        for face in selected_faces:
            face.material_index = material_index
        bmesh.update_edit_mesh(mesh)
    else:
        bpy.ops.object.mode_set(mode="OBJECT")
        for polygon in mesh.polygons:
            polygon.material_index = material_index

    if original_mode != "EDIT":
        bpy.ops.object.mode_set(mode=original_mode)

    return material


def image_to_rgb_grid(image):
    width, height = image.size[:]
    pixels = list(image.pixels[:])
    rgb = [[(0.0, 0.0, 0.0) for _x in range(width)] for _y in range(height)]

    idx = 0
    for y in range(height):
        for x in range(width):
            rgb[y][x] = (pixels[idx], pixels[idx + 1], pixels[idx + 2])
            idx += 4
    return rgb, width, height


def image_to_luminance(rgb_grid, width, height):
    luminance = [[0.0 for _x in range(width)] for _y in range(height)]
    for y in range(height):
        for x in range(width):
            r, g, b = rgb_grid[y][x]
            luminance[y][x] = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return luminance


def build_rgba_pixels_from_gray(gray_grid, width, height):
    pixels = []
    for y in range(height):
        for x in range(width):
            value = min(max(gray_grid[y][x], 0.0), 1.0)
            pixels.extend((value, value, value, 1.0))
    return pixels


def build_normal_pixels(gray_grid, width, height, strength):
    pixels = []
    for y in range(height):
        y0 = max(y - 1, 0)
        y1 = min(y + 1, height - 1)
        for x in range(width):
            x0 = max(x - 1, 0)
            x1 = min(x + 1, width - 1)

            dx = (gray_grid[y][x1] - gray_grid[y][x0]) * strength
            dy = (gray_grid[y1][x] - gray_grid[y0][x]) * strength
            nx = -dx
            ny = -dy
            nz = 1.0
            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            nx /= length
            ny /= length
            nz /= length
            pixels.extend(((nx + 1.0) * 0.5, (ny + 1.0) * 0.5, (nz + 1.0) * 0.5, 1.0))
    return pixels


def create_image_from_pixels(name, width, height, pixels, path):
    image = bpy.data.images.new(name=name, width=width, height=height, alpha=False)
    image.pixels = pixels
    image.filepath_raw = path
    image.file_format = "PNG"
    image.save()
    image.reload()
    return image


def pad_image_to_square(image, square_size):
    src_width, src_height = image.size[:]
    if src_width <= 0 or src_height <= 0:
        raise RuntimeError("У изображения некорректный размер.")

    source_pixels = list(image.pixels[:])
    canvas = [0.0] * (square_size * square_size * 4)
    offset_x = (square_size - src_width) // 2
    offset_y = (square_size - src_height) // 2

    for y in range(src_height):
        for x in range(src_width):
            src_index = (y * src_width + x) * 4
            dst_x = x + offset_x
            dst_y = y + offset_y
            dst_index = (dst_y * square_size + dst_x) * 4
            canvas[dst_index:dst_index + 4] = source_pixels[src_index:src_index + 4]

    image.scale(square_size, square_size)
    image.pixels = canvas
    image.update()


def generate_helper_maps(settings):
    base_image = settings.preview_image
    if base_image is None:
        raise RuntimeError("Сначала сгенерируйте текстуру.")

    output_dir = ensure_output_dir()
    rgb_grid, width, height = image_to_rgb_grid(base_image)
    gray_grid = image_to_luminance(rgb_grid, width, height)

    roughness_grid = [
        [min(max(0.25 + gray_grid[y][x] * 0.75, 0.0), 1.0) for x in range(width)]
        for y in range(height)
    ]
    metallic_grid = [[0.0 for _x in range(width)] for _y in range(height)]
    normal_pixels = build_normal_pixels(gray_grid, width, height, settings.normal_strength)

    cleanup_image_reference(settings.normal_image)
    cleanup_image_reference(settings.roughness_image)
    cleanup_image_reference(settings.metallic_image)

    base_name = settings.base_name or image_basename()
    normal_path = os.path.join(output_dir, f"{base_name}_normal.png")
    roughness_path = os.path.join(output_dir, f"{base_name}_roughness.png")
    metallic_path = os.path.join(output_dir, f"{base_name}_metallic.png")

    roughness_pixels = build_rgba_pixels_from_gray(roughness_grid, width, height)
    metallic_pixels = build_rgba_pixels_from_gray(metallic_grid, width, height)

    settings.normal_image = create_image_from_pixels(
        f"{base_name}_normal", width, height, normal_pixels, normal_path
    )
    settings.roughness_image = create_image_from_pixels(
        f"{base_name}_roughness", width, height, roughness_pixels, roughness_path
    )
    settings.metallic_image = create_image_from_pixels(
        f"{base_name}_metallic", width, height, metallic_pixels, metallic_path
    )

    settings.normal_image.colorspace_settings.name = "Non-Color"
    settings.roughness_image.colorspace_settings.name = "Non-Color"
    settings.metallic_image.colorspace_settings.name = "Non-Color"

    settings.normal_image_path = normal_path
    settings.roughness_image_path = roughness_path
    settings.metallic_image_path = metallic_path


def resize_image_in_place(image, size, pad_to_square=False):
    if image is None:
        raise RuntimeError("Сначала сгенерируйте текстуру.")
    width, height = image.size[:]
    if width <= 0 or height <= 0:
        raise RuntimeError("У изображения некорректный размер.")

    if width >= height:
        new_width = size
        new_height = max(1, round(height * (size / width)))
    else:
        new_height = size
        new_width = max(1, round(width * (size / height)))

    image.scale(new_width, new_height)
    if pad_to_square:
        pad_image_to_square(image, size)


def resize_texture_set(settings, size):
    resize_image_in_place(settings.preview_image, size, settings.pad_to_square)
    ensure_image_saved(
        settings.preview_image,
        settings.preview_image_path or os.path.join(ensure_output_dir(), f"{settings.base_name}_base.png"),
    )

    for image, path in (
        (settings.normal_image, settings.normal_image_path),
        (settings.roughness_image, settings.roughness_image_path),
        (settings.metallic_image, settings.metallic_image_path),
    ):
        if image:
            resize_image_in_place(image, size, settings.pad_to_square)
            ensure_image_saved(image, path)


def save_all_images(settings):
    output_dir = ensure_output_dir()
    base_name = settings.base_name or image_basename()

    if settings.preview_image:
        settings.preview_image_path = settings.preview_image_path or os.path.join(
            output_dir, f"{base_name}_base.png"
        )
        ensure_image_saved(settings.preview_image, settings.preview_image_path)

    if settings.normal_image:
        settings.normal_image_path = settings.normal_image_path or os.path.join(
            output_dir, f"{base_name}_normal.png"
        )
        ensure_image_saved(settings.normal_image, settings.normal_image_path)

    if settings.roughness_image:
        settings.roughness_image_path = settings.roughness_image_path or os.path.join(
            output_dir, f"{base_name}_roughness.png"
        )
        ensure_image_saved(settings.roughness_image, settings.roughness_image_path)

    if settings.metallic_image:
        settings.metallic_image_path = settings.metallic_image_path or os.path.join(
            output_dir, f"{base_name}_metallic.png"
        )
        ensure_image_saved(settings.metallic_image, settings.metallic_image_path)


class GeminiAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    saved_api_key: StringProperty(
        name="Saved API Key",
        subtype="PASSWORD",
        description="Stored Gemini API key",
    )
    output_dir: StringProperty(
        name="Output Folder",
        subtype="DIR_PATH",
        default=default_output_dir(),
        description="Folder for generated textures and helper maps",
    )

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "saved_api_key")
        col.prop(self, "output_dir")
        col.operator("gemini.open_api_key_page", icon="URL")


class GeminiTextureSettings(bpy.types.PropertyGroup):
    model_preset: EnumProperty(
        name="Model Preset",
        description="Choose free or paid Gemini image model",
        items=[
            (
                "FREE_2_FLASH_IMAGE",
                "FREE - Gemini 2.0 Flash Image",
                "Free-tier image generation model when available for your Google AI Studio project",
            ),
            (
                "PAID_25_FLASH_IMAGE",
                "PAID - Gemini 2.5 Flash Image / Nano Banana",
                "Paid native image generation model. Can charge your billing account",
            ),
            (
                "CUSTOM",
                "Custom model",
                "Use the custom model field below",
            ),
        ],
        default="FREE_2_FLASH_IMAGE",
    )
    allow_paid_model: BoolProperty(
        name="I understand this model can charge billing",
        default=False,
        description="Required before using the paid Gemini 2.5 Flash Image model",
    )
    prompt: StringProperty(
        name="Prompt",
        description="Describe the texture you want to generate",
    )
    seamless: BoolProperty(
        name="Seamless",
        description="Request a seamless tileable texture",
        default=True,
    )
    size_mode: EnumProperty(
        name="Size Mode",
        items=[
            ("FIXED_1024", "1024x1024", "Generate a square texture for 1024x1024 output"),
            ("FREE", "Free", "Use free aspect ratio settings"),
        ],
        default="FIXED_1024",
    )
    aspect_ratio: EnumProperty(
        name="Aspect Ratio",
        items=[
            ("1_1", "1:1", ""),
            ("3_2", "3:2", ""),
            ("2_3", "2:3", ""),
            ("4_3", "4:3", ""),
            ("3_4", "3:4", ""),
            ("16_9", "16:9", ""),
            ("9_16", "9:16", ""),
            ("21_9", "21:9", ""),
        ],
        default="1_1",
    )
    model_name: StringProperty(
        name="Custom Model",
        description="Gemini image model name",
        default=FREE_IMAGE_MODEL,
    )
    free_image_size: EnumProperty(
        name="Quality",
        items=[
            ("1K", "1K", "Default Gemini 3 image size"),
            ("2K", "2K", "Higher output size for Gemini 3 image models"),
            ("4K", "4K", "Highest output size for Gemini 3 image models"),
        ],
        default="1K",
    )
    normal_strength: FloatProperty(
        name="Normal Strength",
        default=4.0,
        min=0.1,
        max=20.0,
        description="Strength for generated normal map",
    )
    pad_to_square: BoolProperty(
        name="Pad to Square for UE",
        default=False,
        description="Keep aspect ratio and add padding so the resized result becomes square",
    )
    preview_image: PointerProperty(name="Preview Image", type=bpy.types.Image)
    normal_image: PointerProperty(name="Normal Image", type=bpy.types.Image)
    roughness_image: PointerProperty(name="Roughness Image", type=bpy.types.Image)
    metallic_image: PointerProperty(name="Metallic Image", type=bpy.types.Image)
    base_name: StringProperty(name="Base Name", default="", options={"HIDDEN"})
    preview_image_path: StringProperty(name="Preview Image Path", default="", options={"HIDDEN"})
    normal_image_path: StringProperty(name="Normal Image Path", default="", options={"HIDDEN"})
    roughness_image_path: StringProperty(name="Roughness Image Path", default="", options={"HIDDEN"})
    metallic_image_path: StringProperty(name="Metallic Image Path", default="", options={"HIDDEN"})


class GEMINI_OT_open_api_key_page(bpy.types.Operator):
    bl_idname = "gemini.open_api_key_page"
    bl_label = "Get API Key"
    bl_description = "Open Google AI Studio API key page"

    def execute(self, context):
        bpy.ops.wm.url_open(url=API_KEY_URL)
        return {"FINISHED"}


class GEMINI_OT_generate_texture(bpy.types.Operator):
    bl_idname = "gemini.generate_texture"
    bl_label = "Generate Texture"
    bl_description = "Generate a texture with Gemini and show preview"

    def execute(self, context):
        settings = get_settings(context)
        settings.model_name = normalize_model_name(settings.model_name)
        try:
            image = create_preview_image(settings, request_gemini_image(settings))
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, f"Texture generated and saved locally: {image.name}")
        return {"FINISHED"}


class GEMINI_OT_generate_maps(bpy.types.Operator):
    bl_idname = "gemini.generate_maps"
    bl_label = "Generate Maps"
    bl_description = "Build normal, roughness, and metallic helper maps from the preview"

    def execute(self, context):
        settings = get_settings(context)
        try:
            generate_helper_maps(settings)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, "Normal, roughness, and metallic maps generated.")
        return {"FINISHED"}


class GEMINI_OT_browse_history(bpy.types.Operator):
    bl_idname = "gemini.browse_history"
    bl_label = "Browse History"
    bl_description = "Load previous or next saved generation into preview"

    direction: EnumProperty(
        name="Direction",
        items=[
            ("PREV", "Previous", ""),
            ("NEXT", "Next", ""),
        ],
    )

    def execute(self, context):
        settings = get_settings(context)
        entries, current_index = find_history_index(settings.preview_image_path)

        if not entries:
            self.report({"ERROR"}, "Сохранённые генерации не найдены.")
            return {"CANCELLED"}

        if current_index < 0:
            target_index = 0
        elif self.direction == "PREV":
            target_index = min(current_index + 1, len(entries) - 1)
        else:
            target_index = max(current_index - 1, 0)

        try:
            load_texture_set_from_base_path(settings, entries[target_index])
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, "Generation loaded into preview.")
        return {"FINISHED"}


class GEMINI_OT_apply_texture(bpy.types.Operator):
    bl_idname = "gemini.apply_texture"
    bl_label = "Apply To Selection/Object"
    bl_description = "Apply the preview texture to selected faces or the active object"

    def execute(self, context):
        settings = get_settings(context)
        try:
            apply_material_to_current_selection(context, settings, create_uv_if_missing=False)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, "Texture applied with box projection.")
        return {"FINISHED"}


class GEMINI_OT_apply_texture_auto_uv(bpy.types.Operator):
    bl_idname = "gemini.apply_texture_auto_uv"
    bl_label = "Apply + Create UV If Missing"
    bl_description = "Apply texture and create UVs first if the mesh does not have them"

    def execute(self, context):
        settings = get_settings(context)
        try:
            apply_material_to_current_selection(context, settings, create_uv_if_missing=True)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, "Texture applied. Missing UVs were created automatically.")
        return {"FINISHED"}


class GEMINI_OT_resize_texture(bpy.types.Operator):
    bl_idname = "gemini.resize_texture"
    bl_label = "Resize Texture"
    bl_description = "Resize the generated texture set in place"

    target_size: EnumProperty(
        name="Target Size",
        items=[
            ("512", "512", ""),
            ("256", "256", ""),
            ("128", "128", ""),
        ],
    )

    def execute(self, context):
        settings = get_settings(context)
        try:
            resize_texture_set(settings, int(self.target_size))
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, f"Texture set resized to {self.target_size}x{self.target_size}.")
        return {"FINISHED"}


class GEMINI_OT_save_images(bpy.types.Operator):
    bl_idname = "gemini.save_images"
    bl_label = "Save Locally"
    bl_description = "Save the generated texture and helper maps to the output folder"

    def execute(self, context):
        settings = get_settings(context)
        try:
            save_all_images(settings)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, f"Saved images to: {ensure_output_dir()}")
        return {"FINISHED"}


class GEMINI_OT_clear_preview(bpy.types.Operator):
    bl_idname = "gemini.clear_preview"
    bl_label = "Clear Preview"
    bl_description = "Remove the current preview and helper maps from Blender"

    def execute(self, context):
        clear_generated_images(get_settings(context))
        self.report({"INFO"}, "Preview and helper maps cleared from Blender.")
        return {"FINISHED"}


class GEMINI_PT_texture_panel(bpy.types.Panel):
    bl_label = "Gemini Texture"
    bl_idname = "GEMINI_PT_texture_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Gemini Tex"

    def draw(self, context):
        layout = self.layout
        settings = get_settings(context)
        prefs = get_prefs()

        info_box = layout.box()
        info_box.label(text="API Key is configured in Add-on Preferences.", icon="KEYINGSET")
        if prefs.saved_api_key:
            info_box.label(text="Saved key found.", icon="CHECKMARK")
        else:
            info_box.label(text="No saved key yet. Add it in Preferences.", icon="ERROR")

        settings_box = layout.box()
        settings_box.label(text="Generation", icon="TEXTURE")
        settings_box.prop(settings, "model_preset")
        if settings.model_preset == "FREE_2_FLASH_IMAGE":
            settings_box.label(text="FREE model selected: no paid image output billing.", icon="CHECKMARK")
            settings_box.label(text="Free quotas and availability depend on your AI Studio project.", icon="INFO")
        elif settings.model_preset == "PAID_25_FLASH_IMAGE":
            settings_box.label(text="PAID model selected: can charge your billing account.", icon="ERROR")
            settings_box.prop(settings, "allow_paid_model")
        else:
            settings_box.prop(settings, "model_name")
            if "preview" in settings.model_name.lower():
                settings_box.label(text="Preview models often have stricter quotas.", icon="ERROR")
        settings_box.prop(settings, "prompt")
        settings_box.prop(settings, "seamless")
        settings_box.prop(settings, "size_mode", expand=True)
        if settings.size_mode == "FREE":
            settings_box.prop(settings, "aspect_ratio")
            active_model = resolve_model_name(settings)
            if active_model.startswith("gemini-3"):
                settings_box.prop(settings, "free_image_size")
            else:
                settings_box.label(text="This model usually outputs around 1024px.", icon="INFO")
        settings_box.operator("gemini.generate_texture", icon="RENDER_STILL")

        save_box = layout.box()
        save_box.label(text="Local Files", icon="FILE_FOLDER")
        save_box.prop(prefs, "output_dir")
        save_box.operator("gemini.save_images", icon="FILE_TICK")

        if settings.preview_image:
            preview_box = layout.box()
            preview_box.label(text=f"Preview: {settings.preview_image.name}", icon="IMAGE_DATA")
            settings.preview_image.preview_ensure()
            preview_box.template_icon(icon_value=settings.preview_image.preview.icon_id, scale=12.0)
            preview_box.template_preview(settings.preview_image, show_buttons=False)
            preview_box.label(text=f"Saved in: {ensure_output_dir()}", icon="FILEBROWSER")

            regen_row = preview_box.row(align=True)
            prev_op = regen_row.operator("gemini.browse_history", text="", icon="TRIA_LEFT")
            prev_op.direction = "PREV"
            regen_row.operator("gemini.generate_texture", text="Generate Again", icon="FILE_REFRESH")
            next_op = regen_row.operator("gemini.browse_history", text="", icon="TRIA_RIGHT")
            next_op.direction = "NEXT"

            if settings.normal_image or settings.roughness_image or settings.metallic_image:
                maps_row = preview_box.row(align=True)
                if settings.normal_image:
                    maps_row.label(text="Normal")
                if settings.roughness_image:
                    maps_row.label(text="Roughness")
                if settings.metallic_image:
                    maps_row.label(text="Metallic")

            maps_box = preview_box.box()
            maps_box.label(text="Maps", icon="NODE_MATERIAL")
            maps_box.prop(settings, "normal_strength")
            maps_box.operator("gemini.generate_maps", icon="SHADING_RENDERED")

            apply_row = preview_box.row(align=True)
            apply_row.operator("gemini.apply_texture", icon="MATERIAL")
            apply_row.operator("gemini.apply_texture_auto_uv", icon="UV")

            preview_box.prop(settings, "pad_to_square")
            resize_row = preview_box.row(align=True)
            op_512 = resize_row.operator("gemini.resize_texture", text="512")
            op_512.target_size = "512"
            op_256 = resize_row.operator("gemini.resize_texture", text="256")
            op_256.target_size = "256"
            op_128 = resize_row.operator("gemini.resize_texture", text="128")
            op_128.target_size = "128"

            footer_row = preview_box.row(align=True)
            footer_row.operator("gemini.save_images", icon="FILE_TICK")
            footer_row.operator("gemini.clear_preview", icon="TRASH")

            preview_box.label(
                text="Edit Mode applies to selected faces. Object Mode applies to the whole mesh.",
                icon="INFO",
            )


classes = (
    GeminiAddonPreferences,
    GeminiTextureSettings,
    GEMINI_OT_open_api_key_page,
    GEMINI_OT_generate_texture,
    GEMINI_OT_generate_maps,
    GEMINI_OT_browse_history,
    GEMINI_OT_apply_texture,
    GEMINI_OT_apply_texture_auto_uv,
    GEMINI_OT_resize_texture,
    GEMINI_OT_save_images,
    GEMINI_OT_clear_preview,
    GEMINI_PT_texture_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.gemini_texture_settings = PointerProperty(type=GeminiTextureSettings)


def unregister():
    if hasattr(bpy.types.Scene, "gemini_texture_settings"):
        del bpy.types.Scene.gemini_texture_settings

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
