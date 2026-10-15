"""Fresh full-scissors RGB masks; include visible blades, not just mint handles."""
import json
import cv2
import numpy as np
from PIL import Image
from rgb_scissors import mint
from rgb_cuboid import ray,project
from sam2_masks import Segmenter
from robodojo_episode import save


class ScissorsMasks:
    def __init__(self,folder,table,seeds):
        self.folder=folder;self.table=table;self.seeds=seeds
        self.engine=None;self.tick=None;self.result=None
        self.point=None

    def __call__(self,public,prediction=None):
        if self.tick==public['step']:
            return self.result
        if self.engine is None:
            self.engine=Segmenter()
        if prediction is not None:
            self.point=np.asarray(prediction)
        if self.point is None:
            roi=self.seeds['cam_high']['neck_roi']
            origin,direction=ray(public['calibration']['cam_high'],[(roi[0]+roi[2])/2,(roi[1]+roi[3])/2])
            self.point=origin+direction*((self.table['plane_z_m']+.005-origin[2])/direction[2])
        names=[];images=[];boxes=[];points=[];materials=[]
        for name,rgb in public['rgb'].items():
            calibration=public['calibration'][name]
            uv,depth=project(calibration,self.point.reshape(1,3))
            if depth[0]<=.03:
                continue
            mask=mint(rgb,prediction=uv[0])
            if mask is None:
                continue
            yy,xx=np.nonzero(mask)
            if len(xx)<20:
                continue
            distance=cv2.distanceTransform(mask.astype(np.uint8),cv2.DIST_L2,3)
            v,u=np.unravel_index(distance.argmax(),distance.shape)
            focal=np.asarray(calibration['intrinsic'])[0,0]
            px=max(20,.07*focal/depth[0]);py=max(35,.13*focal/depth[0])
            box=[max(0,xx.min()-px),max(0,yy.min()-py),min(rgb.shape[1]-1,xx.max()+px),min(rgb.shape[0]-1,yy.max()+py)]
            names.append(name);images.append(Image.fromarray(rgb));boxes.append(box);points.append([u,v]);materials.append(mask)
        result={};records=[]
        if names:
            predictions=self.engine.predict_batch(images,boxes,points)
            for name,p,box,point,material in zip(names,predictions,boxes,points,materials):
                cleaned=[]
                for m in p['masks']:
                    _,labels=cv2.connectedComponents(m.astype(np.uint8))
                    label=labels[int(point[1]),int(point[0])]
                    cleaned.append((labels==label) if label else np.zeros_like(m))
                candidates=[i for i,m in enumerate(cleaned) if p['predicted_iou'][i]>=.8 and
                    (m&material.astype(bool)).sum()>=.6*material.sum() and m.sum()<.4*m.size]
                selected=max(candidates,key=lambda i:p['predicted_iou'][i]) if candidates else None
                directory=self.folder/f'frame-{public["step"]:06d}'
                for i,m in enumerate(p['masks']):
                    np.save(directory/f'scissors-{name}-sam{i}.npy',m)
                if selected is not None:
                    result[name]=cleaned[selected].astype(np.uint8)
                records.append(dict(camera=name,box=box,point=point,scores=p['predicted_iou'],selected=selected,
                    associated_component_pixels=int(result[name].sum()) if name in result else 0,
                    component_rule='Only the connected SAM component containing the visible mint material prompt'))
        save(self.folder/f'frame-{public["step"]:06d}'/'scissors_sam.json',dict(
            records=records,source='Fresh RGB and local cached SAM2.1 tiny, mint material identity; no object assets',
            limits='Predicted mask IoU is not measured task correctness; occlusion and blade/handle height differences remain uncertain'))
        self.tick=public['step'];self.result=result
        return result
