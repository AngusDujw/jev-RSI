"""Small printed-digit OCR using local font templates; reject ambiguous matches."""
import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from pathlib import Path


def normalize(binary):
    yy,xx=np.where(binary)
    if len(xx)<8: return None
    crop=binary[yy.min():yy.max()+1,xx.min():xx.max()+1].astype(np.uint8)
    h,w=crop.shape; scale=40/max(h,w); patch=cv2.resize(crop,(max(1,round(w*scale)),max(1,round(h*scale))),interpolation=cv2.INTER_NEAREST)
    out=np.zeros((48,48),np.uint8); y=(48-patch.shape[0])//2;x=(48-patch.shape[1])//2
    out[y:y+patch.shape[0],x:x+patch.shape[1]]=patch
    return out


class DigitOCR:
    def __init__(self):
        self.templates=[]
        fonts=list(Path('/usr/share/fonts/truetype/dejavu').glob('DejaVuSans*.ttf'))
        for digit in '0123456789':
            for font in fonts:
                im=Image.new('L',(100,100)); ImageDraw.Draw(im).text((15,5),digit,font=ImageFont.truetype(str(font),65),fill=255)
                self.templates.append((digit,normalize(np.asarray(im)>100)))
            for font in [cv2.FONT_HERSHEY_SIMPLEX,cv2.FONT_HERSHEY_DUPLEX,cv2.FONT_HERSHEY_COMPLEX]:
                for thickness in (2,3,4):
                    im=np.zeros((100,100),np.uint8); cv2.putText(im,digit,(10,80),font,2.5,255,thickness,cv2.LINE_AA)
                    self.templates.append((digit,normalize(im>100)))
    def read(self,rgb,polygon):
        h,w=rgb.shape[:2]; poly=np.asarray(polygon)*[w-1,h-1]
        lo=np.maximum(0,np.floor(poly.min(0)).astype(int)); hi=np.minimum([w,h],np.ceil(poly.max(0)).astype(int)+1)
        crop=rgb[lo[1]:hi[1],lo[0]:hi[0]]
        if min(crop.shape[:2])<8:return '',dict(reason='small_crop')
        gray=cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY)
        binary=(gray<min(100,float(np.quantile(gray,.3)))).astype(np.uint8)
        n,lab,stats,_=cv2.connectedComponentsWithStats(binary)
        valid=[i for i in range(1,n) if stats[i,4]>=8 and stats[i,3]>.25*gray.shape[0] and stats[i,3]<.95*gray.shape[0]]
        if not valid:return '',dict(reason='no_digit_component')
        parts=[]; diagnostics=[]
        for i in sorted(valid,key=lambda i:stats[i,0]):
            mask=normalize(lab==i); scores={d:0. for d in '0123456789'}
            for d,t in self.templates:
                score=float((mask&t).sum()/max(1,(mask|t).sum()));scores[d]=max(scores[d],score)
            rank=sorted(scores.items(),key=lambda z:-z[1]);diagnostics.append(rank[:2])
            if rank[0][1]<.46 or rank[0][1]-rank[1][1]<.025:return '',dict(reason='ambiguous_template',scores=diagnostics)
            parts.append(rank[0][0])
        return ''.join(parts),dict(source='pixel_template_OCR',scores=diagnostics)
