"""Isolated text-conditioned RGB segmentation server; no simulation access."""
import contextlib,json,sys,time
from pathlib import Path
import numpy as np
from PIL import Image
from local_rgbd_perception import build_detector

with contextlib.redirect_stdout(sys.stderr):
    detector,_=build_detector(dict(existing_root='/root/yekangjie/project/robodojo-jev'),1)
print(json.dumps(dict(ready=True)),flush=True)
for line in sys.stdin:
    try:
        r=json.loads(line)
        if r.get('close'):break
        start=time.monotonic();im=Image.open(r['image']).convert('RGB');w,h=im.size
        caption=r.get('instruction','')
        if r.get('boxes'):
            selected=[(k,str(b['label']),np.array(b['bbox'],float)) for k,b in enumerate(r['boxes'])]
            scores=[1.0]*len(selected)
        else:
            caption=r['instruction']+'. object. container. robot gripper.'
            inputs=detector.processor(images=im,text=caption,return_tensors='pt').to(detector.device)
            with detector.torch.inference_mode():pred=detector.detector(**inputs)
            d=detector.processor.post_process_grounded_object_detection(pred,inputs.input_ids,threshold=.20,text_threshold=.20,target_sizes=[(h,w)])[0]
            selected=[];labels=d.get('text_labels',d.get('labels'))
            from realman_jev.robodojo_rgb import iou
            for idx in d['scores'].argsort(descending=True).tolist():
                box=d['boxes'][idx].detach().cpu().numpy();label=str(labels[idx])
                if any(iou(box,s[2])>.7 for s in selected):continue
                if 'robot' in label or 'gripper' in label:continue
                selected.append((idx,label,box))
                if len(selected)>=12:break
            scores=[float(d['scores'][x[0]]) for x in selected]
        objects=[];out=Path(r['output']);out.mkdir(exist_ok=False)
        if selected:
            si=detector.sam_processor(images=im,input_boxes=[[x[2].tolist() for x in selected]],return_tensors='pt').to(detector.device)
            with detector.torch.inference_mode():sp=detector.sam(**si,multimask_output=False)
            masks=detector.sam_processor.post_process_masks(sp.pred_masks.cpu(),si['original_sizes'].cpu())[0].reshape(-1,h,w).numpy().astype(bool)
            for k,((idx,label,box),mask) in enumerate(zip(selected,masks)):
                if mask.sum()<30:continue
                path=out/f'mask-{k}.npy';np.save(path,mask)
                objects.append(dict(id=f'item_{k}',label=label,score=scores[k],bbox=box.tolist(),mask_path=str(path)))
        result=dict(objects=objects,caption=caption,seconds=time.monotonic()-start)
        (out/'detections.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
    except Exception as e:print(json.dumps(dict(error=type(e).__name__+': '+str(e))),flush=True)
