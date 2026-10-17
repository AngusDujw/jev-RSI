"""Robot-only orientation previews; target poses are never scene truth."""
import io


def orientation_card(current,goal,candidates,vertices):
    import numpy as np
    from PIL import Image,ImageDraw,ImageFont
    from scipy.spatial import ConvexHull
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',20)
    small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)
    columns=3;cell_w=540;cell_h=340
    rows=(len(candidates)+columns-1)//columns
    picture=Image.new('RGB',(columns*cell_w,rows*cell_h+75),'#12212a')
    draw=ImageDraw.Draw(picture)
    draw.text((20,12),'Match ORANGE candidate fingers to CYAN target outline',fill='white',font=font)
    draw.text((20,43),'Three fixed world views per panel. Diagrams show robot orientation only, not scene clearance.',fill='#b6c8cf',font=small)
    pieces=[np.asarray(p,float) for p in vertices]
    extent=max(float(np.linalg.norm(p,axis=1).max()) for p in pieces)
    scale=80/max(extent,1e-5)
    views=[(0,1,'World XY'),(0,2,'World XZ'),(1,2,'World YZ')]
    for index,(name,rotation) in enumerate(candidates):
        left=index%columns*cell_w;top=75+index//columns*cell_h
        draw.rectangle((left+5,top+5,left+cell_w-5,top+cell_h-5),outline='#5a6f76',width=2)
        draw.text((left+15,top+15),name,fill='white',font=font)
        for j,(a,b,label) in enumerate(views):
            anchor=np.array([left+90+j*180,top+175])
            draw.line((tuple(anchor-[55,0]),tuple(anchor+[55,0])),fill='#32464f')
            draw.line((tuple(anchor-[0,75]),tuple(anchor+[0,90])),fill='#32464f')
            draw.text((left+30+j*180,top+285),label,fill='#b6c8cf',font=small)
            for pose,color,filled in ((rotation,'#ffab56',True),(goal,'#43e6d6',False)):
                for piece in pieces:
                    points=piece@pose.T
                    xy=anchor+points[:,[a,b]]*[scale,-scale]
                    xy=np.unique(np.round(xy,2),axis=0)
                    if len(xy)<3:continue
                    try:polygon=[tuple(p) for p in xy[ConvexHull(xy).vertices]]
                    except Exception:continue
                    if filled:draw.polygon(polygon,fill='#a76535')
                    draw.line(polygon+[polygon[0]],fill=color,width=3)
    buffer=io.BytesIO();picture.save(buffer,format='PNG')
    return buffer.getvalue()
