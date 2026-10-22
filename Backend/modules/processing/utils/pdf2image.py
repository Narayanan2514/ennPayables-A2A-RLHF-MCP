import os
import fitz  # PyMuPDF

def pdf_to_images(pdf_path, output_folder, image_start_index=1, dpi=300):
    """
    Convert PDF pages to high-resolution PNG images using PyMuPDF.

    Args:
        pdf_path (str): Path to the PDF file.
        output_folder (str): Folder where images will be saved.
        image_start_index (int): Starting index for image filenames.
        dpi (int): Desired resolution for images (default 300).

    Returns:
        List[str]: Paths of saved images.
    """
    os.makedirs(output_folder, exist_ok=True)
    doc = fitz.open(pdf_path)
    image_paths = []

    # Calculate zoom factor to reach the desired DPI
    zoom = dpi / 72  # 72 is default PDF pixel density
    matrix = fitz.Matrix(zoom, zoom)

    for i in range(len(doc)):
        page = doc.load_page(i)  # load page i
        pix = page.get_pixmap(matrix=matrix)  # render page at high DPI

        # Save image
        image_path = os.path.join(output_folder, f"page_{image_start_index + i}.png")
        pix.save(image_path)
        image_paths.append(image_path)
        print(f"📸 Saved page {i+1} as high-res image: {image_path}")

    doc.close()
    return image_paths