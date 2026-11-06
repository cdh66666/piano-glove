"""Render the real PDF pages with PDFium; use the recognizer's shared lock."""
import base64
import io
import pypdfium2 as pdfium
from pdf_backend import PDF_LOCK

def render_pdf_region(path,page_number,x,y,width,height,scale=8):
    """Render one small region (PDF points, top-left origin) sharply for the review lens."""
    with PDF_LOCK:
        with pdfium.PdfDocument(str(path)) as document:
            if not 1<=page_number<=len(document):raise ValueError('页码超出范围')
            page=document[page_number-1]
            try:
                page_width,page_height=page.get_size()
                left,top=max(0,x),max(0,y)
                right,bottom=min(page_width,x+width),min(page_height,y+height)
                if right<=left or bottom<=top:raise ValueError('放大区域不在页面内')
                bitmap=page.render(scale=scale,crop=(left,page_height-bottom,page_width-right,top))
                try:
                    image=bitmap.to_pil().convert('RGB')
                    buffer=io.BytesIO();image.save(buffer,format='PNG')
                    image.close()
                finally:bitmap.close()
            finally:page.close()
    return dict(x=left,y=top,width=right-left,height=bottom-top,
                data='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode('ascii'))

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
