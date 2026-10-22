# ---------------- unified_transform.py ----------------
import os
import math
import cv2
import fitz
import random
import string
import numpy as np
import pytesseract
import pdfplumber
import pandas as pd
from reportlab.pdfgen import canvas
from openpyxl import Workbook
from modules.processing.utils.image2pdf import image2pdfstreams
from modules.processing.utils.pdf2image import pdf_to_images

# ---------------- TABLE DETECTION ----------------
def detect_table(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)

    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    detect_horizontal = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)

    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
    detect_vertical = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, vertical_kernel, iterations=2)

    table_mask = cv2.add(detect_horizontal, detect_vertical)
    contours, _ = cv2.findContours(table_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    table_like_contours = [cnt for cnt in contours if cv2.contourArea(cnt) > 1000]
    return len(table_like_contours)

def midpoint(x1, y1, x2, y2):
    return (int((x1 + x2) / 2), int((y1 + y2) / 2))

# ---------------- WORD MERGING ----------------
def merge_close_words(words, x_threshold=1.5, y_threshold=0):
    if not words:
        return []
    words.sort(key=lambda w: (round(w['top'], 1), w['x0']))
    merged = []
    current_line = []
    last_top = None
    for w in words:
        top = round(w['top'], 1)
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
        gap = w['x0'] - current['x1']
        if gap <= x_threshold:
            current['text'] += w['text']
            current['x1'] = w['x1']
        else:
            merged_line.append(current)
            current = w.copy()
    merged_line.append(current)
    return merged_line

# ---------------- FORMAT DETECTION ----------------

# def detect_invoice_format(unique_words, config):
#     detected_format = None
#     max_match_count = 0
#     exclude_words = set()

#     # normalize input
#     lower_unique_words = set(w.lower() for w in unique_words)

#     # Step 1: count word frequency across formats
#     word_freq = {}
#     for data in config.values():
#         words = set(w.lower() for w in data.get("fields", []))
#         for w in words:
#             word_freq[w] = word_freq.get(w, 0) + 1

#     # Step 2: identify common words (appear in more than 1 format)
#     common_words = {w for w, count in word_freq.items() if count > 1}

#     # print("\nCommon words (ignored):", common_words)

#     # Step 3: match using only distinctive words
#     for name, data in config.items():
#         format_words = set(w.lower() for w in data.get("fields", []))

#         # remove common words
#         distinctive_words = format_words - common_words

#         matches = lower_unique_words & distinctive_words
#         match_count = len(matches)

#         # 🔍 debug
#         # print(f"\nFormat: {name}")
#         # print(f"Distinctive words: {distinctive_words}")
#         # print(f"Matched distinctive words ({match_count}): {matches}")

#         if match_count > max_match_count:
#             max_match_count = match_count
#             detected_format = name
#             exclude_words = format_words

#     print("\n✅ Final", detected_format)

#     return detected_format, exclude_words

def detect_invoice_format(unique_words, config):

    detected_format = None
    best_score = 0
    exclude_words = set()

    # normalize OCR words
    lower_unique_words = set(w.lower() for w in unique_words)

    # build word frequency map
    word_freq = {}

    for data in config.values():

        words = set(w.lower() for w in data.get("fields", []))

        for w in words:
            word_freq[w] = word_freq.get(w, 0) + 1

    # score each format
    for name, data in config.items():

        format_words = set(w.lower() for w in data.get("fields", []))

        score = 0
        matches = []

        for word in format_words:

            if word in lower_unique_words:

                # rare words get higher score
                weight = 1 / word_freq[word]

                score += weight
                matches.append(word)

        print(f"\nFormat: {name}")
        print(f"Matches: {matches}")
        print(f"Score: {score}")

        if score > best_score:

            best_score = score
            detected_format = name
            exclude_words = format_words

    print("\n✅ Final Detected Format:", detected_format)

    return detected_format, exclude_words


def transform_raw_pdf(pdf_path, output_folder, config):
    """
    Encode an actual PDF (not scanned/image) using bbox overlays.
    Also exports each page as a high-res PNG image.
    
    Returns:
        output_images: list of page image paths
        mapping_path: path to Excel mapping
        success: True/False
        doc_obj: None (placeholder for consistency)
        is_pdf: True
        error_msg: None or error string
    """
    os.makedirs(output_folder, exist_ok=True)

    # ---------- Paths ----------
    output_pdf_path = os.path.join(output_folder, "encoded_output.pdf")
    mapping_path = os.path.join(output_folder, "encrypted_mapping_3digit.xlsx")

    # ---------- Open PDF ----------
    doc = fitz.open(pdf_path)
    new_doc = fitz.open()
    output_images = []

    # ---------- Extract all words ----------
    all_words = []
    for page_index in range(len(doc)):
        page = doc[page_index]
        words = page.get_text("words")  # word-level info
        for w in words:
            all_words.append(w[4].strip())  # word text

    # ---------- UNIQUE WORDS & FORMAT ----------
    unique_words = sorted(set(all_words))
    print("------unique words------",unique_words)
    print("------config------",config)

    detected_format, EXCLUDE_WORDS_SET = detect_invoice_format(unique_words, config)
    print("------detected customer config--------------", detected_format)

    if not detected_format:
        return [], "", False, None, True, "Customer config not found"

    # ---------- Prepare mapping ----------
    word_to_code = {}
    short_chars = string.digits + string.ascii_lowercase
    
    # import string
    short_chars = string.ascii_lowercase + string.digits

    def generate_code(word_length):
        while True:
            if word_length < 3:
                code = random.choice(short_chars)
            else:
                code = str(random.randint(100, 999))
            if code not in word_to_code.values():
                return code

    # ---------- Process each page ----------
    for page_index in range(len(doc)):
        page = doc[page_index]
        rect = page.rect
        new_page = new_doc.new_page(width=rect.width, height=rect.height)
        new_page.show_pdf_page(rect, doc, page_index)

        words = page.get_text("words")
        for w in words:
            x0, y0, x1, y1, word, *_ = w
            clean_word = word.strip()
            if not clean_word or clean_word.lower() in EXCLUDE_WORDS_SET:
                continue

            # Assign code
            if clean_word not in word_to_code:
                word_to_code[clean_word] = generate_code(len(clean_word))

            code_val = word_to_code[clean_word]

            # Draw transparent bbox with gray border
            bbox = fitz.Rect(x0, y0, x1, y1)
            new_page.draw_rect(
                bbox,
                fill=(1, 1, 1),        # white fill
                color=(0.5, 0.5, 0.5), # gray outline
                width=0.3,
                
            )

            # Overlay code text
            new_page.insert_text(
                (x0, y1 - 2),
                code_val,
                fontsize=8,
                fontname="helv",
                color=(0, 0, 0),
                overlay=True
            )

        # ---------- Save page as image ----------
        pix = new_page.get_pixmap(dpi=300)
        img_path = os.path.join(output_folder, f"page_{page_index + 1}.png")
        pix.save(img_path)
        output_images.append(img_path)

    # ---------- Save encoded PDF ----------
    new_doc.save(output_pdf_path)
    new_doc.close()
    doc.close()

    # ---------- Save mapping ----------
    df = pd.DataFrame([{'Original Word': k, 'Encrypted Word': v} for k, v in word_to_code.items()])
    df.to_excel(mapping_path, index=False)

    # ---------- Return ----------
    return output_images, mapping_path, True, None, True, None

# ---------------- TRANSFORM ----------------
def transform(pdf_path, output_folder, config, doc_type):
    os.makedirs(output_folder, exist_ok=True)

    # ---------- WORD EXTRACTION FUNCTION ----------
    def extract_words_from_pdf(path):
        word_locs = []
        with pdfplumber.open(path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                merged = merge_close_words(page.extract_words())
                for w in merged:
                    word_locs.append({
                        "page": page_num,
                        "text": w["text"],
                        "x0": w["x0"],
                        "top": w["top"],
                        "x1": w["x1"],
                        "bottom": w["bottom"],
                        "height": w["bottom"] - w["top"]
                    })
        return word_locs

    # ---------- CASE 3: IMAGE INPUT ----------
    if pdf_path.lower().endswith(('.png', '.jpg', '.jpeg')):
        pdf_path = image2pdfstreams(pdf_path)

    # ---------- CASE 1 & 2: EXTRACT WORDS ----------
    word_locations = extract_words_from_pdf(pdf_path)

    if word_locations:
        print("------------actual pdf processing--------------")
        return transform_raw_pdf(pdf_path, output_folder, config)

    # ---------- SCANNED PDF / NO TEXT (CASE 2) ----------
    if not word_locations:
        images_paths = pdf_to_images(pdf_path, output_folder, dpi=300)
        searchable_pdfs = []
        for img_path in images_paths:
            pdf_page = image2pdfstreams(img_path)
            searchable_pdfs.append(pdf_page)
        all_word_locations = []
        for pdf_page_path in searchable_pdfs:
            locs = extract_words_from_pdf(pdf_page_path)
            all_word_locations.extend(locs)
        word_locations = all_word_locations
        if not word_locations:
            return [], "", False, None, False, "No text found after OCR"

    # ---------- UNIQUE WORDS & FORMAT ----------
    unique_words = sorted({w["text"] for w in word_locations})
    detected_format, EXCLUDE_WORDS_SET = detect_invoice_format(unique_words, config)
    print("------detected customer config--------------", detected_format)
    if not detected_format:
        
        return [], "", False, None, False, "Customer config not found"

    # ---------- 3-DIGIT ENCRYPTION ----------
    word_to_code = {}
    code = 100
    for w in unique_words:
        if w.lower() not in EXCLUDE_WORDS_SET:
            word_to_code[w] = str(code).zfill(3)
            code += 1

    # ---------- SAVE MAPPING ----------
    mapping_path = os.path.join(output_folder, "encrypted_mapping_3digit.xlsx")
    df = pd.DataFrame([{'Original Word': k, 'Encrypted Word': v} for k, v in word_to_code.items()])
    df.to_excel(mapping_path, index=False)

    # ---------- PROCESS EACH PAGE ----------
    doc = fitz.open(pdf_path)
    output_images = []
    for page_number in range(len(doc)):
        page = doc.load_page(page_number)
        pix = page.get_pixmap(dpi=300)
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)

        # Table detection
        num_tables = detect_table(img_np)
        if num_tables < 1:
            continue

        rgb = cv2.cvtColor(img_np, cv2.COLOR_BGR2RGB)
        ocr_data = pytesseract.image_to_data(rgb, output_type=pytesseract.Output.DICT)

        # Create mask for inpainting
        mask = np.zeros(img_np.shape[:2], dtype="uint8")
        for i, word in enumerate(ocr_data['text']):
            word = word.strip()
            if word in word_to_code:
                x, y, w, h = ocr_data['left'][i], ocr_data['top'][i], ocr_data['width'][i], ocr_data['height'][i]
                x0, y0 = x, y
                x1, y1 = x + w, y
                x2, y2 = x + w, y + h
                x3, y3 = x, y + h
                mid_start = midpoint(x0, y0, x3, y3)
                mid_end = midpoint(x1, y1, x2, y2)
                thickness = int(math.hypot(x3 - x0, y3 - y0))
                cv2.line(mask, mid_start, mid_end, 255, thickness)

        inpainted_img = cv2.inpaint(img_np, mask, 7, cv2.INPAINT_NS)

        # Overlay encrypted words
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1
        thickness = 0
        for i, word in enumerate(ocr_data['text']):
            word = word.strip()
            if word in word_to_code:
                x, y, w, h = ocr_data['left'][i], ocr_data['top'][i], ocr_data['width'][i], ocr_data['height'][i]
                encrypted_word = word_to_code[word]
                text_size = cv2.getTextSize(encrypted_word, font, font_scale, thickness)[0]
                text_x = x + (w - text_size[0]) // 2
                text_y = y + (h + text_size[1]) // 2
                cv2.putText(inpainted_img, encrypted_word, (text_x, text_y), font, font_scale, (0, 0, 0), thickness)

        # Save high-res page_n.png
        img_path = os.path.join(output_folder, f"page_{page_number + 1}.png")
        cv2.imwrite(img_path, inpainted_img)
        output_images.append(img_path)

    return output_images, mapping_path, True, None, True, None