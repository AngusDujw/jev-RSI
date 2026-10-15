"""Local cached SAM2 image masks, never actor images or privileged scene state.

API: installed Transformers4.57.6, documented at
https://huggingface.co/docs/transformers/model_doc/sam2
"""
from pathlib import Path
import numpy as np
import torch
from transformers import Sam2Model,Sam2Processor

MODEL='facebook/sam2.1-hiera-tiny'
CACHE=Path('/root/yekangjie/project/robodojo-jev/.cache/models')


class Segmenter:
    def __init__(self):
        torch.set_num_threads(2)
        self.processor=Sam2Processor.from_pretrained(MODEL,cache_dir=str(CACHE),local_files_only=True)
        self.model=Sam2Model.from_pretrained(MODEL,cache_dir=str(CACHE),local_files_only=True).eval().to('cuda:0')

    def predict_batch(self,images,boxes,points):
        inputs=self.processor(images=images,input_boxes=[[list(map(float,box))] for box in boxes],
            input_points=[[[list(map(float,point))]] for point in points],
            input_labels=[[[1]] for _ in images],return_tensors='pt').to(self.model.device)
        with torch.inference_mode():
            outputs=self.model(**inputs,multimask_output=True)
        masks=self.processor.post_process_masks(outputs.pred_masks.cpu(),inputs['original_sizes'].cpu())
        scores=outputs.iou_scores.detach().cpu().numpy()
        return [dict(masks=value[0].numpy().astype(bool),predicted_iou=scores[i,0].tolist(),
            source='Current RGB with camera-derived box and visible red material point; local cached SAM2.1 tiny')
            for i,value in enumerate(masks)]
