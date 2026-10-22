"""PDF -> PII-masked page images, gated on recognizing a known customer
invoice layout.

Exact port of ennVault_org_backend/modules/processing/pre_processor/
transform.py: table detection (`detect_table`), word merging
(`merge_close_words`/`_merge_line`), per-customer format detection
(`detect_invoice_format`, scored against the exclusion_config word lists --
see config_loader.py), and the two encode paths (`transform_raw_pdf` for a
real-text PDF, the OCR/inpaint path in `transform` for a scanned PDF/image)
that replace every recognized word with a short code before the page is
ever sent to the vision LLM, saving the code<->word mapping to an Excel
file that `agents/agent_3/services/decoder.py` reads back afterward.

Returns the same 6-tuple shape as the original `transform()`:
(output_images, mapping_path, success, dup_refs, format_ok, err_desc).
"""
from __future__ import annotations

import math
import os
import random
import string

import cv2
import numpy as np
import pandas as pd
import pdfplumber
import pytesseract

from .pdf_utils import image2pdfstreams, pdf_to_images


def detect_table(image) -> int:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)

    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    detect_horizontal = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)

    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
    detect_vertical = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, vertical_kernel, iterations=2)

    table_mask = cv2.add(detect_horizontal, detect_vertical)
    contours, _ = cv2.findContours(table_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return len([cnt for cnt in contours if cv2.contourArea(cnt) > 1000])


def _midpoint(x1, y1, x2, y2):
    return (int((x1 + x2) / 2), int((y1 + y2) / 2))


def merge_close_words(words, x_threshold=1.5, y_threshold=0):
    if not words:
        return []
    words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    merged = []
    current_line = []
    last_top = None
    for w in words:
        top = round(w["top"], 1)
        if last_top is None or abs(top - last_top) > y_threshold:
            if current_line:
                merged.extend(_merge_line(current_line, x_threshold))
            current_line = [w]
            last_top = top
        else:
            current_line.append(w)
    if current_line:
        merged.extend(_merge_line(current_line, x_threshold))
    return merged


def _merge_line(line_words, x_threshold):
    merged_line = []
    current = line_words[0].copy()
    for w in line_words[1:]:
        gap = w["x0"] - current["x1"]
        if gap <= x_threshold:
            current["text"] += w["text"]
            current["x1"] = w["x1"]
        else:
            merged_line.append(current)
            current = w.copy()
    merged_line.append(current)
    return merged_line


def detect_invoice_format(unique_words, config):
    """Scores each known customer format in `config` by how many of its
    distinctive (rarely-shared) label words appear in this PDF's OCR'd
    words. Returns (detected_format_name_or_None, set_of_words_to_mask)."""
    detected_format = None
    best_score = 0
    exclude_words: set[str] = set()

    lower_unique_words = {w.lower() for w in unique_words}

    word_freq: dict[str, int] = {}
    for data in config.values():
        for w in {w.lower() for w in data.get("fields", [])}:
            word_freq[w] = word_freq.get(w, 0) + 1

    for name, data in config.items():
        format_words = {w.lower() for w in data.get("fields", [])}
        score = 0.0
        for word in format_words:
            if word in lower_unique_words:
                score += 1 / word_freq[word]
        if score > best_score:
            best_score = score
            detected_format = name
            exclude_words = format_words

    return detected_format, exclude_words


def transform_raw_pdf(pdf_path: str, output_folder: str, config: dict):
    """Encodes a real (non-scanned) PDF via bbox overlays. Returns
    (output_images, mapping_path, success, doc_obj=None, is_pdf=True, error_msg)."""
    import fitz  # PyMuPDF

    os.makedirs(output_folder, exist_ok=True)
    output_pdf_path = os.path.join(output_folder, "encoded_output.pdf")
    mapping_path = os.path.join(output_folder, "encrypted_mapping_3digit.xlsx")

    doc = fitz.open(pdf_path)
    new_doc = fitz.open()
    output_images = []

    all_words = []
    for page_index in range(len(doc)):
        for w in doc[page_index].get_text("words"):
            all_words.append(w[4].strip())

    unique_words = sorted(set(all_words))
    detected_format, exclude_words = detect_invoice_format(unique_words, config)
    if not detected_format:
        return [], "", False, None, True, "Customer config not found"

    word_to_code: dict[str, str] = {}
    short_chars = string.digits + string.ascii_lowercase

    def generate_code(word_length):
        while True:
            code = random.choice(short_chars) if word_length < 3 else str(random.randint(100, 999))
            if code not in word_to_code.values():
                return code

    for page_index in range(len(doc)):
        page = doc[page_index]
        rect = page.rect
        new_page = new_doc.new_page(width=rect.width, height=rect.height)
        new_page.show_pdf_page(rect, doc, page_index)

        for w in page.get_text("words"):
            x0, y0, x1, y1, word, *_ = w
            clean_word = word.strip()
            if not clean_word or clean_word.lower() in exclude_words:
                continue
            if clean_word not in word_to_code:
                word_to_code[clean_word] = generate_code(len(clean_word))
            code_val = word_to_code[clean_word]

            new_page.draw_rect(fitz.Rect(x0, y0, x1, y1), fill=(1, 1, 1), color=(0.5, 0.5, 0.5), width=0.3)
            new_page.insert_text((x0, y1 - 2), code_val, fontsize=8, fontname="helv", color=(0, 0, 0), overlay=True)

        pix = new_page.get_pixmap(dpi=300)
        img_path = os.path.join(output_folder, f"page_{page_index + 1}.png")
        pix.save(img_path)
        output_images.append(img_path)

    new_doc.save(output_pdf_path)
    new_doc.close()
    doc.close()

    df = pd.DataFrame([{"Original Word": k, "Encrypted Word": v} for k, v in word_to_code.items()])
    df.to_excel(mapping_path, index=False)

    return output_images, mapping_path, True, None, True, None


def transform(pdf_path: str, output_folder: str, config: dict, doc_type: str):
    """Top-level entrypoint. Returns
    (output_images, mapping_path, success, dup_refs, format_ok, err_desc)."""
    os.makedirs(output_folder, exist_ok=True)

    def extract_words_from_pdf(path):
        word_locs = []
        with pdfplumber.open(path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                merged = merge_close_words(page.extract_words())
                for w in merged:
                    word_locs.append(
                        {
                            "page": page_num,
                            "text": w["text"],
                            "x0": w["x0"],
                            "top": w["top"],
                            "x1": w["x1"],
                            "bottom": w["bottom"],
                            "height": w["bottom"] - w["top"],
                        }
                    )
        return word_locs

    if pdf_path.lower().endswith((".png", ".jpg", ".jpeg")):
        pdf_path = image2pdfstreams(pdf_path)

    word_locations = extract_words_from_pdf(pdf_path)

    if word_locations:
        return transform_raw_pdf(pdf_path, output_folder, config)

    # Scanned PDF / no embedded text: OCR each page, then re-check for words.
    images_paths = pdf_to_images(pdf_path, output_folder, dpi=300)
    searchable_pdfs = [image2pdfstreams(img_path) for img_path in images_paths]
    all_word_locations = []
    for pdf_page_path in searchable_pdfs:
        all_word_locations.extend(extract_words_from_pdf(pdf_page_path))
    word_locations = all_word_locations
    if not word_locations:
        return [], "", False, None, False, "No text found after OCR"

    unique_words = sorted({w["text"] for w in word_locations})
    detected_format, exclude_words = detect_invoice_format(unique_words, config)
    if not detected_format:
        return [], "", False, None, False, "Customer config not found"

    word_to_code: dict[str, str] = {}
    code = 100
    for w in unique_words:
        if w.lower() not in exclude_words:
            word_to_code[w] = str(code).zfill(3)
            code += 1

    mapping_path = os.path.join(output_folder, "encrypted_mapping_3digit.xlsx")
    df = pd.DataFrame([{"Original Word": k, "Encrypted Word": v} for k, v in word_to_code.items()])
    df.to_excel(mapping_path, index=False)

    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    output_images = []
    for page_number in range(len(doc)):
        page = doc.load_page(page_number)
        pix = page.get_pixmap(dpi=300)
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)

        if detect_table(img_np) < 1:
            continue

        rgb = cv2.cvtColor(img_np, cv2.COLOR_BGR2RGB)
        ocr_data = pytesseract.image_to_data(rgb, output_type=pytesseract.Output.DICT)

        mask = np.zeros(img_np.shape[:2], dtype="uint8")
        for i, word in enumerate(ocr_data["text"]):
            word = word.strip()
            if word in word_to_code:
                x, y, w_, h = ocr_data["left"][i], ocr_data["top"][i], ocr_data["width"][i], ocr_data["height"][i]
                mid_start = _midpoint(x, y, x, y + h)
                mid_end = _midpoint(x + w_, y, x + w_, y + h)
                thickness = int(math.hypot(w_, h))
                cv2.line(mask, mid_start, mid_end, 255, thickness)

        inpainted_img = cv2.inpaint(img_np, mask, 7, cv2.INPAINT_NS)

        font = cv2.FONT_HERSHEY_SIMPLEX
        for i, word in enumerate(ocr_data["text"]):
            word = word.strip()
            if word in word_to_code:
                x, y, w_, h = ocr_data["left"][i], ocr_data["top"][i], ocr_data["width"][i], ocr_data["height"][i]
                encrypted_word = word_to_code[word]
                text_size = cv2.getTextSize(encrypted_word, font, 1, 0)[0]
                text_x = x + (w_ - text_size[0]) // 2
                text_y = y + (h + text_size[1]) // 2
                cv2.putText(inpainted_img, encrypted_word, (text_x, text_y), font, 1, (0, 0, 0), 0)

        img_path = os.path.join(output_folder, f"page_{page_number + 1}.png")
        cv2.imwrite(img_path, inpainted_img)
        output_images.append(img_path)

    doc.close()
    return output_images, mapping_path, True, None, True, None
