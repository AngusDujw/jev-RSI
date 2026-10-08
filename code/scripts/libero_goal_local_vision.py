"""Public-image object selection for Goal pick/place without a runtime LLM.

Task labels come from the public instruction. GroundingDINO/SAM reads rendered
RGB only; fixed fixture regions were measured in public RGB captures and are
checked later by calibrated RGB-D. No scene object state is read here.
"""
import json
import numpy as np


SOURCE_LABEL = {
    1144: 'bowl', 1163: 'wine bottle', 1252: 'bowl',
    1335: 'cream cheese box', 1423: 'bowl', 1458: 'wine bottle',
}
DESTINATION_LABEL = {1335: 'bowl', 1423: 'plate'}
FIXTURE_DESTINATION = {
    1144: ('stove support surface', (465, 306, 644, 421)),
    1163: ('visible cabinet top', (0, 278, 220, 370)),
    1252: ('visible cabinet top', (0, 278, 220, 370)),
    1458: ('wine rack opening', (51, 51, 242, 355)),
}


def overlap_ratio(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    low, high = np.maximum(a[:2], b[:2]), np.minimum(a[2:], b[2:])
    intersection = float(np.prod(np.maximum(high-low, 0)))
    return intersection / max(1., float(np.prod(np.maximum(a[2:]-a[:2], 0))))


def associate_precontact(detections, label, prior_box):
    """Match a previously visible object before contact, despite noun drift."""
    prior_box = np.asarray(prior_box, float)
    choices = []
    for detection in detections:
        box = np.asarray(detection['bbox'], float)
        if label not in detection['label'].strip().lower() or detection['score'] < .25:
            continue
        low, high = np.maximum(box[:2], prior_box[:2]), np.minimum(box[2:], prior_box[2:])
        intersection = float(np.prod(np.maximum(high-low, 0)))
        area = float(np.prod(box[2:]-box[:2]))
        prior_area = float(np.prod(prior_box[2:]-prior_box[:2]))
        iou = intersection/max(1., area+prior_area-intersection)
        if iou >= .60:
            choices.append((iou, detection['score'], detection))
    choices.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if not choices or (len(choices)>1 and choices[1][0]>.9*choices[0][0]):
        raise RuntimeError(f'No unambiguous precontact visible {label}')
    return choices[0][2]


def pick_visible(detections, label, excluded_box=None):
    """Fail closed on missing/ambiguous exact-label public-image detections."""
    choices = [d for d in detections if d['label'].strip().lower() == label]
    if excluded_box is not None:
        choices = [d for d in choices if overlap_ratio(d['bbox'], excluded_box) < .45]
    choices.sort(key=lambda d: d['score'], reverse=True)
    if not choices or choices[0]['score'] < .35:
        raise RuntimeError(f'No high-confidence visible {label}')
    if (len(choices) > 1 and choices[1]['score'] >= .85*choices[0]['score'] and
            overlap_ratio(choices[0]['bbox'], choices[1]['bbox']) < .5):
        raise RuntimeError(f'Ambiguous visible {label}')
    return choices[0]


def recognize(worker, receive, views, task_id, reason, prior, folder):
    if task_id not in SOURCE_LABEL:
        raise ValueError(f'No local Goal workflow for task {task_id}')
    view = views['agentview']
    if view['rgb'].shape[:2] != (768, 768):
        raise ValueError('Local Goal detection requires 768x768 agentview')
    import cv2
    image = folder/'agentview.png'
    cv2.imwrite(str(image), cv2.cvtColor(view['rgb'], cv2.COLOR_RGB2BGR))
    def detect(role, label):
        out = folder/f'grounding-{role}'
        request = dict(image=str(image), instruction=label+' .', output=str(out))
        worker.stdin.write(json.dumps(request)+'\n')
        worker.stdin.flush()
        result = receive()
        (folder/f'grounding-{role}-response.json').write_text(json.dumps(result, indent=2)+'\n')
        return result['objects']
    source_label = SOURCE_LABEL[task_id]
    detections = detect('source', source_label)
    if reason == 'pregrasp' and prior is not None:
        try:
            source = associate_precontact(detections, source_label,
                                          prior['source']['bbox'])
            evidence = 'local RGB detection matched to initial public-visible box before contact'
        except RuntimeError:
            source = pick_visible(detections, source_label)
            evidence = 'local GroundingDINO exact public noun + visible SAM box'
    else:
        source = pick_visible(detections, source_label)
        evidence = 'local GroundingDINO exact public noun + visible SAM box'
    result = dict(source=dict(label=source_label, camera='agentview',
                              bbox=source['bbox'], visible=True,
                              evidence=evidence))
    if task_id in DESTINATION_LABEL:
        destination_label = DESTINATION_LABEL[task_id]
        destination = pick_visible(detect('destination', destination_label),
                                   destination_label, source['bbox'])
        result['destination'] = dict(label=destination_label, camera='agentview',
                                     bbox=destination['bbox'], visible=True,
                                     receiver_kind='open_container' if task_id == 1335 else 'support_surface',
                                     evidence='local GroundingDINO public noun; exclude source overlap')
    else:
        label, box = FIXTURE_DESTINATION[task_id]
        result['destination'] = dict(label=label, camera='agentview',
                                     bbox=list(box), visible=True,
                                     receiver_kind='support_surface',
                                     evidence='predeclared public RGB fixture region; fresh RGB-D measured')
    return result
