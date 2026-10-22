"""PDF<->image helpers used by transform_service.

Exact port of ennVault_org_backend/modules/processing/utils/image2pdf.py
(`image2pdfstreams`) and .../utils/pdf2image.py (`pdf_to_images`).
"""
from __future__ import annotations

import io
import os
import shutil

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from shared.config import settings

if settings.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD
else:
    found = shutil.which("tesseract")
    if found:
        pytesseract.pytesseract.tesseract_cmd = found


def pdf_to_images(pdf_path: str, output_folder: str, image_start_index: int = 1, dpi: int = 300) -> list[str]:
    """Renders each PDF page to a high-resolution PNG."""
    os.makedirs(output_folder, exist_ok=True)
    doc = fitz.open(pdf_path)
    image_paths = []

    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    for i in range(len(doc)):
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=matrix)
        image_path = os.path.join(output_folder, f"page_{image_start_index + i}.png")
        pix.save(image_path)
        image_paths.append(image_path)

    doc.close()
    return image_paths


def image2pdfstreams(image_path: str) -> str:
    """Wraps a scanned page image in a searchable PDF (OCR'd text overlaid,
    nearly-invisible, so pdfplumber's word extraction works on it)."""
    img = Image.open(image_path).convert("RGB")
    width, height = img.size

    ocr_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    doc = fitz.open()
    page = doc.new_page(width=width, height=height)

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_bytes = img_byte_arr.getvalue()
    page.insert_image(fitz.Rect(0, 0, width, height), stream=img_bytes)

    for i, word in enumerate(ocr_data["text"]):
        if word.strip():
            x = ocr_data["left"][i]
            y = ocr_data["top"][i]
            h = ocr_data["height"][i]
            pdf_y = height - y
            page.insert_text(
                fitz.Point(x, pdf_y),
                word,
                fontsize=h,
                fontname="helv",
                fill=(0, 0, 0),
                fill_opacity=0.01,
                overlay=True,
            )

    pdf_path = image_path.rsplit(".", 1)[0] + "_searchable.pdf"
    doc.save(pdf_path)
    doc.close()
    return pdf_path
