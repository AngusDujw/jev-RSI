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
    def __init__(self,folder,differential_camera=None):
        self.folder=Path(folder)/('sam-cap-differential' if differential_camera else 'sam-cap')
        self.folder.mkdir(exist_ok=True)
        self.engine=None
        self.differential_camera=differential_camera;self.templates={};self.differential_enabled=False

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
        if self.differential_camera and self.differential_enabled:
            from cap_differential import measure
            name=self.differential_camera
            if name not in masks:
                fit=dict(usable=False,reason='Independent camera material mask unavailable')
            else:
                key=(identity,name)
                if key not in self.templates:
                    # First call for this identity occurs before the pressing
                    # hand approaches. These are same-episode sensor references.
                    self.templates[key]=(public,masks[name].copy(),dict(cap))
                    save(directory/'template_reference.json',dict(step=public['step'],camera=name,
                        cap_base_hypothesis=cap,scope='Unpressed same-episode RGB reference, not retrieved experience'))
                baseline,baseline_mask,base_cap=self.templates[key]
                old=np.asarray(baseline['calibration'][name]['camera_to_environment']);now=np.asarray(public['calibration'][name]['camera_to_environment'])
                from scipy.spatial.transform import Rotation
                drift=float(np.linalg.norm(old[:3,3]-now[:3,3]));angle=float(Rotation.from_matrix(now[:3,:3]@old[:3,:3].T).magnitude())
                measured=measure(public,baseline,masks[name],baseline_mask,base_cap,name,base_cap['center_m'][2])
                center=np.asarray(base_cap['center_m'],float).copy();center[2]-=measured.get('downward_displacement_m',0.)
                fit=dict(usable=bool(measured.get('usable') and drift<=.001 and angle<=.005),center_m=center.tolist(),
                    conditional_halfwidth_m=[.002,.002,measured.get('conditional_travel_halfwidth_m',.008)],
                    rim_rms_px=measured.get('rim_template_rms_px',100.),camera_names=[name],differential=measured,
                    observer_translation_drift_m=drift,observer_rotation_drift_rad=angle,
                    source='Independent current RGB differential rim travel; absolute base XYZ retained only as a visual hypothesis',
                    limits='Only travel is currently measured. Base XY/Z are unpressed RGB hypotheses; no fresh absolute object pose, contact or electrical state.')
        fit.update(step=public['step'],identity=identity,actor_images=0,
            current_material_views=list(masks),segmentation_valid=bool(masks),
            segmentation_source='Local cached SAM2.1 tiny; geometry from fresh RGB and public camera/robot data')
        save(directory/'geometry.json',fit)
        return fit
