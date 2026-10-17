Optional CPU RGB tools are installed and local weights are available read-only. They are additional ingredients, not a task pipeline. Choose, combine or replace them according to the task and verify their usefulness on current observations. No simulator scene state or object assets are supplied.

```python
from optional_perception import DenseRGBMatcher, PromptedRGBMasks

matcher = DenseRGBMatcher()
matches = matcher.match(image0_path, image1_path, max_side=640)

segmenter = PromptedRGBMasks()
regions = segmenter.predict(image_path, '/output/regions',
                            points_xy=[[u, v]], labels=[1])
# Alternatively supply box_xyxy=[left, top, right, bottom],
# or generate current-image proposals without a prompt:
regions = segmenter.automatic(image_path, '/output/proposals', points_per_side=16)
```

`DenseRGBMatcher` uses Kornia LoFTR indoor_new. It returns keypoints0_px, keypoints1_px and confidence in the original images' pixel coordinates, plus image/resizing metadata. These are candidate same-surface correspondences. Reject inconsistent correspondences using calibration and appropriate image evidence before using them for geometry. A matching score is not calibrated positional uncertainty, object identity, depth or contact evidence. Combining learned and classical matching may be useful; more correspondences do not imply more correct object measurements.

`PromptedRGBMasks` uses SAM ViT-B. predict accepts current-image positive/negative points (labels 1/0) and/or an XYXY box. It returns mask proposals with PNG mask_path, pixel area, exclusive-maximum XYXY bounds and predicted_mask_iou. automatic supplies proposals from a regular point grid. Masks may omit, split or merge a visible object; IDs belong only to the current call. They do not identify the source semantically, recover hidden surfaces or establish three-dimensional geometry. Model scores are not calibrated measurement uncertainty.

Use current image evidence to supply or compute any runtime prompts, and check region identity instead of assuming a preparation-time pixel still names the object. Inspect masks and correspondences. A processor may use them to construct task-specific visual relations, overlays or uncertain geometry, but must not select actions. These helpers expose no task-success signals and retain no observation history. Store runtime outputs under /output; do not load new model weights during control. The helpers and checkpoints are under /perception; only code, packages and weights are mounted there, with no saved experiment images or test observations.

Sources: https://kornia.readthedocs.io/en/stable/feature.html and https://github.com/facebookresearch/segment-anything .
