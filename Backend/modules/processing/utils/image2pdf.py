import fitz  # PyMuPDF
from PIL import Image
import pytesseract
import io
import shutil



# pytesseract.pytesseract.tesseract_cmd ="/usr/local/bin/tesseract"
pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract")

def image2pdfstreams(image_path):
    img = Image.open(image_path).convert("RGB")
    width, height = img.size

    # OCR with positional data
    ocr_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    # Create a blank PDF
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)

    # Insert image as background
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_bytes = img_byte_arr.getvalue()

    page.insert_image(fitz.Rect(0, 0, width, height), stream=img_bytes)

    # Overlay invisible/selectable text
    for i, word in enumerate(ocr_data['text']):
        if word.strip():
            x = ocr_data['left'][i]
            y = ocr_data['top'][i]
            w = ocr_data['width'][i]
            h = ocr_data['height'][i]

            # Flip y-axis for PDF coordinates
            pdf_y = height - y

            # Adjust position to better fit within word bbox
            point = fitz.Point(x, pdf_y)

            # Insert text with low opacity
            page.insert_text(point, word,
                             fontsize=h,
                             fontname="helv",
                             fill=(0, 0, 0),
                             fill_opacity=0.01,  # nearly invisible, but selectable
                             overlay=True)

    pdf_path = image_path.rsplit(".", 1)[0] + "_searchable.pdf"
    doc.save(pdf_path)
    doc.close()
    print(f"Searchable PDF saved to {pdf_path}")
    return pdf_path
