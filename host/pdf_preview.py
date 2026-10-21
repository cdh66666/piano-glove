"""Render the real PDF pages with PDFium; use the recognizer's shared lock."""
import base64
import io
import pypdfium2 as pdfium
from pdf_backend import PDF_LOCK

def render_pdf_pages(path):
    previews=[]
    with PDF_LOCK:
        with pdfium.PdfDocument(str(path)) as document:
            for index in range(len(document)):
                page=document[index]
                try:
                    width,height=page.get_size()
                    if width<=0 or height<=0:raise ValueError('PDF页面尺寸不正确')
                    bitmap=page.render(scale=min(1199/width,1599/height))
                    try:
                        image=bitmap.to_pil().convert('RGB')
                        buffer=io.BytesIO();image.save(buffer,format='PNG')
                        previews.append(dict(page=index+1,width=image.width,height=image.height,
                            data='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode('ascii')))
                        image.close()
                    finally:bitmap.close()
                finally:page.close()
    return previews
