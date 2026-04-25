from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pdf2image import convert_from_path, pdfinfo_from_path
from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError
from PIL import Image

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = None
    TkinterDnD = None


Order = Literal["row", "column"]

APP_TITLE = "Split PDF Handout to Image Slide"
AUTHOR_NAME = "Arthur Tao"
AUTHOR_WEBSITE_URL = "https://taoyutsun.blogspot.com/"
AUTHOR_FACEBOOK_URL = "https://facebook.com/arthurtaoyutsun"
SOURCE_CODE_URL: str | None = "https://github.com/taoyutsun/split-pdf-handout-to-image-slide"

DEFAULT_DPI = 300
DEFAULT_WHITE_THRESHOLD = 245
DEFAULT_MIN_AREA_RATIO = 0.01
DEFAULT_PADDING_RATIO = 0.006

UI_BG = "#15171c"
UI_SURFACE = "#202329"
UI_SURFACE_ALT = "#262a31"
UI_FIELD = "#101216"
UI_BORDER = "#3a404a"
UI_TEXT = "#f4f7fb"
UI_MUTED = "#aeb7c4"
UI_ACCENT = "#4f8cff"
UI_ACCENT_HOVER = "#6aa0ff"
UI_DISABLED = "#69717d"
UI_SUCCESS = "#5ed7a4"


@dataclass(frozen=True)
class Settings:
    dpi: int = DEFAULT_DPI
    order: Order = "row"
    poppler_path: Path | None = None
    layout: tuple[int, int] | None = None
    white_threshold: int = DEFAULT_WHITE_THRESHOLD
    min_area_ratio: float = DEFAULT_MIN_AREA_RATIO
    padding_ratio: float = DEFAULT_PADDING_RATIO
    keep_images: bool = False
    images_dir: Path | None = None
    overwrite: bool = False


@dataclass(frozen=True)
class ConversionResult:
    output_pdf: Path
    page_count: int
    slide_count: int
    images_dir: Path | None


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_poppler_path(explicit_path: str | os.PathLike[str] | None = None) -> Path | None:
    candidates: list[Path] = []

    if explicit_path:
        candidates.append(Path(explicit_path))

    env_path = os.environ.get("PDF2IMAGE_POPPLER_PATH")
    if env_path:
        candidates.append(Path(env_path))

    app_dir = application_dir()
    candidates.extend(
        [
            app_dir / "poppler" / "Library" / "bin",
            app_dir / "poppler" / "bin",
            app_dir / "Library" / "bin",
            Path(r"C:\poppler-24.08.0\Library\bin"),
            Path(r"C:\Program Files\poppler\Library\bin"),
            Path(r"C:\Program Files\poppler\bin"),
        ]
    )

    for candidate in candidates:
        if (candidate / "pdftoppm.exe").exists() or (candidate / "pdftoppm").exists():
            return candidate

    if shutil.which("pdftoppm") and shutil.which("pdfinfo"):
        return None

    return None


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate

    raise FileExistsError(f"找不到可用的輸出檔名：{path}")


def build_output_path(pdf_path: Path, output_path: str | os.PathLike[str] | None, overwrite: bool) -> Path:
    output = Path(output_path) if output_path else pdf_path.with_name(f"{pdf_path.stem}_slide.pdf")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    return output if overwrite else unique_path(output)


def parse_layout(value: str | None) -> tuple[int, int] | None:
    if not value or value.lower() == "auto":
        return None

    match = re.fullmatch(r"\s*(\d+)\s*[xX/]\s*(\d+)\s*", value)
    if not match:
        raise ValueError("版面格式請使用 auto、2x2、3x2、2/2 或 3/2 這類格式。")

    columns, rows = int(match.group(1)), int(match.group(2))
    if columns < 1 or rows < 1:
        raise ValueError("版面欄數與列數都必須大於 0。")
    return columns, rows


def normalize_order(value: str | None) -> Order:
    normalized = (value or "1").strip().lower()
    row_values = {"1", "row", "rows", "row-major", "left-to-right", "ltr", "左到右"}
    column_values = {"2", "column", "columns", "col", "column-major", "top-to-bottom", "ttb", "上到下"}

    if normalized in row_values:
        return "row"
    if normalized in column_values:
        return "column"
    raise ValueError("排列順序請輸入 1/row 或 2/column。")


def box_area(box: tuple[int, int, int, int]) -> int:
    return box[2] * box[3]


def contains_box(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int], tolerance: int = 4) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return (
        ix >= ox - tolerance
        and iy >= oy - tolerance
        and ix + iw <= ox + ow + tolerance
        and iy + ih <= oy + oh + tolerance
    )


def intersection_over_union(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)

    if right <= left or bottom <= top:
        return 0.0

    intersection = (right - left) * (bottom - top)
    union = box_area(a) + box_area(b) - intersection
    return intersection / union if union else 0.0


def expand_box(
    box: tuple[int, int, int, int],
    image_width: int,
    image_height: int,
    padding_ratio: float,
) -> tuple[int, int, int, int]:
    x, y, width, height = box
    pad_x = max(2, int(image_width * padding_ratio))
    pad_y = max(2, int(image_height * padding_ratio))

    left = max(0, x - pad_x)
    top = max(0, y - pad_y)
    right = min(image_width, x + width + pad_x)
    bottom = min(image_height, y + height + pad_y)
    return left, top, right - left, bottom - top


def remove_nested_and_duplicate_boxes(boxes: Iterable[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    kept: list[tuple[int, int, int, int]] = []

    for box in sorted(boxes, key=box_area, reverse=True):
        if any(contains_box(existing, box) or intersection_over_union(existing, box) > 0.86 for existing in kept):
            continue
        kept.append(box)

    return kept


def group_boxes(
    boxes: list[tuple[int, int, int, int]],
    axis: Literal["x", "y"],
    tolerance: float,
) -> list[list[tuple[int, int, int, int]]]:
    center_index = 0 if axis == "x" else 1
    size_index = 2 if axis == "x" else 3

    def center(box: tuple[int, int, int, int]) -> float:
        return box[center_index] + box[size_index] / 2

    groups: list[list[tuple[int, int, int, int]]] = []

    for box in sorted(boxes, key=center):
        box_center = center(box)
        if not groups:
            groups.append([box])
            continue

        group_center = sum(center(item) for item in groups[-1]) / len(groups[-1])
        if abs(box_center - group_center) <= tolerance:
            groups[-1].append(box)
        else:
            groups.append([box])

    return groups


def sort_boxes(
    boxes: list[tuple[int, int, int, int]],
    order: Order,
    image_width: int,
    image_height: int,
) -> list[tuple[int, int, int, int]]:
    if order == "column":
        tolerance = max(image_width * 0.035, 10)
        groups = group_boxes(boxes, "x", tolerance)
        groups.sort(key=lambda group: sum(box[0] + box[2] / 2 for box in group) / len(group))
        return [box for group in groups for box in sorted(group, key=lambda item: item[1])]

    tolerance = max(image_height * 0.035, 10)
    groups = group_boxes(boxes, "y", tolerance)
    groups.sort(key=lambda group: sum(box[1] + box[3] / 2 for box in group) / len(group))
    return [box for group in groups for box in sorted(group, key=lambda item: item[0])]


def fixed_layout_boxes(image: Image.Image, layout: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    columns, rows = layout
    width, height = image.size
    boxes: list[tuple[int, int, int, int]] = []

    for row in range(rows):
        for column in range(columns):
            left = round(column * width / columns)
            top = round(row * height / rows)
            right = round((column + 1) * width / columns)
            bottom = round((row + 1) * height / rows)
            boxes.append((left, top, right - left, bottom - top))

    return boxes


def detect_layout(
    image: Image.Image,
    settings: Settings,
) -> list[tuple[int, int, int, int]]:
    image_width, image_height = image.size
    if settings.layout:
        boxes = fixed_layout_boxes(image, settings.layout)
        return sort_boxes(boxes, settings.order, image_width, image_height)

    rgb = np.array(image.convert("RGB"))
    image_height, image_width = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    _, mask = cv2.threshold(gray, settings.white_threshold, 255, cv2.THRESH_BINARY_INV)

    kernel_width = max(3, image_width // 150)
    kernel_height = max(3, image_height // 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, kernel_height))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.dilate(mask, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = image_width * image_height
    min_area = image_area * settings.min_area_ratio
    boxes: list[tuple[int, int, int, int]] = []

    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        contour_area = cv2.contourArea(contour)
        bounding_area = width * height

        if contour_area < min_area and bounding_area < min_area:
            continue
        if width < image_width * 0.05 or height < image_height * 0.05:
            continue
        if bounding_area > image_area * 0.92 and len(contours) > 1:
            continue

        boxes.append(expand_box((x, y, width, height), image_width, image_height, settings.padding_ratio))

    boxes = remove_nested_and_duplicate_boxes(boxes)
    if not boxes:
        boxes = [(0, 0, image_width, image_height)]

    return sort_boxes(boxes, settings.order, image_width, image_height)


def prepare_image_dir(pdf_path: Path, settings: Settings) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if settings.keep_images:
        image_dir = settings.images_dir or pdf_path.with_name(f"{pdf_path.stem}_split_images")
        image_dir = image_dir.expanduser().resolve()
        if not settings.overwrite:
            image_dir = unique_path(image_dir)
        image_dir.mkdir(parents=True, exist_ok=True)
        return image_dir, None

    temp_dir = tempfile.TemporaryDirectory(prefix="split_pdf_slides_")
    return Path(temp_dir.name), temp_dir


def save_slide_images(pdf_path: Path, image_dir: Path, settings: Settings, page_count: int) -> list[Path]:
    poppler_path = str(settings.poppler_path) if settings.poppler_path else None
    slide_paths: list[Path] = []
    slide_index = 1

    for page_number in range(1, page_count + 1):
        rendered_pages = convert_from_path(
            str(pdf_path),
            dpi=settings.dpi,
            first_page=page_number,
            last_page=page_number,
            poppler_path=poppler_path,
            thread_count=1,
        )

        if not rendered_pages:
            continue

        with rendered_pages[0] as image:
            boxes = detect_layout(image, settings)
            for x, y, width, height in boxes:
                slide = image.crop((x, y, x + width, y + height)).convert("RGB")
                slide_path = image_dir / f"slide_{slide_index:04d}.png"
                slide.save(slide_path, "PNG")
                slide.close()
                slide_paths.append(slide_path)
                slide_index += 1

    return slide_paths


def merge_images_to_pdf(slide_paths: list[Path], output_pdf: Path, dpi: int) -> None:
    if not slide_paths:
        raise RuntimeError("沒有偵測到可輸出的投影片區塊。")

    opened_images = [Image.open(path) for path in slide_paths]
    try:
        first_image, rest_images = opened_images[0], opened_images[1:]
        first_image.save(
            output_pdf,
            "PDF",
            save_all=True,
            append_images=rest_images,
            resolution=dpi,
        )
    finally:
        for image in opened_images:
            image.close()


def convert_pdf_to_slide_pdf(
    pdf_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str] | None,
    settings: Settings,
) -> ConversionResult:
    pdf = Path(pdf_path).expanduser().resolve()
    if not pdf.exists():
        raise FileNotFoundError(f"找不到 PDF 檔案：{pdf}")
    if pdf.suffix.lower() != ".pdf":
        raise ValueError("請選擇 PDF 檔案。")

    output_pdf = build_output_path(pdf, output_path, settings.overwrite)
    poppler_path = str(settings.poppler_path) if settings.poppler_path else None
    info = pdfinfo_from_path(str(pdf), poppler_path=poppler_path)
    page_count = int(info.get("Pages", 0))
    if page_count < 1:
        raise RuntimeError("PDF 沒有可轉換的頁面。")

    image_dir, temp_dir = prepare_image_dir(pdf, settings)
    try:
        slide_paths = save_slide_images(pdf, image_dir, settings, page_count)
        merge_images_to_pdf(slide_paths, output_pdf, settings.dpi)
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    return ConversionResult(
        output_pdf=output_pdf,
        page_count=page_count,
        slide_count=len(slide_paths),
        images_dir=image_dir if settings.keep_images else None,
    )


def build_poppler_error_message() -> str:
    return (
        "找不到 Poppler，無法讀取 PDF。\n\n"
        "請擇一處理：\n"
        "1. 將 Poppler 的 bin 資料夾加入 PATH。\n"
        "2. 設定環境變數 PDF2IMAGE_POPPLER_PATH。\n"
        "3. 使用命令列參數 --poppler-path 指定 Poppler bin 資料夾。\n\n"
        r"Windows 常見路徑範例：C:\poppler-24.08.0\Library\bin"
    )


class SlideConverterGui:
    def __init__(self, args: argparse.Namespace):
        root_class = TkinterDnD.Tk if TkinterDnD is not None else tk.Tk
        self.root = root_class()
        self.args = args
        self.worker_thread: threading.Thread | None = None
        self.last_output_dir: Path | None = None
        self.busy_widgets: list[tk.Widget] = []

        self.pdf_path_var = tk.StringVar()
        self.output_path_var = tk.StringVar(value=args.output or "")
        self.order_var = tk.StringVar(value="2" if normalize_order(args.order) == "column" else "1")
        self.layout_var = tk.StringVar(value=args.layout or "auto")
        self.dpi_var = tk.StringVar(value=str(args.dpi))
        self.poppler_path_var = tk.StringVar(value=args.poppler_path or "")
        self.keep_images_var = tk.BooleanVar(value=bool(args.keep_images))
        self.advanced_visible_var = tk.BooleanVar(value=bool(args.poppler_path))
        self.status_var = tk.StringVar(value="請選擇 PDF 檔案")

        self.configure_window()
        self.configure_style()
        self.build_ui()

    def configure_window(self) -> None:
        self.root.title(APP_TITLE)
        self.root.geometry("860x820")
        self.root.minsize(780, 760)
        self.root.configure(bg=UI_BG)

    def configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft JhengHei UI", 10))
        style.configure("TProgressbar", background=UI_ACCENT, troughcolor=UI_SURFACE_ALT, bordercolor=UI_SURFACE_ALT)
        style.configure(
            "Dark.TCombobox",
            fieldbackground=UI_FIELD,
            background=UI_SURFACE_ALT,
            foreground=UI_TEXT,
            arrowcolor=UI_TEXT,
            bordercolor=UI_BORDER,
            lightcolor=UI_BORDER,
            darkcolor=UI_BORDER,
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", UI_FIELD), ("disabled", UI_SURFACE)],
            foreground=[("readonly", UI_TEXT), ("disabled", UI_DISABLED)],
        )
        style.configure(
            "Dark.TSpinbox",
            fieldbackground=UI_FIELD,
            background=UI_SURFACE_ALT,
            foreground=UI_TEXT,
            arrowsize=14,
            bordercolor=UI_BORDER,
            lightcolor=UI_BORDER,
            darkcolor=UI_BORDER,
        )

    def build_ui(self) -> None:
        container = tk.Frame(self.root, bg=UI_BG, padx=24, pady=20)
        container.pack(fill="both", expand=True)

        self.build_footer(container)

        content = tk.Frame(container, bg=UI_BG)
        content.pack(side="top", fill="both", expand=True)

        tk.Label(
            content,
            text=APP_TITLE,
            bg=UI_BG,
            fg=UI_TEXT,
            font=("Microsoft JhengHei UI", 20, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            content,
            text="將多格 PDF 講義轉成單頁投影片 PDF",
            bg=UI_BG,
            fg=UI_MUTED,
            font=("Microsoft JhengHei UI", 10),
            anchor="w",
        ).pack(anchor="w", pady=(2, 16))

        self.build_file_panel(content)
        self.build_options_panel(content)
        self.build_action_panel(content)

    def create_panel(self, parent: tk.Widget, title: str) -> tk.Frame:
        panel = tk.Frame(parent, bg=UI_SURFACE, highlightbackground=UI_BORDER, highlightthickness=1)
        panel.pack(fill="x", pady=(0, 12))
        tk.Label(
            panel,
            text=title,
            bg=UI_SURFACE,
            fg=UI_TEXT,
            font=("Microsoft JhengHei UI", 10, "bold"),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 8))
        body = tk.Frame(panel, bg=UI_SURFACE, padx=14, pady=0)
        body.pack(fill="x", pady=(0, 14))
        return body

    def make_entry(self, parent: tk.Widget, textvariable: tk.StringVar) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=textvariable,
            bg=UI_FIELD,
            fg=UI_TEXT,
            insertbackground=UI_TEXT,
            disabledbackground=UI_SURFACE_ALT,
            disabledforeground=UI_DISABLED,
            relief="flat",
            highlightbackground=UI_BORDER,
            highlightcolor=UI_ACCENT,
            highlightthickness=1,
            font=("Microsoft JhengHei UI", 10),
        )

    def make_button(self, parent: tk.Widget, text: str, command, accent: bool = False) -> tk.Button:
        bg = UI_ACCENT if accent else UI_SURFACE_ALT
        active_bg = UI_ACCENT_HOVER if accent else "#303641"
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg="#ffffff" if accent else UI_TEXT,
            activebackground=active_bg,
            activeforeground="#ffffff",
            disabledforeground=UI_DISABLED,
            relief="flat",
            borderwidth=0,
            padx=16,
            pady=8,
            font=("Microsoft JhengHei UI", 10, "bold" if accent else "normal"),
            cursor="hand2",
        )
        return button

    def make_field_label(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=UI_SURFACE,
            fg=UI_MUTED,
            font=("Microsoft JhengHei UI", 10),
            anchor="w",
        )

    def make_radio(self, parent: tk.Widget, text: str, value: str) -> tk.Radiobutton:
        return tk.Radiobutton(
            parent,
            text=text,
            variable=self.order_var,
            value=value,
            bg=UI_SURFACE,
            fg=UI_TEXT,
            activebackground=UI_SURFACE,
            activeforeground=UI_TEXT,
            selectcolor=UI_FIELD,
            font=("Microsoft JhengHei UI", 10),
            cursor="hand2",
        )

    def build_file_panel(self, parent: tk.Widget) -> None:
        file_panel = self.create_panel(parent, "PDF 檔案")

        input_row = tk.Frame(file_panel, bg=UI_SURFACE)
        input_row.pack(fill="x")

        input_entry = self.make_entry(input_row, self.pdf_path_var)
        input_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        browse_button = self.make_button(input_row, "選擇 PDF", self.choose_pdf)
        browse_button.pack(side="left")
        self.busy_widgets.extend([input_entry, browse_button])

        self.drop_area = tk.Frame(
            file_panel,
            bg=UI_SURFACE_ALT,
            highlightbackground=UI_BORDER,
            highlightcolor=UI_ACCENT,
            highlightthickness=1,
            height=82,
            cursor="hand2",
        )
        self.drop_area.pack(fill="x", pady=(12, 0))
        self.drop_area.pack_propagate(False)
        self.drop_area.bind("<Button-1>", lambda _event: self.choose_pdf())

        drop_text = "拖曳 PDF 到這裡" if DND_FILES is not None else "貼上 PDF 路徑，或按「選擇 PDF」"
        self.drop_label = tk.Label(
            self.drop_area,
            text=drop_text,
            bg=UI_SURFACE_ALT,
            fg=UI_TEXT,
            font=("Microsoft JhengHei UI", 12, "bold"),
        )
        self.drop_label.pack(expand=True)
        self.drop_label.bind("<Button-1>", lambda _event: self.choose_pdf())

        if DND_FILES is not None and hasattr(self.drop_area, "drop_target_register"):
            self.drop_area.drop_target_register(DND_FILES)
            self.drop_area.dnd_bind("<<Drop>>", self.on_drop)
            if hasattr(self.drop_label, "drop_target_register"):
                self.drop_label.drop_target_register(DND_FILES)
                self.drop_label.dnd_bind("<<Drop>>", self.on_drop)

        output_row = tk.Frame(file_panel, bg=UI_SURFACE)
        output_row.pack(fill="x", pady=(12, 0))

        self.make_field_label(output_row, "輸出 PDF").pack(side="left", padx=(0, 8))
        output_entry = self.make_entry(output_row, self.output_path_var)
        output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        output_button = self.make_button(output_row, "儲存為", self.choose_output)
        output_button.pack(side="left", padx=(0, 8))

        auto_button = self.make_button(output_row, "自動命名", lambda: self.output_path_var.set(""))
        auto_button.pack(side="left")
        self.busy_widgets.extend([output_entry, output_button, auto_button])

    def build_options_panel(self, parent: tk.Widget) -> None:
        options_panel = self.create_panel(parent, "轉換設定")

        order_row = tk.Frame(options_panel, bg=UI_SURFACE)
        order_row.pack(fill="x")
        self.make_field_label(order_row, "排列順序").pack(side="left", padx=(0, 12))
        row_radio = self.make_radio(order_row, "左到右，再上到下", "1")
        col_radio = self.make_radio(order_row, "上到下，再左到右", "2")
        row_radio.pack(side="left", padx=(0, 18))
        col_radio.pack(side="left")

        grid_row = tk.Frame(options_panel, bg=UI_SURFACE)
        grid_row.pack(fill="x", pady=(12, 0))

        self.make_field_label(grid_row, "版面模式").pack(side="left", padx=(0, 8))
        layout_combo = ttk.Combobox(
            grid_row,
            textvariable=self.layout_var,
            values=["auto", "2x1", "1x2", "2x2", "3x2", "2x3", "3x3", "4x4"],
            width=12,
            state="readonly",
            style="Dark.TCombobox",
        )
        layout_combo.pack(side="left", padx=(0, 24))

        self.make_field_label(grid_row, "DPI").pack(side="left", padx=(0, 8))
        dpi_spin = ttk.Spinbox(grid_row, from_=72, to=600, increment=25, textvariable=self.dpi_var, width=8, style="Dark.TSpinbox")
        dpi_spin.pack(side="left", padx=(0, 24))

        keep_images = tk.Checkbutton(
            grid_row,
            text="保留中間圖片",
            variable=self.keep_images_var,
            bg=UI_SURFACE,
            fg=UI_TEXT,
            activebackground=UI_SURFACE,
            activeforeground=UI_TEXT,
            selectcolor=UI_FIELD,
            font=("Microsoft JhengHei UI", 10),
            cursor="hand2",
        )
        keep_images.pack(side="left")

        advanced_toggle = tk.Checkbutton(
            options_panel,
            text="顯示進階設定",
            variable=self.advanced_visible_var,
            command=self.toggle_advanced_settings,
            bg=UI_SURFACE,
            fg=UI_MUTED,
            activebackground=UI_SURFACE,
            activeforeground=UI_TEXT,
            selectcolor=UI_FIELD,
            font=("Microsoft JhengHei UI", 9),
            cursor="hand2",
        )
        advanced_toggle.pack(anchor="w", pady=(12, 0))

        self.advanced_frame = tk.Frame(options_panel, bg=UI_SURFACE)
        poppler_note = tk.Label(
            self.advanced_frame,
            text="Poppler 是讀取與轉換 PDF 的外部工具。通常留空即可；只有在程式提示找不到 Poppler 時，才需要指定 Poppler 的 bin 資料夾。",
            bg=UI_SURFACE,
            fg=UI_MUTED,
            font=("Microsoft JhengHei UI", 9),
            anchor="w",
            justify="left",
            wraplength=760,
        )
        poppler_note.pack(fill="x", pady=(0, 8))

        poppler_row = tk.Frame(self.advanced_frame, bg=UI_SURFACE)
        poppler_row.pack(fill="x")
        self.make_field_label(poppler_row, "Poppler 路徑").pack(side="left", padx=(0, 8))
        poppler_entry = self.make_entry(poppler_row, self.poppler_path_var)
        poppler_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        poppler_button = self.make_button(poppler_row, "選擇資料夾", self.choose_poppler)
        poppler_button.pack(side="left")
        self.toggle_advanced_settings()

        self.busy_widgets.extend([row_radio, col_radio, layout_combo, dpi_spin, keep_images, advanced_toggle, poppler_entry, poppler_button])

    def build_action_panel(self, parent: tk.Widget) -> None:
        action_row = tk.Frame(parent, bg=UI_BG)
        action_row.pack(fill="x", pady=(0, 12))

        self.start_button = self.make_button(action_row, "開始轉換", self.start_conversion, accent=True)
        self.start_button.pack(side="left")

        self.open_folder_button = self.make_button(action_row, "開啟輸出資料夾", self.open_output_folder)
        self.open_folder_button.configure(state="disabled")
        self.open_folder_button.pack(side="left", padx=(10, 0))

        self.progress = ttk.Progressbar(parent, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 8))

        status_label = tk.Label(
            parent,
            textvariable=self.status_var,
            bg=UI_BG,
            fg=UI_MUTED,
            font=("Microsoft JhengHei UI", 9),
            anchor="w",
        )
        status_label.pack(anchor="w", pady=(0, 12))

    def build_footer(self, parent: tk.Widget) -> None:
        footer = tk.Frame(parent, bg=UI_SURFACE, highlightbackground=UI_BORDER, highlightthickness=1)
        footer.pack(fill="x", side="bottom", pady=(10, 0))

        title = tk.Label(
            footer,
            text="關於作者",
            bg=UI_SURFACE,
            fg=UI_TEXT,
            font=("Microsoft JhengHei UI", 10, "bold"),
            anchor="w",
        )
        title.pack(fill="x", padx=14, pady=(10, 4))

        intro = tk.Label(
            footer,
            text=f"{APP_TITLE} 由 {AUTHOR_NAME} 設計與維護，採 MIT 授權。歡迎使用與分享，並保留原作者與來源資訊。",
            bg=UI_SURFACE,
            fg=UI_MUTED,
            font=("Microsoft JhengHei UI", 9),
            anchor="w",
            justify="left",
            wraplength=760,
        )
        intro.pack(fill="x", padx=14)

        author = tk.Label(
            footer,
            text=f"作者：{AUTHOR_NAME}",
            bg=UI_SURFACE,
            fg=UI_TEXT,
            font=("Microsoft JhengHei UI", 9, "bold"),
            anchor="w",
        )
        author.pack(fill="x", padx=14, pady=(8, 4))

        links = tk.Frame(footer, bg=UI_SURFACE)
        links.pack(fill="x", padx=14, pady=(0, 10))
        self.add_link(links, "亞瑟 ASK 部落格", AUTHOR_WEBSITE_URL)
        self.add_separator(links)
        self.add_link(links, "Facebook", AUTHOR_FACEBOOK_URL)
        self.add_separator(links)
        if SOURCE_CODE_URL:
            self.add_link(links, "檢視原始碼", SOURCE_CODE_URL)
        else:
            tk.Label(
                links,
                text="檢視原始碼（發布後補上）",
                bg=UI_SURFACE,
                fg=UI_DISABLED,
                font=("Microsoft JhengHei UI", 9),
            ).pack(side="left")

    def add_link(self, parent: tk.Widget, text: str, url: str) -> None:
        link = tk.Label(
            parent,
            text=text,
            bg=UI_SURFACE,
            fg="#8fdcff",
            font=("Microsoft JhengHei UI", 9, "underline"),
            cursor="hand2",
        )
        link.pack(side="left")
        link.bind("<Button-1>", lambda _event: webbrowser.open(url))

    def add_separator(self, parent: tk.Widget) -> None:
        tk.Label(parent, text="  |  ", bg=UI_SURFACE, fg=UI_DISABLED, font=("Microsoft JhengHei UI", 9)).pack(side="left")

    def toggle_advanced_settings(self) -> None:
        if self.advanced_visible_var.get():
            self.advanced_frame.pack(fill="x", pady=(8, 0))
        else:
            self.advanced_frame.pack_forget()

    def choose_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="選擇要轉換的 PDF",
            filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")],
            parent=self.root,
        )
        if path:
            self.pdf_path_var.set(path)
            self.status_var.set("已選擇 PDF，請確認設定後開始轉換")

    def choose_output(self) -> None:
        initial_dir = Path(self.pdf_path_var.get()).parent if self.pdf_path_var.get() else Path.cwd()
        path = filedialog.asksaveasfilename(
            title="選擇輸出 PDF 位置",
            defaultextension=".pdf",
            filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")],
            initialdir=str(initial_dir) if initial_dir.exists() else str(Path.cwd()),
            parent=self.root,
        )
        if path:
            self.output_path_var.set(path)

    def choose_poppler(self) -> None:
        path = filedialog.askdirectory(title="選擇 Poppler bin 資料夾", parent=self.root)
        if path:
            self.poppler_path_var.set(path)

    def on_drop(self, event: tk.Event) -> None:
        dropped_paths = [Path(item) for item in self.root.tk.splitlist(event.data)]
        pdf_paths = [path for path in dropped_paths if path.suffix.lower() == ".pdf"]
        if not pdf_paths:
            messagebox.showwarning("檔案格式不支援", "請拖曳 PDF 檔案。", parent=self.root)
            return
        self.pdf_path_var.set(str(pdf_paths[0]))
        self.status_var.set("已加入 PDF，請確認設定後開始轉換")

    def start_conversion(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        pdf_path = Path(self.pdf_path_var.get().strip().strip('"')).expanduser()
        if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
            messagebox.showerror("檔案錯誤", "請選擇有效的 PDF 檔案。", parent=self.root)
            return

        try:
            dpi = int(self.dpi_var.get())
            if dpi < 72:
                raise ValueError
        except ValueError:
            messagebox.showerror("設定錯誤", "DPI 請輸入 72 以上的整數。", parent=self.root)
            return

        gui_args = argparse.Namespace(**vars(self.args))
        gui_args.order = self.order_var.get()
        gui_args.layout = self.layout_var.get().strip() or "auto"
        gui_args.dpi = dpi
        gui_args.poppler_path = self.poppler_path_var.get().strip() or None
        gui_args.keep_images = bool(self.keep_images_var.get())
        gui_args.images_dir = None

        output_path = self.output_path_var.get().strip() or None
        self.set_busy(True)
        self.status_var.set("轉換中，請稍候...")
        self.progress.start(12)

        self.worker_thread = threading.Thread(
            target=self.run_conversion_worker,
            args=(str(pdf_path), output_path, gui_args),
            daemon=True,
        )
        self.worker_thread.start()

    def run_conversion_worker(self, pdf_path: str, output_path: str | None, args: argparse.Namespace) -> None:
        try:
            settings = build_settings(args)
            result = convert_pdf_to_slide_pdf(pdf_path, output_path, settings)
        except PDFInfoNotInstalledError:
            self.root.after(0, self.show_error, "Poppler 設定錯誤", build_poppler_error_message())
        except (PDFPageCountError, RuntimeError, ValueError, OSError) as exc:
            self.root.after(0, self.show_error, "轉換失敗", str(exc))
        except Exception as exc:
            self.root.after(0, self.show_error, "未預期錯誤", str(exc))
        else:
            self.root.after(0, self.show_success, result)

    def set_busy(self, is_busy: bool) -> None:
        state = "disabled" if is_busy else "normal"
        for widget in self.busy_widgets:
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        self.start_button.configure(state=state)

    def show_success(self, result: ConversionResult) -> None:
        self.progress.stop()
        self.set_busy(False)
        self.last_output_dir = result.output_pdf.parent
        self.open_folder_button.configure(state="normal")
        self.status_var.set(f"完成：{result.output_pdf}")
        image_message = f"\n拆分圖片資料夾：{result.images_dir}" if result.images_dir else ""
        messagebox.showinfo(
            "PDF 生成完成",
            f"已成功生成 PDF：\n{result.output_pdf}\n\n"
            f"原始頁數：{result.page_count}\n"
            f"輸出投影片頁數：{result.slide_count}"
            f"{image_message}",
            parent=self.root,
        )

    def show_error(self, title: str, message: str) -> None:
        self.progress.stop()
        self.set_busy(False)
        self.status_var.set(message.splitlines()[0] if message else title)
        messagebox.showerror(title, message, parent=self.root)

    def open_output_folder(self) -> None:
        if not self.last_output_dir or not self.last_output_dir.exists():
            return
        if sys.platform == "win32":
            os.startfile(self.last_output_dir)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(self.last_output_dir)])
        else:
            subprocess.Popen(["xdg-open", str(self.last_output_dir)])

    def run(self) -> int:
        self.root.mainloop()
        return 0


def run_gui(args: argparse.Namespace) -> int:
    return SlideConverterGui(args).run()


def build_settings(args: argparse.Namespace, order: Order | None = None) -> Settings:
    layout = parse_layout(args.layout)
    poppler_path = find_poppler_path(args.poppler_path)
    return Settings(
        dpi=args.dpi,
        order=order or normalize_order(args.order),
        poppler_path=poppler_path,
        layout=layout,
        white_threshold=args.white_threshold,
        min_area_ratio=args.min_area_ratio,
        padding_ratio=args.padding_ratio,
        keep_images=args.keep_images,
        images_dir=Path(args.images_dir) if args.images_dir else None,
        overwrite=args.overwrite,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="將多格講義 PDF 拆成單頁投影片 PDF，可雙擊用 GUI，也可用命令列批次處理。",
    )
    parser.add_argument("pdf", nargs="?", help="要轉換的 PDF 路徑；未提供時會開啟檔案選擇視窗。")
    parser.add_argument("-o", "--output", help="輸出 PDF 路徑；預設為 原檔名_slide.pdf。")
    parser.add_argument(
        "--order",
        default="1",
        help="投影片順序：1/row = 左到右再上到下；2/column = 上到下再左到右。",
    )
    parser.add_argument("--layout", default="auto", help="版面偵測模式。預設 auto；也可指定 2x2、3x2、2/3 等固定版面。")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"PDF 轉圖片解析度，預設 {DEFAULT_DPI}。")
    parser.add_argument("--poppler-path", help="Poppler bin 資料夾路徑；未提供時會自動尋找或使用 PATH。")
    parser.add_argument("--keep-images", action="store_true", help="保留拆出的中間 PNG 圖片。")
    parser.add_argument("--images-dir", help="搭配 --keep-images 使用，指定中間圖片輸出資料夾。")
    parser.add_argument("--overwrite", action="store_true", help="允許覆蓋指定輸出 PDF。預設會自動加編號避免覆蓋。")
    parser.add_argument(
        "--white-threshold",
        type=int,
        default=DEFAULT_WHITE_THRESHOLD,
        help="白底判斷門檻，數值越高越容易把淺色內容視為要裁切的內容。",
    )
    parser.add_argument(
        "--min-area-ratio",
        type=float,
        default=DEFAULT_MIN_AREA_RATIO,
        help="偵測區塊最小面積比例，預設 0.01。",
    )
    parser.add_argument(
        "--padding-ratio",
        type=float,
        default=DEFAULT_PADDING_RATIO,
        help="裁切時保留的邊界比例，預設 0.006。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.pdf is None:
        return run_gui(args)

    try:
        settings = build_settings(args)
        result = convert_pdf_to_slide_pdf(args.pdf, args.output, settings)
    except PDFInfoNotInstalledError:
        print(build_poppler_error_message(), file=sys.stderr)
        return 1
    except (PDFPageCountError, RuntimeError, ValueError, OSError) as exc:
        print(f"轉換失敗：{exc}", file=sys.stderr)
        return 1

    print(f"已成功生成 PDF：{result.output_pdf}")
    print(f"原始頁數：{result.page_count}")
    print(f"輸出投影片頁數：{result.slide_count}")
    if result.images_dir:
        print(f"拆分圖片資料夾：{result.images_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
