"""Read-only campaign identity audit; never print credentials or model inputs."""
import collections
import hashlib
import json
from pathlib import Path

ROOT = Path('/root/yekangjie/project/jev_rsi/.worktrees/robodojo-planner-advancer-20261018')
ASSETS = ROOT / 'code/runs/company2-20261018'
rows = []
for episode in sorted(ASSETS.glob('*/*/episode')):
    requests = sorted((episode / 'decisions').glob('*/request.json'))
    if not requests:
        continue
    request_models, response_models, response_shapes = (collections.Counter() for _ in range(3))
    efforts, image_counts = collections.Counter(), collections.Counter()
    errors = []
    for request in requests:
        try:
            data = json.loads(request.read_text())
            request_models[str(data.get('model'))] += 1
            efforts[str(data.get('reasoning', {}).get('effort'))] += 1
            image_counts[str(len(data.get('images', {})))] += 1
            response = request.parent / 'response.json'
            if response.exists():
                raw = json.loads(response.read_text())
                response_models[str(raw.get('model'))] += 1
                shape = ('responses_object' if raw.get('object') == 'response' else
                         'typed_answers' if 'answers' in raw else 'other')
                response_shapes[shape] += 1
        except (ValueError, TypeError, AttributeError) as exc:
            errors.append({'file': str(request.relative_to(ASSETS)), 'error_type': type(exc).__name__})
    snapshot = episode.parent / 'framework_source/code/planner_advancer/models.py'
    source = snapshot.read_text() if snapshot.exists() else ''
    native = episode / 'native/evaluation_outcome.json'
    outcome = json.loads(native.read_text()) if native.exists() else {}
    rows.append(dict(run=str(episode.parent.relative_to(ASSETS)), requests=len(requests),
        request_models=dict(request_models), response_models=dict(response_models),
        response_shapes=dict(response_shapes), reasoning_efforts=dict(efforts),
        image_counts=dict(image_counts), first_request=str(requests[0].relative_to(ASSETS)),
        last_request=str(requests[-1].relative_to(ASSETS)),
        launch_source_path=str(snapshot.relative_to(ASSETS)) if snapshot.exists() else None,
        launch_source_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest() if snapshot.exists() else None,
        launch_source_responses_endpoint='/responses' in source,
        launch_source_decisions_endpoint='/v1/decisions' in source,
        native={key: outcome.get(key) for key in ('complete','native_success','native_score','native_control_steps')},
        errors=errors))
summary = collections.Counter()
for row in rows:
    summary.update(row['request_models'])
print(json.dumps(dict(scope='Actual retained requests/responses and launch snapshots; no inference calls. No prompts or credentials read into output.',
    root=str(ASSETS), runs=len(rows), request_model_totals=dict(summary), episodes=rows), indent=2))
