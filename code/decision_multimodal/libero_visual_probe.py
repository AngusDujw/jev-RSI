"""Paired, read-only visual-coordinate probes. Never instantiate a robot env."""
import argparse
import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys

from legacy_decisions import MODEL, convert_request, english
from libero_prompt_revision import RevisedAPI

CAPTION = (
    'Yellow cross: original frontend positional target. White circle: measured control reference. '
    'Optional world ruler at that reference: red +X, green +Y, blue +Z, each 0.05 m, '
    'projected using current OpenCV K and camera-to-world T. Calibration only, not an action recommendation. '
    'Missing or collapsed axes do not mean zero motion. Image directions depend on the camera.')
QUESTION = (
    'For world {axis}, select the existing categorical direction toward the current stage goal. '
    'Use both current views, camera calibration, measured end-effector state and retained feedback. '
    'The optional ruler indicates positive world axes, not desired motion. '
    'Keep still in gripper-only stages; preserve the original tolerance and phase gates.')


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def reference(request):
    state = request['state']
    tol = state.get('axis_hold_tolerance_mm')
    if tol is None and 'hold_tolerance_m' in state:
        tol = state['hold_tolerance_m'] * 1000
    expected = {}
    for axis, row in state.get('translation_axes', {}).items():
        error = row.get('goal_minus_current_mm')
        if error is None or axis not in 'xyz':
            continue
        within = (abs(error) <= tol if tol is not None else
                  row.get('relation', '').replace(' ', '_') == 'within_tolerance' or error == 0)
        expected[axis] = ('hold' if within else
                          'positive' if error > 0 else 'negative')
    return expected


class Recorder:
    def __init__(self, folder):
        self.folder = folder
        folder.mkdir(parents=True)

    def log(self, value):
        with (self.folder/'events.jsonl').open('a') as handle:
            handle.write(json.dumps(value) + '\n')


class ProbeAPI(RevisedAPI):
    def __init__(self, recorder, payload, metadata, image_count):
        self.template = payload
        self.metadata = metadata
        self.image_count = image_count
        self.profile = 'offline_visual_probe_' + metadata['condition']
        super().__init__({}, recorder.log, 'jev')

    revise = staticmethod(deepcopy)

    def build_payload(self, sent):
        payload = convert_request(sent)
        content = deepcopy(self.template)
        content[0]['text'] = payload['input']
        payload['input'] = [dict(role='user', content=content)]
        english(payload)
        return payload

    def validate_payload(self, payload):
        assert payload['model'] == MODEL
        content = payload['input'][0]['content']
        assert sum(p['type'] == 'input_image' for p in content) == self.image_count

    def input_audit(self):
        return self.metadata


def axis_images(content, dispatch, output):
    """Goal-independent ruler: only public measured EEF, current K/T and RGB."""
    import numpy as np
    from PIL import Image, ImageDraw
    output.mkdir()
    origin = np.asarray(dispatch['measured_robot']['robot0_eef_pos'], float)
    images = [item for item in content if item['type'] == 'input_image']
    records = []
    for image, view in zip(images, dispatch['camera_views']):
        picture = Image.open(io.BytesIO(base64.b64decode(image['image_url'].split(',',1)[1]))).convert('RGB')
        draw = ImageDraw.Draw(picture)
        W = np.linalg.inv(np.asarray(view['camera_to_world'], float))
        K = np.asarray(view['K'], float)

        def project(point):
            p = W @ np.r_[point, 1.]
            if p[2] <= 0:
                return None
            uv = K @ p[:3]
            u, v = uv[:2] / uv[2]
            return (float(u), float(v)) if 0 <= u < picture.width and 0 <= v < picture.height else None

        start = project(origin)
        flags = {}
        for i, (axis, color) in enumerate(zip('XYZ', ('#ff5555', '#44ff66', '#5599ff'))):
            end = project(origin + np.eye(3)[i] * .05)
            visible = start is not None and end is not None
            if visible:
                delta = np.asarray(end)-np.asarray(start)
                length = float(np.linalg.norm(delta))
                visible = length >= 2
                if visible:
                    normal = np.array([-delta[1], delta[0]]) / length
                    unit = delta / length
                    draw.line((start, end), fill=color, width=3)
                    a = np.asarray(end)-unit*7+normal*3
                    b = np.asarray(end)-unit*7-normal*3
                    draw.polygon([end, tuple(a), tuple(b)], fill=color)
                    draw.text((end[0]+3, end[1]-10), '+'+axis, fill=color, stroke_width=1, stroke_fill='black')
            flags[axis] = visible
        buffer = io.BytesIO()
        picture.save(buffer, format='PNG')
        raw = buffer.getvalue()
        path = output/(view['camera']+'.png')
        path.write_bytes(raw)
        image['image_url'] = 'data:image/png;base64,'+base64.b64encode(raw).decode()
        records.append(dict(camera=view['camera'], image_path=str(path),
            sha256=hashlib.sha256(raw).hexdigest(), visible_ruler_axes=flags,
            ruler_source='Public measured EEF and current K/T only; fixed0.05m positive axes'))
    return records


def selected_cases(root):
    for case in sorted(root.glob('task-*-init-*')):
        for directory in sorted((case/'multimodal/decision-api').glob('[0-9]*')):
            required = ['legacy-request.json', 'revised-legacy-request.json', 'response.json', 'request.json']
            if not all((directory/name).exists() for name in required):
                continue
            original = json.loads((directory/'legacy-request.json').read_text())
            expected = reference(original)
            if not any(v != 'hold' for v in expected.values()):
                continue
            yield case, directory, expected
            break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--waypoint-root', type=Path, required=True)
    parser.add_argument('--raw-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for family, root in [('waypoint', args.waypoint_root), ('raw', args.raw_root)]:
        selected = list(selected_cases(root))
        if len(selected) != 30:
            raise ValueError('Exactly one deterministic nonzero-error observation per30 episodes required')
        for case, source, expected in selected:
            payload = json.loads((source/'request.json').read_text())
            dispatch = json.loads((source/'dispatch.json').read_text())
            revised = json.loads((source/'revised-legacy-request.json').read_text())
            for condition in (['marker_base', 'marker_ruler'] if family == 'waypoint' else ['raw_no_images']):
                folder = args.output/condition/case.name
                content = deepcopy(payload['input'][0]['content'])
                legacy = deepcopy(revised)
                metadata = dict(condition=condition, source=str(source), native_execution=False,
                    selection='First received decision with any nominal nonzero XYZ error; same rule for every episode')
                if family == 'waypoint':
                    # The same wording in both probes isolates ruler pixels.
                    content.append(dict(type='input_text', text=CAPTION))
                    for axis in 'xyz':
                        if axis in legacy['questions']:
                            legacy['questions'][axis]['instructions'] = QUESTION.format(axis=axis.upper())
                    if condition == 'marker_ruler':
                        metadata['ruler_images'] = axis_images(content, dispatch, args.output/('ruler-'+case.name))
                        context = json.loads(content[1]['text'])
                        for view, image in zip(context['camera_views'], metadata['ruler_images']):
                            view['rgb_path'] = image['image_path']
                            view['sha256'] = image['sha256']
                            view['visible_ruler_axes'] = image['visible_ruler_axes']
                        content[1]['text'] = json.dumps(context)
                    image_count = 2
                else:
                    context = json.loads(content[1]['text'])
                    for view in context['camera_views']:
                        for key in ('rgb_path', 'sha256', 'original_rgb_path'):
                            view.pop(key, None)
                    context['timing'] = 'Saved observation used for a read-only text-only probe. No images are attached and no robot action will execute.'
                    context['interpretation'] = 'Camera calibration is metadata only; current image content is not available in this probe.'
                    content = [content[0], dict(type='input_text', text=json.dumps(context))]
                    image_count = 0
                recorder = Recorder(folder)
                api = ProbeAPI(recorder, content, metadata, image_count)
                try:
                    response = api.post('/systemone', legacy)
                    choices = {axis: response['answers'][axis]['choice'] for axis in expected if axis in response['answers']}
                    score = dict(correct=sum(choices.get(a) == v for a,v in expected.items()), total=len(expected),
                        nonzero_correct=sum(choices.get(a) == v for a,v in expected.items() if v != 'hold'),
                        nonzero_total=sum(v != 'hold' for v in expected.values()))
                    baseline = json.loads((source/'legacy-response.json').read_text())
                    baseline_choices = {a: baseline['answers'][a]['choice'] for a in expected}
                    result = dict(condition=condition, episode=case.name, source=str(source),
                        expected_nominal=expected, choices=choices, score=score, source_choices=baseline_choices)
                except Exception as error:
                    result = dict(condition=condition, episode=case.name, source=str(source),
                        error_type=type(error).__name__, error=str(error).replace(api.credential, '[redacted]')[:500])
                save(folder/'probe-result.json', result)
                results.append(result)
                print(json.dumps(result), flush=True)
    summary = dict(probes=len(results), native_episodes=0, results=results)
    save(args.output/'summary.json', summary)
    return 0


if __name__ == '__main__':
    sys.exit(main())
