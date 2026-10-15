"""Current RGB cap observation with local SAM masks and public calibration."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from sam2_masks import Segmenter
from rgb_cuboid import project
from cap_motion import cap_pose,tool_mask
from robodojo_episode import save


def load_public(folder,step):
    path=Path(folder)/f'frame-{step:06d}'
    public=json.loads((path/'public.json').read_text())
    public['rgb']={name:np.array(Image.open(path/(name+'.png'))) for name in public['calibration']}
    return public


class CapObserver:
    def __init__(self,folder):
        self.folder=Path(folder)/'sam-cap'
        self.folder.mkdir(exist_ok=True)
        self.engine=None

    def measure(self,public,cap,identity='red1'):
        directory=self.folder/f'{public["step"]:06d}-{identity}'
        if (directory/'geometry.json').exists():
            return json.loads((directory/'geometry.json').read_text())
        directory.mkdir(exist_ok=True)
        center=np.asarray(cap['center_m'])
        color=cap.get('color','red')
        angles=np.linspace(0,2*np.pi,100,endpoint=False)
        offsets=cap['radius_m']*np.column_stack([np.cos(angles),np.sin(angles),np.zeros(len(angles))])
        images=[];boxes=[];points=[];names=[]
        for name,rgb in public['rgb'].items():
            camera=public['calibration'][name]
            uv,depth=project(camera,np.vstack([center+offsets+[0,0,z] for z in (-.022,.008)]))
            if min(depth)<=.01:
                continue
            lower=np.maximum([0,0],uv.min(0)-8)
            upper=np.minimum([rgb.shape[1]-1,rgb.shape[0]-1],uv.max(0)+8)
            if np.any(upper-lower<8):
                continue
            r,g,b=rgb.astype(float).transpose(2,0,1)
            material=((r>180)&(r>1.8*g)&(r>1.8*b)) if color=='red' else ((b>180)&(b>1.8*r)&(b>1.8*g))
            red=material&(tool_mask(public,name)==0)
            region=np.zeros(red.shape,bool)
            region[int(lower[1]):int(upper[1])+1,int(lower[0]):int(upper[0])+1]=True
            yy,xx=np.nonzero(red&region)
            if not len(xx):
                continue
            center_uv,_=project(camera,center.reshape(1,3))
            index=((xx-center_uv[0,0])**2+(yy-center_uv[0,1])**2).argmin()
            images.append(Image.fromarray(rgb));boxes.append([*lower,*upper])
            points.append([int(xx[index]),int(yy[index])]);names.append(name)
        masks={};metadata=[]
        if images:
            if self.engine is None:
                self.engine=Segmenter()
            results=self.engine.predict_batch(images,boxes,points)
            for name,box,point,result in zip(names,boxes,points,results):
                candidates=result.pop('masks')
                index=int(np.argmax(result['predicted_iou']))
                np.save(directory/(name+'-candidates.npy'),candidates)
                result.update(camera=name,box=np.asarray(box).tolist(),point=point,selected_index=index)
                result['source']='Current RGB, camera-derived box and visible '+color+' material point; local cached SAM2.1 tiny'
                metadata.append(result)
                if result['predicted_iou'][index]>=.8:
                    masks[name]=candidates[index]
        save(directory/'segmentation.json',metadata)
        fit=cap_pose(public,cap,masks)
        fit.update(step=public['step'],identity=identity,actor_images=0,
            current_material_views=list(masks),segmentation_valid=bool(masks),
            segmentation_source='Local cached SAM2.1 tiny; geometry from fresh RGB and public camera/robot data')
        save(directory/'geometry.json',fit)
        return fit
