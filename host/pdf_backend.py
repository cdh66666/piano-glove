"""Read-only PDFium adapter used by the vector recognizer and page preview.

Only the low-level PDF geometry is adapted. Musical rules live in the recognizer.
All PDFium calls in this process must share PDF_LOCK; PDFium is not thread-safe.
Coordinates returned here are PDF points with a top-left origin.
"""
from contextlib import contextmanager, closing
import ctypes
import math
from threading import RLock
from types import SimpleNamespace

import pypdfium2 as pdfium
import pypdfium2.raw as raw

PDF_LOCK = RLock()


def _multiply(outer, inner):
    a,b,c,d,e,f = outer
    g,h,i,j,k,l = inner
    return (a*g+c*h, b*g+d*h, a*i+c*j, b*i+d*j, a*k+c*l+e, b*k+d*l+f)


def _matrix(obj):
    m = raw.FS_MATRIX()
    if not raw.FPDFPageObj_GetMatrix(obj, m):
        raise ValueError('无法读取 PDF 路径坐标变换')
    return (m.a,m.b,m.c,m.d,m.e,m.f)


def _point(matrix, x, y, height):
    a,b,c,d,e,f = matrix
    # The PDF canvas stores single-precision coordinates. Keep each affine
    # operation at that precision; double intermediates can move a beam onto
    # the recognizer's exact distance boundary by one floating-point unit.
    px=ctypes.c_float(ctypes.c_float(a*x+c*y).value+e).value
    py=ctypes.c_float(ctypes.c_float(b*x+d*y).value+f).value
    return (px,ctypes.c_float(height-py).value)


def _scale(matrix):
    a,b,c,d,_,_ = matrix
    return math.sqrt(abs(a*d-b*c))


class VectorPage:
    def __init__(self, page):
        self.page = page
        width,height = page.get_size()
        self.rect = SimpleNamespace(width=width,height=height)
        # The supplied Aloisen scores have unrotated zero-origin crop boxes.
        # Reject unsupported coordinates explicitly rather than silently moving
        # notes to the wrong staff on other PDFs.
        left,bottom,_,_ = page.get_cropbox()
        if page.get_rotation() or abs(left)>1e-4 or abs(bottom)>1e-4:
            raise ValueError('此 PDF 的旋转或裁切坐标需要先恢复为普通竖向页面')

    def chars(self):
        result=[]
        with closing(self.page.get_textpage()) as text:
            for index in range(text.count_chars()):
                flags=ctypes.c_int()
                length=raw.FPDFText_GetFontInfo(text,index,None,0,flags)
                if not length:
                    continue
                buffer=ctypes.create_string_buffer(length)
                raw.FPDFText_GetFontInfo(text,index,buffer,length,flags)
                if buffer.value.decode('utf-8',errors='replace').split('+')[-1] != 'Aloisen':
                    continue
                unicode_value=raw.FPDFText_GetUnicode(text,index)
                if not unicode_value or raw.FPDFText_IsGenerated(text,index):
                    continue
                x,y=ctypes.c_double(),ctypes.c_double()
                if not raw.FPDFText_GetCharOrigin(text,index,x,y):
                    raise ValueError('无法读取 PDF 音符字符的位置')
                matrix=raw.FS_MATRIX()
                if not raw.FPDFText_GetMatrix(text,index,matrix):
                    raise ValueError('无法读取 PDF 音符字号变换')
                size=raw.FPDFText_GetFontSize(text,index)*math.sqrt(abs(matrix.a*matrix.d-matrix.b*matrix.c))
                # Ignore font-line boxes completely outside the page, matching
                # normal clipped page text extraction. Tight glyph bounds can
                # otherwise expose a clipped finger number at the page edge.
                origin_y=self.rect.height-y.value
                if origin_y+.2*size<0 or origin_y-.8*size>self.rect.height:
                    continue
                left,bottom,right,top=text.get_charbox(index)
                red,green,blue,alpha=(ctypes.c_uint() for _ in range(4))
                raw.FPDFText_GetFillColor(text,index,red,green,blue,alpha)
                result.append(dict(char=chr(unicode_value),x=x.value,y=self.rect.height-y.value,
                                   bbox=[left,self.rect.height-top,right,self.rect.height-bottom],
                                   size=size,color=(red.value<<16)|(green.value<<8)|blue.value))
        return result

    def geometry(self):
        lines,curves=[],[]
        identity=(1,0,0,1,0,0)

        def visit(container,parent,is_form=False,depth=0):
            if depth>15:
                raise ValueError('PDF 嵌套结构过深，无法可靠识别')
            count=raw.FPDFFormObj_CountObjects(container) if is_form else raw.FPDFPage_CountObjects(container)
            getter=raw.FPDFFormObj_GetObject if is_form else raw.FPDFPage_GetObject
            for index in range(count):
                obj=getter(container,index)
                kind=raw.FPDFPageObj_GetType(obj)
                if kind not in (raw.FPDF_PAGEOBJ_PATH,raw.FPDF_PAGEOBJ_FORM):
                    continue
                matrix=_multiply(parent,_matrix(obj))
                if kind==raw.FPDF_PAGEOBJ_FORM:
                    visit(obj,matrix,True,depth+1)
                    continue
                fill,stroke=ctypes.c_int(),ctypes.c_int()
                if not raw.FPDFPath_GetDrawMode(obj,fill,stroke):
                    raise ValueError('无法读取 PDF 路径绘制类型')
                width=ctypes.c_float()
                raw.FPDFPageObj_GetStrokeWidth(obj,width)
                effective_width=ctypes.c_float(width.value*_scale(matrix)).value if stroke.value else 0
                path=[]
                for segment_index in range(raw.FPDFPath_CountSegments(obj)):
                    segment=raw.FPDFPath_GetPathSegment(obj,segment_index)
                    x,y=ctypes.c_float(),ctypes.c_float()
                    if not raw.FPDFPathSegment_GetPoint(segment,x,y):
                        raise ValueError('无法读取 PDF 路径节点')
                    path.append((raw.FPDFPathSegment_GetType(segment),x.value,y.value,
                                 bool(raw.FPDFPathSegment_GetClose(segment))))
                # Preserve the original recognizer's treatment of rectangle
                # primitives: their edges were not used as musical lines.
                if _is_rectangle(path):
                    continue
                previous=None;start=None;all_points=[];has_curve=False
                for kind,x,y,closed in path:
                    point=_point(matrix,x,y,self.rect.height);all_points.append(point)
                    if kind==raw.FPDF_SEGMENT_MOVETO:
                        previous=point;start=point
                    elif kind==raw.FPDF_SEGMENT_LINETO:
                        if previous is not None:
                            lines.append((*previous,*point,effective_width))
                        previous=point
                    elif kind==raw.FPDF_SEGMENT_BEZIERTO:
                        has_curve=True;previous=point
                    if closed and previous is not None and start is not None and previous!=start:
                        lines.append((*previous,*start,effective_width))
                        previous=start
                if has_curve and all_points:
                    curves.append([min(p[0] for p in all_points),min(p[1] for p in all_points),
                                   max(p[0] for p in all_points),max(p[1] for p in all_points)])
        visit(self.page.raw,identity)
        return lines,curves


def _is_rectangle(path):
    if len(path) not in (4,5) or not path[-1][3]:
        return False
    if path[0][0]!=raw.FPDF_SEGMENT_MOVETO or any(p[0]!=raw.FPDF_SEGMENT_LINETO for p in path[1:]):
        return False
    points=[(p[1],p[2]) for p in path]
    if len(points)==5:
        if points[-1]!=points[0]:
            return False
        points.pop()
    return len(set(points))==4 and all(abs(a[0]-b[0])<1e-5 or abs(a[1]-b[1])<1e-5
        for a,b in zip(points,points[1:]+points[:1]))


class VectorDocument:
    def __init__(self, document):
        self.document=document

    def __iter__(self):
        for index in range(len(self.document)):
            page=self.document[index]
            try:
                yield VectorPage(page)
            finally:
                page.close()


@contextmanager
def open_document(path):
    with PDF_LOCK, pdfium.PdfDocument(path) as document:
        yield VectorDocument(document)
