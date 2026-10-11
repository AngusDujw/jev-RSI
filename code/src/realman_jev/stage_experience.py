"""Planner-only evidence of completed substages, including failed whole episodes."""
import json
import gzip
import math
from copy import deepcopy
from pathlib import Path


def executed_example(record, campaign):
    """Compact a native-positive example around measured executed contracts."""
    source=Path(record['source']).resolve()
    if not source.is_relative_to(Path(campaign).resolve()):
        raise ValueError('Executed experience source escapes the campaign')
    contracts=source/'policy/completed-stage-contracts.json'
    if not contracts.exists():
        return deepcopy(record)  # Do not guess which historical contracts ran.
    example=deepcopy(record)
    configuration=source/'config.json'
    if configuration.exists():
        cfg=json.loads(configuration.read_text())
        example['execution_protocol']={key:cfg.get(key) for key in (
            'step_m','angle_rad','joint_step_rad','ticks_per_action','magnitude_mode',
            'gripper_settle_actions','gripper_settle_epsilon','jev_state_representation',
            'planning_horizon','goal_regression_actions')}
        example['execution_protocol']['interpretation']='These global defaults governed this measured episode. Stage overrides take precedence; an omitted stage cap inherited these defaults. Adapt the design to current observations and the current action contract rather than replaying historical actions.'
    result_path=source/'result.json'
    if result_path.exists():
        outcome=json.loads(result_path.read_text())
        example['measured_episode_budget']=dict(native_steps=outcome.get('native_steps'),
            native_step_limit=(outcome.get('native_evaluation') or {}).get('native_step_limit'),
            full_planning_rounds=outcome.get('full_planning_rounds'),
            budget_reviews=outcome.get('budget_reviews'))
    from .stage_ir import Stage
    def compact(contract):
        return Stage.model_validate(contract).model_dump(exclude_defaults=True)
    example['executed_stages']=[]
    for endpoint in json.loads(contracts.read_text()):
        # Expressions/thresholds already live in the contract; retain their
        # measured values and ordering without repeating descriptions twice.
        example['executed_stages'].append(dict(id=endpoint['id'],native_tick=endpoint['native_tick'],
            actions=endpoint['actions'],contract=compact(endpoint['contract']),
            measured_checks=[dict(index=i,value=check['value'],satisfied=check['satisfied'])
                             for i,check in enumerate(endpoint['measured_checks'])]))
    example['planning_decisions']=[p['reasoning'] for p in example.pop('plans')]
    events=source/'policy/events.jsonl'
    compressed=events.with_suffix(events.suffix+'.gz')
    opener=(lambda:gzip.open(compressed,'rt')) if compressed.exists() else events.open
    plans=[json.loads(path.read_text())['stages']
           for path in sorted((source/'policy').glob('plan-??.json'))]
    last=None
    stage_runs=[]
    decisions={}
    handoff=0
    if events.exists() or compressed.exists():
        with opener() as stream:
            for line in stream:
                event=json.loads(line)
                kind=event.get('kind')
                if kind=='decision':
                    decisions[event['decision']]=(event.get('stage'),event.get('stage_id'))
                elif kind=='execution':
                    last=event
                    stage_index,stage_id=decisions.get(event['decision'],(None,None))
                    if stage_id!=event.get('stage') or type(stage_index) is not int:
                        continue
                    key=(handoff,stage_index,stage_id)
                    if not stage_runs or stage_runs[-1]['_key']!=key:
                        stage_runs.append(dict(_key=key,id=stage_id,
                                               first_native_tick=event['tick'],
                                               last_native_tick=event['tick'],
                                               physical_actions=0))
                    stage_runs[-1]['physical_actions']+=1
                    stage_runs[-1]['last_native_tick']=event['tick']
                elif kind in ('stage_failed','stage_planner_handoff'):
                    handoff+=1
    completed_ids={stage['id'] for stage in example['executed_stages']}
    revision=0
    previous_index=-1
    timeline=[]
    for run_index,run in enumerate(stage_runs):
        _,stage_index,stage_id=run.pop('_key')
        if stage_index<=previous_index:
            revision+=1
        while revision<len(plans) and (stage_index>=len(plans[revision])
                                       or plans[revision][stage_index]['id']!=stage_id):
            revision+=1
        run['source_plan_revision']=revision+1 if revision<len(plans) else None
        run['measured_endpoint_recorded']=stage_id in completed_ids
        terminal_run=run_index==len(stage_runs)-1 and last is not None and stage_id==last['stage']
        if terminal_run:
            run['evidence_level']='native_terminal_action_stage'
        elif revision<len(plans) and stage_id not in completed_ids:
            run['contract']=compact(plans[revision][stage_index])
            run['evidence_level']='physically_executed_without_recorded_stage_endpoint'
        timeline.append(run)
        previous_index=stage_index
    example['physical_execution_timeline']=timeline
    if last:
        matches=[s for p in reversed(record['plans']) for s in p['stages'] if s['id']==last['stage']]
        if matches:
            example['native_terminal_action_stage']=dict(contract=compact(matches[0]),native_tick=last['tick'],
                interpretation='Last physically executed stage before independent native success; stage endpoint may not have been separately recorded.')
    example['interpretation']='The physical_execution_timeline preserves the order and action counts of stages that actually sent native actions. Its contracts without recorded endpoints are lower-grade evidence even though the whole historical episode succeeded. Abandoned unexecuted suffixes are omitted. Re-ground all designs from current measurements; no historical motor trace is automatically replayed.'
    return example


def planner_examples(records, task, layout_sha256, mode='mixed', campaign=None):
    """Retrieve model-authored evidence; never choose or execute motor stages."""
    if mode not in ('mixed','validated_first','executed_first','efficient_executed','matched_executed','matched_recent_executed'):
        raise ValueError('Unknown planner experience mode')
    relevant=[r for r in records if r['task']==task]
    positives=[r for r in relevant if r['verified_native_success']]
    if mode in ('efficient_executed','matched_executed','matched_recent_executed'):
        if campaign is None:raise ValueError('Efficient experience requires its campaign')
        positions={id(record):i for i,record in enumerate(positives)}
        def efficiency(record):
            source=Path(record['source']).resolve()
            if not source.is_relative_to(Path(campaign).resolve()):
                raise ValueError('Experience result source escapes the campaign')
            result=source/'result.json'
            outcome=json.loads(result.read_text()) if result.exists() else {}
            native=outcome.get('native_evaluation',{})
            steps=outcome.get('native_steps');limit=native.get('native_step_limit')
            verified=native.get('valid_for_success_rate') is True and native.get('native_success') is True
            fraction=steps/limit if verified and type(steps) in (int,float) and type(limit) in (int,float) and limit>0 else 2.
            if not math.isfinite(fraction) or fraction<0 or fraction>1:fraction=2.
            return fraction,len(record['plans']),-positions[id(record)]
        matching=sorted((r for r in positives if r['layout_sha256']==layout_sha256),key=efficiency)
        other=sorted((r for r in positives if r['layout_sha256']!=layout_sha256),key=efficiency)
        if mode=='matched_recent_executed':
            pool=matching if matching else other
            selected=[max(pool,key=lambda record:positions[id(record)])] if pool else []
        elif mode=='matched_executed' and matching:
            selected=matching[:1]
        else:
            selected=other[:1]+matching[:1] if matching and other else sorted(positives,key=efficiency)[:2]
    elif mode in ('validated_first','executed_first'):
        matching=[r for r in positives if r['layout_sha256']==layout_sha256]
        other=[r for r in positives if r['layout_sha256']!=layout_sha256]
        selected=other[-1:]+matching[-1:] if matching and other else positives[-2:]
    else:
        selected=positives[-2:]
    failed=[r for r in relevant if not r['verified_native_success']][-1:]
    examples=deepcopy(selected)
    if mode in ('executed_first','efficient_executed','matched_executed','matched_recent_executed'):
        if campaign is None:raise ValueError('Executed experience requires its campaign')
        examples=[executed_example(r,campaign) for r in selected]
    for record in failed:
        example=deepcopy(record)
        if mode in ('validated_first','executed_first','efficient_executed','matched_executed','matched_recent_executed') and positives:
            # Old failed objectives are hypotheses, even if one endpoint passed.
            # Preserve observed failure diagnostics without teaching their whole
            # strategy or old scene poses alongside a validated whole episode.
            example={k:example[k] for k in ('task','layout_sha256','verified_native_success',
                'status','failure_events','source','observation') if k in example}
            example['interpretation']='Failure diagnostics only; this episode did not validate a strategy.'
        else:
            example['failed_strategy_summaries']=[dict(reasoning=p['reasoning'],
                objectives=[dict(id=s['id'],objective=s['objective']) for s in p['stages']])
                for p in example.pop('plans')]
        examples.append(example)
    for example in examples:
        example['same_frozen_layout']=example.get('layout_sha256')==layout_sha256
        example['scene_match_interpretation']='Equality of the frozen asset/layout SHA256 only; not proof of current capture, identical physical trajectory, or unseen-scene generalization.'
    return examples,bool(positives),relevant


def partial_progress(record, campaign):
    source = Path(record['source']).resolve()
    if not source.is_relative_to(Path(campaign).resolve()):
        return []
    policy = source/'policy'
    explicit = policy/'completed-stage-contracts.json'
    if explicit.exists():
        return json.loads(explicit.read_text())
    history = policy/'completed-stage-history.json'
    if not history.exists():
        return []
    if any(policy.glob('budget-review-response-*.json')):
        return []
    # Historical trials predate budget reviews, so revision-1 identifies their
    # exact GPT plan. Do not guess for revisions without a matching plan file.
    result = []
    for endpoint in json.loads(history.read_text()):
        plan = policy/f'plan-{endpoint["revision"]-1:02d}.json'
        if not plan.exists():
            continue
        matches = [s for s in json.loads(plan.read_text())['stages'] if s['id']==endpoint['id']]
        if len(matches)==1:
            result.append(dict(**endpoint,contract=matches[0]))
    return result


def useful_partial_examples(records, campaign, limit=2):
    candidates = []
    for record in records:
        if record['verified_native_success']:
            continue
        endpoints = partial_progress(record,campaign)
        if endpoints:
            score = sum(bool(e['measured_checks']) for e in endpoints)
            candidates.append((score,len(endpoints),record,endpoints))
    candidates.sort(key=lambda item:item[:2],reverse=True)
    return [dict(source=record['source'],layout_sha256=record['layout_sha256'],
        whole_episode_native_success=False,measured_substage_endpoints=endpoints,
        interpretation='These GPT-generated substages reached their recorded measured conditions. They do NOT prove whole-task success, universal grasp validity, or current-scene applicability. Closure/pose-only stages do not prove capture. Re-plan using CURRENT evidence; do not execute these as a fixed expert.')
        for _,_,record,endpoints in candidates[:limit]]
