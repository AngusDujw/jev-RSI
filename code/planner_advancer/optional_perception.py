"""Optional RGB correspondence tool; no robot commands or object-state access."""
from copy import deepcopy
from pathlib import Path
import json
import time


class DenseRGBMatcher:
    """CPU LoFTR indoor_new with an explicitly supplied local checkpoint."""

    def __init__(self, weights='/perception/weights/loftr_indoor_ds_new.ckpt', threads=4):
        import torch
        from kornia.feature import LoFTR
        from kornia.feature.loftr.loftr import default_cfg
        torch.set_num_threads(max(1, min(int(threads), 8)))
        config=deepcopy(default_cfg)
        config['coarse']['temp_bug_fix']=True
        self.model=LoFTR(pretrained=None, config=config).cpu().eval()
        checkpoint=torch.load(Path(weights), map_location='cpu', weights_only=True)
        self.model.load_state_dict(checkpoint['state_dict'], strict=True)

    @staticmethod
    def _image(path, max_side):
        import cv2
        import numpy as np
        import torch
        gray=cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise ValueError('Unreadable image: '+str(path))
        height,width=gray.shape
        if min(height,width)<8:
            raise ValueError('Image must be at least eight pixels on each side')
        scale=min(1., float(max_side)/max(height,width))
        resized_width=max(8,int(width*scale)//8*8)
        resized_height=max(8,int(height*scale)//8*8)
        resized=cv2.resize(gray,(resized_width,resized_height),interpolation=cv2.INTER_AREA)
        tensor=torch.from_numpy(np.ascontiguousarray(resized)).float()[None,None]/255.
        return tensor,[width,height],[resized_width,resized_height]

    def match(self, image0, image1, max_side=640):
        """Return original-image pixel correspondences, not geometry or identity."""
        import numpy as np
        import torch
        if not 64<=int(max_side)<=640:
            raise ValueError('max_side must be between 64 and 640')
        tensor0,size0,resized0=self._image(image0,int(max_side))
        tensor1,size1,resized1=self._image(image1,int(max_side))
        started=time.monotonic()
        with torch.inference_mode():
            result=self.model({'image0':tensor0,'image1':tensor1})
        pairs=[]
        for key,size,resized in [('keypoints0',size0,resized0),('keypoints1',size1,resized1)]:
            pixels=result[key].cpu().numpy()
            pairs.append(((pixels+.5)*(np.asarray(size)/np.asarray(resized))-.5).tolist())
        confidence=result['confidence'].cpu().numpy().tolist()
        return dict(keypoints0_px=pairs[0],keypoints1_px=pairs[1],confidence=confidence,
                    image0_size=size0,image1_size=size1,resized0_size=resized0,resized1_size=resized1,
                    inference_seconds=time.monotonic()-started,
                    meaning='Candidate same-surface correspondences in original pixel coordinates. '
                    'Confidence is a learned matching score, not calibrated positional uncertainty. '
                    'No object identity, depth, contact, clearance, action or grasp is established.')


class PromptedRGBMasks:
    """CPU SAM ViT-B masks from current-image prompts or an automatic grid."""

    def __init__(self, weights='/perception/weights/sam_vit_b_01ec64.pth', threads=4):
        import torch
        from segment_anything import sam_model_registry
        torch.set_num_threads(max(1,min(int(threads),8)))
        self.model=sam_model_registry['vit_b'](checkpoint=str(weights)).cpu().eval()

    @staticmethod
    def _read(path):
        import cv2
        image=cv2.imread(str(path))
        if image is None:
            raise ValueError('Unreadable image: '+str(path))
        return cv2.cvtColor(image,cv2.COLOR_BGR2RGB)

    @staticmethod
    def _save(image, masks, scores, output_dir):
        import cv2
        import numpy as np
        folder=Path(output_dir)
        folder.mkdir(parents=True,exist_ok=True)
        records=[]
        for index,(mask,score) in enumerate(zip(masks,scores)):
            ys,xs=np.nonzero(mask)
            if not len(xs):
                continue
            path=folder/f'mask-{index:03d}.png'
            if not cv2.imwrite(str(path),mask.astype(np.uint8)*255):
                raise RuntimeError('Could not write mask')
            records.append(dict(id=index,mask_path=str(path),area_px=int(len(xs)),
                bbox_xyxy_px=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)],
                predicted_mask_iou=float(score)))
        return dict(image_size=[image.shape[1],image.shape[0]],masks=records,
            meaning='Current-image region hypotheses, not semantic identities or full hidden object shapes. '
            'Mask scores are uncalibrated model estimates, not positional uncertainty. '
            'No depth, object pose, contact, clearance, action or grasp is established. '
            'Bounding boxes use exclusive maximum pixel coordinates.')

    def predict(self, image_path, output_dir, points_xy=None, labels=None, box_xyxy=None):
        import numpy as np
        import torch
        from segment_anything import SamPredictor
        image=self._read(image_path)
        height,width=image.shape[:2]
        points=None if points_xy is None else np.asarray(points_xy,dtype=np.float32)
        point_labels=None if labels is None else np.asarray(labels,dtype=np.int32)
        box=None if box_xyxy is None else np.asarray(box_xyxy,dtype=np.float32)
        if points is None and box is None:
            raise ValueError('Supply current-image points or a box')
        if points is not None:
            if points.ndim!=2 or points.shape[1]!=2 or not len(points) or not np.isfinite(points).all():
                raise ValueError('Points must be a finite nonempty Nx2 array')
            if (points<0).any() or (points[:,0]>=width).any() or (points[:,1]>=height).any():
                raise ValueError('Point outside current image')
            if point_labels is None:
                point_labels=np.ones(len(points),dtype=np.int32)
            if point_labels.shape!=(len(points),) or not np.isin(point_labels,[0,1]).all():
                raise ValueError('Point labels must be zero/one with one label per point')
        elif point_labels is not None:
            raise ValueError('Labels require points')
        if box is not None:
            if box.shape!=(4,) or not np.isfinite(box).all() or not (0<=box[0]<box[2]<=width and 0<=box[1]<box[3]<=height):
                raise ValueError('Box must be ordered finite in-image XYXY coordinates')
        started=time.monotonic()
        predictor=SamPredictor(self.model)
        with torch.inference_mode():
            predictor.set_image(image)
            masks,scores,_=predictor.predict(point_coords=points,point_labels=point_labels,box=box,multimask_output=True)
        result=self._save(image,masks,scores,output_dir)
        result['inference_seconds']=time.monotonic()-started
        return result

    def automatic(self, image_path, output_dir, points_per_side=16):
        import torch
        from segment_anything import SamAutomaticMaskGenerator
        if not 4<=int(points_per_side)<=24:
            raise ValueError('CPU points_per_side must be between four and 24')
        image=self._read(image_path)
        generator=SamAutomaticMaskGenerator(self.model,points_per_side=int(points_per_side),
            points_per_batch=16,crop_n_layers=0,output_mode='binary_mask')
        started=time.monotonic()
        with torch.inference_mode():
            proposals=generator.generate(image)
        result=self._save(image,[p['segmentation'] for p in proposals],
            [p['predicted_iou'] for p in proposals],output_dir)
        result['inference_seconds']=time.monotonic()-started
        return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('image0')
    parser.add_argument('image1')
    parser.add_argument('output',type=Path)
    parser.add_argument('--weights',default='/perception/weights/loftr_indoor_ds_new.ckpt')
    parser.add_argument('--max-side',type=int,default=640)
    args=parser.parse_args()
    matches=DenseRGBMatcher(args.weights).match(args.image0,args.image1,args.max_side)
    args.output.write_text(json.dumps(matches,allow_nan=False))
    print(json.dumps(dict(matches=len(matches['confidence']),seconds=matches['inference_seconds'])))
