"""GPT-generated relational plans -> official Jev choices -> bounded native steps."""
from __future__ import annotations
import argparse
from copy import deepcopy
import fcntl
import gzip
import json
import re
from pathlib import Path
import time
from types import SimpleNamespace
import httpx
import numpy as np
from scipy.spatial.transform import Rotation
from .api import API
from .runtime import Log
from .stage_network import api_dns_overrides
from .decision_client import DECISION_PROMPT, add_visual_question, prepare, validate
from .experience_notes import load_notes
from .stage_prompts import LEGACY_V11_PROMPT
from .stage_prompts_vision import VISION_V1_PROMPT
from .stage_prompts_vision_method import VISION_METHOD_V1_PROMPT
from .stage_prompts_adaptive import LEGACY_V11_ADAPTIVE_PROMPT, LEGACY_V11_PROTECTED_PROMPT, LEGACY_V11_COMPLIANT_PROMPT, LEGACY_V11_MEASURED_REUSE_PROMPT, LEGACY_V11_RETENTION_PROMPT, LEGACY_V11_CONDITIONAL_REUSE_PROMPT, LEGACY_V11_CONTACT_PROGRESS_PROMPT, LEGACY_V11_TASK_FRAME_PROGRESS_PROMPT, LEGACY_V11_ANCHORED_APPROACH_PROMPT
from .stage_ir import StagePlan, StageBudgetReview, GoalMonitor, PROMPT, COMPACT_PROMPT, BUDGET_PROMPT, compile_stage, endpoint_unmet, limit_translation_speed, task_checks, task_progress, variables, motor_questions, canonical_motor_state, rot, visual_checks
from .stage_ir import stage_prerequisites


ENTRY_CONTRACT_INSTRUCTION = '''For EVERY Stage or StageReference, explicitly
provide requires_acceptance_indices, a list of distinct indices into YOUR current
task_acceptance contract, or [] when no final relation is required at entry.
These are measured ENTRY requirements, not effects expected after that stage.
Before final robot withdrawal/home or other closing operations that assume task
geometry is finished, require the relevant object/operation acceptance relations.
Do not require future robot home/open conditions before the action that creates
them. Necessary intermediate deformation or repairs may have different entry
dependencies; YOU declare them. The runtime checks these measurements before
the stage sends any motor action. A false prerequisite sends evidence back to
you; it does not become true because a narrative says it is complete. Reuse a
compatible acceptance contract and compare its indexed measured values explicitly.
No dependency or repair direction is inferred by task name or by the runtime.'''


def inference(method, log, *args):
    """Retry transient inference transport errors before any physical mutation."""
    setting=getattr(getattr(method,'__self__',None),'cfg',{})
    recovery_s=setting.get('transport_recovery_s',0)
    if not isinstance(recovery_s,(int,float)) or isinstance(recovery_s,bool) or recovery_s < 0:
        raise ValueError('transport_recovery_s must be a nonnegative number')
    deadline=None
    attempt=0
    while True:
        try:
            with api_dns_overrides([setting]):
                return method(*args)
        except (httpx.RequestError, RuntimeError) as exc:
            transient = isinstance(exc, httpx.RequestError) or any(
                'HTTP '+str(code) in str(exc) for code in (429,500,502,503,504,520,522,524,529))
            transient |= str(exc)=='Responses stream ended without completion' or (
                str(exc).startswith('Responses stream failed/incomplete:') and any(
                    text in str(exc).lower() for text in ('stream was interrupted','http/2 stream failed','connection reset')))
            if not transient or (not recovery_s and attempt >= 2):
                raise
            if recovery_s and deadline is None:
                deadline=time.monotonic()+recovery_s
            remaining=deadline-time.monotonic() if deadline is not None else None
            if remaining is not None and remaining <= 0:
                raise
            delay=min(10,2*(attempt+1))
            if remaining is not None:
                delay=min(delay,remaining)
            log(dict(kind='inference_transport_retry', attempt=attempt+1,
                     wait_s=round(delay,3), error_type=type(exc).__name__,
                     physical_action_sent=False))
            time.sleep(delay)
            attempt += 1


def run(args):
    from hybrid_rollout.robodojo.robodojo_server.protocol import RPCClient
    cfg = json.loads(Path(args.config).read_text())
    observation_mode = cfg.get('observation_mode', 'oracle')
    if observation_mode != 'vision':
        raise ValueError('This campaign accepts sensor-only vision observations')
    if observation_mode == 'vision' and cfg.get('track_material_points', False):
        raise ValueError('RGB vision cannot access simulator material vertices')
    prompt_mode=cfg.get('planner_prompt_mode','full')
    planner_prompts={'full':PROMPT,'compact_contract':COMPACT_PROMPT,
                    'vision_v1':VISION_V1_PROMPT,
                    'vision_method_v1':VISION_METHOD_V1_PROMPT,
                    'legacy_v11':LEGACY_V11_PROMPT,
                    'legacy_v11_adaptive':LEGACY_V11_ADAPTIVE_PROMPT,
                    'legacy_v11_protected':LEGACY_V11_PROTECTED_PROMPT,
                    'legacy_v11_compliant':LEGACY_V11_COMPLIANT_PROMPT,
                    'legacy_v11_measured_reuse':LEGACY_V11_MEASURED_REUSE_PROMPT,
                    'legacy_v11_retention':LEGACY_V11_RETENTION_PROMPT,
                    'legacy_v11_conditional_reuse':LEGACY_V11_CONDITIONAL_REUSE_PROMPT,
                    'legacy_v11_contact_progress':LEGACY_V11_CONTACT_PROGRESS_PROMPT,
                    'legacy_v11_task_frame_progress':LEGACY_V11_TASK_FRAME_PROGRESS_PROMPT,
                    'legacy_v11_anchored_approach':LEGACY_V11_ANCHORED_APPROACH_PROMPT}
    if prompt_mode not in planner_prompts:
        raise ValueError('Unknown planner prompt mode')
    if prompt_mode == 'vision_method_v1' and observation_mode != 'vision':
        raise ValueError('vision_method_v1 requires vision observation mode')
    planner_prompt=(planner_prompts[prompt_mode]
        .replace('TypeSafe Jev', 'OpenAI GPT decision model')
        .replace('Official Jev', 'OpenAI GPT decision model')
        .replace('Jev', 'GPT decision model'))
    case = json.loads(Path(args.case).read_text())
    log = Log(args.output)
    notes = load_notes(cfg['experience_notes_root'], case['task'])
    api_cfg = json.loads(Path(args.api_config).read_text())
    if (api_cfg['gpt']['model'] != 'gpt-6.1-sol' or
            api_cfg['gpt'].get('reasoning_effort') != 'high' or
            api_cfg['decision']['model'] != 'gpt-6-luna'):
        raise ValueError('Planner and decision models do not match the frozen campaign')
    (log.folder/'runtime-protocol.json').write_text(json.dumps(dict(
        planner_reasoning_effort=api_cfg['gpt'].get('reasoning_effort'),
        planner_model=api_cfg['gpt']['model'],decision_model=api_cfg['decision']['model'],
        goal_regression_actions=cfg.get('goal_regression_actions',3),
        planning_horizon=cfg.get('planning_horizon'),
        gripper_settle_actions=cfg.get('gripper_settle_actions',0),
        gripper_settle_epsilon=cfg.get('gripper_settle_epsilon',.015),
        unmet_pose_actions=cfg.get('unmet_pose_actions',0),
        track_material_points=cfg.get('track_material_points',False),
        semantic_handoffs=cfg.get('semantic_handoffs',False),
        planner_prompt_mode=prompt_mode,
        api_routes={r:{k:c.get(k) for k in ('base_url','proxy','resolved_host_ip')}
                    for r,c in api_cfg.items() if r in ('gpt','decision')},
        experience_context_mode=cfg.get('experience_context_mode','mixed'),
        compact_catalog_context=cfg.get('compact_catalog_context',False),
        observation_mode=observation_mode),indent=2))
    clients = {role: API(api_cfg[key], log, role) for role, key in
               [('planner', 'gpt'), ('decision', 'decision')]}
    vision = None
    if observation_mode == 'vision':
        from .stage_vision import VisionScene
        clients['vision'] = API(api_cfg['gpt'], log, 'vision')
        vision_cfg = dict(cfg.get('vision', {}))
        vision_cfg['method_plan_enabled'] = prompt_mode == 'vision_method_v1'
        vision = VisionScene(vision_cfg, clients['vision'], log, inference)
    rpc = RPCClient('127.0.0.1', args.port, timeout=cfg.get('rpc_timeout_s',240))
    episode, tick = None, 0
    summary = dict(status='starting', complete=False, physical_success=False, case=case,
                   executor='openai_gpt6_luna_decision', planner=api_cfg['gpt']['model'],
                   observation=observation_mode, decisions=0)
    started = time.monotonic()
    revision, budget_reviews = 0, 0
    def call(op, **kw):
        return rpc.request(op, episode_id=episode, step_id=tick, **kw)
    def observe_stage(decision):
        if vision is None:
            return call('stage_observation', track_material_points=cfg.get('track_material_points',False),
                gripper_commands=grippers, gripper_settled=[n>=max(2,settle_required) for n in settled_actions]), call('teacher_observation')
        obs = call('teacher_observation')
        state = call('vision_stage_state')
        return vision.observe(obs, state, decision), obs
    try:
        reset = rpc.request('reset', seed=case['layout_id'], source='gpt_eef', policy_version='relational_stage_ir_v1')
        episode, tick = reset['episode_id'], reset['step_id']
        meta = reset['metadata']
        if vision is not None:
            vision.cfg['control_dt_s'] = meta['control_dt']
        call('begin_combination', evaluation_method='gpt61_stage_gpt6_luna', observation=observation_mode,
             privileged_object_input=False, human_plan=False,
             pi05_enabled=False, executor='openai_gpt6_luna_decision')
        grippers, settled_actions = [1., 1.], [0, 0]
        settle_required=cfg.get('gripper_settle_actions',0)
        home, _ = observe_stage(-1)
        home = deepcopy(home)
        (log.folder/'initial-features.json').write_text(json.dumps(home, indent=2))
        (log.folder/'planner-prompt.txt').write_text(planner_prompt)
        grippers = [float(home['robot']['states'][i*7+6]) for i in range(2)]
        plan, index, entry, age = None, 0, None, 0
        feedback, history = None, []
        completed_stages, planning_memory = [], []
        completed_contracts = []
        task_acceptance = []
        goal_monitor = None
        stable_ready = 0
        stagnant_actions = 0
        unmet_pose_actions = 0
        hold_stall_actions = 0
        decision_limit = args.max_decisions or meta['max_episode_steps']+80*cfg.get('max_planning_rounds',8)+16
        summary['decision_limit'] = decision_limit
        for decision in range(decision_limit):
            if Path(cfg['stop_file']).exists():
                summary['status'] = 'operator_stop'; break
            if time.monotonic()-started > cfg['timeout_s']:
                summary['status'] = 'wall_time_limit'; break
            evidence, obs = observe_stage(decision)
            try:
                acceptance_evidence = dict(checks=task_checks(task_acceptance,evidence,home))
            except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                acceptance_evidence = dict(checks=[],unavailable=str(exc))
            if plan is None:
                if revision >= cfg.get('max_planning_rounds', 4):
                    summary['status'] = 'recovery_budget_exhausted'; break
                request = dict(instruction=obs['instruction'], variables=variables(evidence),
                    physical_features=evidence, initial_robot=home['robot'], feedback=feedback, recent=history[-4:],
                    completed_stages=completed_stages,
                    prior_planning_memory=[dict(reasoning=memory['reasoning'][:1200],
                        stage_objectives=memory['stage_objectives']) for memory in planning_memory[-2:]],
                    native_step_limit=meta['max_episode_steps'], remaining_steps=meta['max_episode_steps']-tick,
                    action_contract=dict(translation_step_m=cfg['step_m'], rotation_step_rad=cfg['angle_rad'],
                                         expression_functions=['abs','min','max','sqrt','hypot'],literal_square_supported=True,
                                         per_stage_translation_cap_m_range=[.002,.025],
                                         per_stage_translation_speed_m_per_s_range=[.03,.8],native_control_dt_s=meta['control_dt'],
                                         cartesian_ik_translation_error_norm_cap_m=.02,
                                         cartesian_ik_rotation_error_norm_cap_rad=.1,
                                         cartesian_ik_joint_proposal_delta_cap_rad=.05,
                                         solver_caps_provenance='Pinned RoboDojo RPC ArmFK.bounded_target; direct joint-reference actions use the configured joint_step_rad instead.',
                                         joint_step_rad=cfg.get('joint_step_rad', .06), ticks_per_action=cfg['ticks_per_action'],
                                         gripper_settle_actions=settle_required,
                                         gripper_settle_epsilon=cfg.get('gripper_settle_epsilon',.015),
                                         unmet_pose_actions=cfg.get('unmet_pose_actions',0),
                                         magnitude_mode=cfg.get('magnitude_mode', 'fixed')))
                request.update(task_acceptance_contract=[p.model_dump() for p in task_acceptance],
                               task_acceptance_measurements=acceptance_evidence)
                if (task_acceptance and isinstance(feedback,dict) and
                        isinstance(feedback.get('entry'),dict) and 'checks' in acceptance_evidence):
                    try:
                        request['task_acceptance_progress_since_stage_entry'] = task_progress(
                            task_checks(task_acceptance,feedback['entry'],home),
                            acceptance_evidence['checks'])
                    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                        request['task_acceptance_progress_unavailable'] = str(exc)
                catalog = {}
                plan_schema = StagePlan.model_json_schema()
                request['planning_contract']=dict(max_stages=cfg.get('planning_horizon'),
                    remaining_full_planning_rounds=cfg.get('max_planning_rounds',8)-revision,
                    mode='milestone_handoffs' if cfg.get('semantic_handoffs') else
                         'receding_stages' if cfg.get('planning_horizon') else 'whole_remaining_plan')
                if prompt_mode == 'vision_method_v1':
                    request['planning_contract']['max_observe_after_handoffs'] = 3
                    stage_schema = plan_schema['$defs']['Stage']
                    stage_schema['required'] = list(dict.fromkeys(
                        [*stage_schema['required'], 'purpose']))
                    stage_schema['properties']['purpose'].pop('default', None)
                specs = json.loads(Path(cfg['task_specs']).read_text()) if cfg.get('task_specs') else {}
                request['public_task_acceptance'] = specs.get(case['task'], obs['instruction'])
                request['acceptance_provenance'] = specs.get('source', 'task instruction')
                request['reviewed_experience'] = notes
                request['experience_usage_rule'] = ('Use prior failures as hypotheses about sensing, contact, and stage design; '
                    're-ground every entity in current camera images and robot state. No historical pose is a current observation.')
                bank = Path(cfg.get('experience_bank_path', str(Path(cfg['campaign'])/'experience.jsonl')))
                if bank.exists():
                    with (bank.parent/'ledger.lock').open('a') as lock:
                        fcntl.flock(lock, fcntl.LOCK_SH)
                        records = [row for line in bank.read_text().splitlines()
                                   if (row := json.loads(line)).get('observation') == 'vision']
                    from .stage_experience import planner_examples
                    experience_mode=cfg.get('experience_context_mode','mixed')
                    request['prior_experience'],has_success,examples=planner_examples(
                        records,case['task'],case['layout_sha256'],experience_mode,cfg['campaign'])
                    request['experience_context_mode']=experience_mode
                    request['experience_instruction'] = 'Native-positive examples independently passed their original evaluator in the recorded scene; they are not proof of current capture or universal reliability. same_frozen_layout explicitly identifies an asset/layout match, not a capture or success label for this episode. physical_execution_timeline records only stages that sent native actions, in order; measured_endpoint_recorded distinguishes completed stage contracts from lower-grade physically executed contracts without endpoint proof. Re-ground compatible designs using CURRENT bindings, geometry and measurements, retaining what fits rather than inventing replacements without evidence. Compare their execution_protocol with the current action_contract; omitted historical stage caps inherited historical defaults, so preserve or explicitly justify adaptations to those effective increments. Historical warnings refer to their earlier failures, not automatically to later validated designs. Explain necessary adaptations. Never copy mismatched absolute poses or treat a failed strategy as validated; the framework does not automatically replay a motor trace.'
                    if cfg.get('partial_stage_experience', False) and not (experience_mode in ('validated_first','executed_first','efficient_executed','matched_executed','matched_recent_executed') and has_success):
                        from .stage_experience import useful_partial_examples
                        request['partial_stage_experience'] = useful_partial_examples(examples,cfg['campaign'])
                if cfg.get('stage_contract_reuse', False):
                    from .stage_catalog import attach_catalog, catalog_schema, CATALOG_INSTRUCTION
                    request['prior_experience'], catalog = attach_catalog(
                        request.get('prior_experience', []),
                        compact_context=cfg.get('compact_catalog_context', False))
                    plan_schema = catalog_schema(catalog)
                    request['contract_reuse_instruction'] = CATALOG_INSTRUCTION
                if cfg.get('stage_entry_contracts', False):
                    request['stage_entry_contract_instruction'] = ENTRY_CONTRACT_INSTRUCTION
                    for name in ('Stage', 'StageReference'):
                        definition=plan_schema.get('$defs',{}).get(name)
                        if definition is not None:
                            definition.setdefault('required',[]).append('requires_acceptance_indices')
                cached = Path(cfg['reviewed_plan']) if revision == 0 and cfg.get('reviewed_plan') else None
                if vision is not None:
                    request['historical_visual_references'] = [dict(
                        image='reference_'+identity, visual_id=identity,
                        meaning='historical RGB crop, never a current camera view')
                        for identity in sorted(vision.visually_mobile)
                        if identity in vision.reference_crops][:3]
                    if vision.method is not None:
                        request['visual_method'] = vision.method.model_dump()
                        request['visual_method_provenance'] = 'live GPT design from public instruction and first RGB frames; no object truth'
                (log.folder/f'planner-input-{revision:02d}.json').write_text(json.dumps(request, indent=2))
                cameras = {k: SimpleNamespace(rgb=obs[k]) for k in ('cam_high', 'cam_left_wrist', 'cam_right_wrist') if k in obs}
                if vision is not None:
                    for reference in request['historical_visual_references']:
                        cameras[reference['image']] = SimpleNamespace(
                            rgb=vision.reference_crops[reference['visual_id']])
                if cached:
                    source_case = json.loads((cached.parent.parent/'case.json').read_text())
                    event_path=cached.parent/'events.jsonl'
                    compressed=event_path.with_suffix(event_path.suffix+'.gz')
                    with (gzip.open(compressed,'rt') if compressed.exists() else event_path.open()) as stream:
                        events = [json.loads(line) for line in stream]
                    expected_planner = api_cfg['gpt'].get('expected_model_prefix', api_cfg['gpt']['model'])
                    if source_case['layout_sha256'] != case['layout_sha256'] or not any(
                            e.get('kind') == 'api' and e.get('role') == 'planner' and
                            str(e.get('model','')).startswith(expected_planner) for e in events):
                        raise ValueError('Precomputed plan lacks matching scene or genuine GPT-6 provenance')
                    raw_plan = json.loads(cached.read_text())
                    summary['precomputed_gpt_plan'] = str(cached)
                    log(dict(kind='precomputed_gpt_plan', source=str(cached), actual_new_gpt_call=False))
                else:
                    raw_plan = inference(clients['planner'].chat, log, planner_prompt, request, cameras, plan_schema)
                (log.folder/f'planner-response-{revision:02d}.json').write_text(json.dumps(raw_plan, indent=2))
                try:
                    if cfg.get('stage_entry_contracts', False) and (
                            not isinstance(raw_plan,dict) or
                            not isinstance(raw_plan.get('stages'),list) or any(
                                not isinstance(s,dict) or 'requires_acceptance_indices' not in s or
                                not isinstance(s['requires_acceptance_indices'],list)
                                for s in raw_plan['stages'])):
                        raise ValueError('Every stage must explicitly declare requires_acceptance_indices as a list')
                    references = []
                    if cfg.get('stage_contract_reuse', False):
                        from .stage_catalog import expand_catalog_plan
                        candidate, references = expand_catalog_plan(raw_plan, catalog, request['variables']['o'])
                    else:
                        candidate = StagePlan.model_validate(raw_plan)
                    if cfg.get('planning_horizon') and len(candidate.stages)>cfg['planning_horizon']:
                        raise ValueError('Plan exceeds the configured receding stage horizon')
                    if cfg.get('semantic_handoffs') and (
                            not candidate.stages[-1].observe_after or any(s.observe_after for s in candidate.stages[:-1])):
                        raise ValueError('Emit only the executable prefix through ONE next measured milestone, with observe_after=true on its final stage')
                    if prompt_mode == 'vision_method_v1':
                        if any(not isinstance(raw_stage, dict) or 'purpose' not in raw_stage
                               for raw_stage in raw_plan['stages']):
                            raise ValueError('Every vision-method stage must explicitly declare purpose=sense or purpose=manipulate')
                        handoffs = sum(stage.observe_after for stage in candidate.stages)
                        if handoffs > 3:
                            raise ValueError(f'Plan declares {handoffs} GPT handoffs; maximum is 3 because RGB tracking runs every decision')
                        declared = set(vision.method_by_id)
                        for stage in candidate.stages:
                            if stage.purpose == 'sense':
                                if any(goal.gripper == 'close' or any(
                                        re.search(r'(?:now|entry|home)\.o\.v_[a-z][a-z0-9_]*', target)
                                        for target in goal.target)
                                        for goal in stage.arms.values()):
                                    raise ValueError(f'Sensing stage {stage.id!r} must move only to a robot-state waypoint without closing fingers')
                            required = {r.id for r in stage.visual_requirements}
                            if not required <= declared:
                                raise ValueError(f'Stage {stage.id!r} requires an undeclared visual entity')
                            mentioned = set(re.findall(
                                r'(?:now|entry|home)\.o\.(v_[a-z][a-z0-9_]*)',
                                stage.model_dump_json()))
                            if not mentioned <= required:
                                raise ValueError(f'Stage {stage.id!r} omits visual_requirements for {sorted(mentioned-required)}')
                            for requirement in stage.visual_requirements:
                                if requirement.quality != 'last_stereo_bounded':
                                    continue
                                predicates = [p.expression for p in stage.completion+stage.abort]
                                if any(re.search(r'(?:now|entry|home)\.o\.'+re.escape(requirement.id)+r'(?:\.|\b)', expression)
                                       for expression in predicates):
                                    raise ValueError(f'Stage {stage.id!r} cannot use stale stereo to prove an object predicate')
                    # Check every expression and frame against available fields before moving.
                    for stage in candidate.stages:
                        try:
                            compile_stage(stage, evidence, evidence, home, 0)
                        except (ValueError, KeyError, TypeError, ArithmeticError, SyntaxError, RecursionError) as exc:
                            raise ValueError(f'Stage {stage.id!r}: {exc}') from exc
                    candidate_acceptance=candidate.task_acceptance or task_acceptance
                    for stage in candidate.stages:
                        stage_prerequisites(stage,candidate_acceptance,evidence,home)
                    candidate_monitor=GoalMonitor(candidate.protection_groups,
                        task_checks(candidate_acceptance,evidence,home))
                except (ValueError, KeyError, TypeError, ArithmeticError, SyntaxError, RecursionError) as exc:
                    feedback = dict(reason='rejected_stage_contract', detail=str(exc), rejected_plan=raw_plan)
                    log(dict(kind='plan_rejected', **feedback))
                    revision += 1
                    continue
                plan, index, age, entry, stable_ready = candidate, 0, 0, None, 0
                if cfg.get('stage_contract_reuse', False):
                    (log.folder/f'plan-reuse-resolution-{revision:02d}.json').write_text(
                        json.dumps(references, indent=2))
                    log(dict(kind='plan_contract_references', revision=revision, references=references,
                             physical_action_sent=False))
                if candidate.task_acceptance:
                    task_acceptance = candidate.task_acceptance
                    (log.folder/'task-acceptance-contract.json').write_text(json.dumps([p.model_dump() for p in task_acceptance],indent=2))
                goal_monitor=candidate_monitor
                (log.folder/'goal-protection-contract.json').write_text(json.dumps(
                    [g.model_dump() for g in candidate.protection_groups],indent=2))
                planning_memory.append(dict(reasoning=plan.reasoning,
                    stage_objectives=[dict(id=s.id, objective=s.objective) for s in plan.stages]))
                (log.folder/f'plan-{revision:02d}.json').write_text(plan.model_dump_json(indent=2))
                revision += 1
            if index >= len(plan.stages):
                feedback = dict(reason='stage_list_exhausted', instruction=obs['instruction'],
                                last_completed_plan=plan.model_dump(), current=evidence,
                                guidance='Recheck the public task acceptance and physical state; provide any omitted remaining operations. Stage-list completion alone does not finish the episode.')
                log(dict(kind='plan_exhausted', tick=tick))
                plan = None
                continue
            stage = plan.stages[index]
            new_stage = entry is None
            if entry is None:
                entry = deepcopy(evidence)
                stagnant_actions = 0
                unmet_pose_actions = 0
                hold_stall_actions = 0
            if new_stage and stage.requires_acceptance_indices:
                prerequisites=stage_prerequisites(stage,task_acceptance,evidence,home)
                if not all(check['satisfied'] for check in prerequisites):
                    feedback=dict(reason='stage_prerequisite_unmet',stage=stage.model_dump(),
                        prerequisites=prerequisites,current=evidence,
                        guidance='Your declared entry dependencies are currently false. No action from this stage was sent. Ground a repair or a different applicable stage in these measurements; do not replace a false measurement with a narrative claim.')
                    log(dict(kind='stage_entry_blocked',tick=tick,**feedback,physical_action_sent=False))
                    plan=None
                    continue
            if prompt_mode == 'vision_method_v1' and stage.visual_requirements and stage.purpose != 'sense':
                bounded_requirements = [requirement.model_copy(update=dict(
                    max_age_ticks=min(requirement.max_age_ticks,
                        vision.method_by_id[requirement.id].max_stale_ticks)))
                    for requirement in stage.visual_requirements]
                visual_evidence = visual_checks(bounded_requirements, evidence)
                if not all(check['satisfied'] for check in visual_evidence):
                    feedback = dict(reason='stage_visual_evidence_unavailable',
                        stage=stage.model_dump(), visual_checks=visual_evidence,
                        current=evidence, entry=entry,
                        guidance='Required camera identity, freshness or stereo measurement is missing. No action was sent. Reobserve from permitted RGB cameras or redesign the stage for evidence that is actually measurable; do not use stale object XYZ as proof.')
                    log(dict(kind='stage_failed', tick=tick, **feedback,
                             physical_action_sent=False))
                    vision.last_localization_decision = -10**9
                    plan = None
                    continue
            try:
                state, resolved = compile_stage(stage, evidence, entry, home, age, grippers,
                    [n>=settle_required for n in settled_actions] if settle_required else None)
            except (ValueError, KeyError, TypeError, ArithmeticError, SyntaxError, RecursionError) as exc:
                feedback = dict(reason='stage_relation_unavailable', detail=str(exc), stage=stage.model_dump(), current=evidence)
                log(dict(kind='stage_failed', tick=tick, **feedback))
                plan = None
                continue
            if not endpoint_unmet(stage,state):
                unmet_pose_actions=0
            if cfg.get('unmet_pose_actions',0) and unmet_pose_actions>=cfg['unmet_pose_actions']:
                feedback=dict(reason='pose_reached_endpoint_unmet',stage=stage.model_dump(),state=state,
                    current=evidence,entry=entry,consecutive_actions=unmet_pose_actions,
                    guidance='Active hand targets and commanded finger conditions are reached, but measured object predicates remain false. Holding did not establish the endpoint. Inspect contact, deformation, target offsets or invalid predicates and replan from current evidence. No contact-loss cause or success is inferred; no corrective action was chosen by the runtime.')
                log(dict(kind='stage_failed',tick=tick,**feedback))
                plan=None
                continue
            if new_stage and not state['ready'] and cfg.get('kinematic_preflight', False):
                probe_targets = {}
                for arm, goal in stage.arms.items():
                    if goal.reference == 'joints' or not (goal.axes or goal.rotate):
                        continue
                    i = ('left', 'right').index(arm)
                    quaternion = resolved[arm]['quaternion_wxyz']
                    if goal.rotate:
                        position = np.asarray(entry['robot']['eef_positions_m'][i], float)
                    else:
                        key = 'nominal_grasp_points_m' if goal.reference == 'tcp' else 'eef_positions_m'
                        position = np.asarray(entry['robot'][key][i], float)
                    position = position.copy()
                    for j in goal.axes:
                        position[j] = resolved[arm]['target'][j]
                    if goal.reference == 'tcp' and not goal.rotate:
                        bias = np.linalg.norm(np.asarray(evidence['robot']['nominal_grasp_points_m'][i])-evidence['robot']['eef_positions_m'][i])
                        position -= rot(quaternion).apply([bias, 0., 0.])
                    probe_targets[arm] = dict(position=position.tolist(), quaternion_wxyz=quaternion)
                if probe_targets:
                    diagnostics = call('stage_ik_probe', targets=probe_targets)
                    log(dict(kind='kinematic_preflight', tick=tick, stage=stage.id, targets=probe_targets, diagnostics=diagnostics))
                    if any(not d['numerical_candidate_found'] for d in diagnostics['arms'].values()):
                        feedback = dict(reason='kinematic_endpoint_not_found', stage=stage.model_dump(), current=evidence,
                            diagnostics=diagnostics, requested_targets=probe_targets,
                            guidance='Read-only robot IK did not find this endpoint. This is not a collision check or impossibility proof. Choose a reachable valid goal region, another grasp orientation/height/arm, or intermediate relation. No physical action was sent for this stage.')
                        log(dict(kind='stage_failed', tick=tick, **feedback))
                        plan = None
                        continue
            if state['failures'] or (age >= stage.max_actions and not state['ready']):
                if not state['failures'] and cfg.get('stage_budget_review', False) and budget_reviews < cfg.get('max_budget_reviews',12) and stage.max_actions < 100:
                    request = dict(instruction=obs['instruction'],current_stage=stage.model_dump(),current_motor=state,
                        physical_features=evidence,recent=history[-4:],completed_stages=completed_stages,
                        whole_task_intent=plan.reasoning,
                        native_steps_remaining=meta['max_episode_steps']-tick,
                        pending_stages=[dict(id=s.id,objective=s.objective,max_actions=s.max_actions,
                            ticks_per_action=s.ticks_per_action or cfg['ticks_per_action']) for s in plan.stages[index+1:]])
                    request.update(task_acceptance_contract=[p.model_dump() for p in task_acceptance],
                                   task_acceptance_measurements=acceptance_evidence)
                    (log.folder/f'budget-review-input-{budget_reviews:02d}.json').write_text(json.dumps(request,indent=2))
                    raw = inference(clients['planner'].chat,log,BUDGET_PROMPT,request,None,StageBudgetReview.model_json_schema())
                    (log.folder/f'budget-review-response-{budget_reviews:02d}.json').write_text(json.dumps(raw,indent=2))
                    budget_reviews += 1
                    try:
                        review = StageBudgetReview.model_validate(raw)
                        remaining = (meta['max_episode_steps']-tick)//(stage.ticks_per_action or cfg['ticks_per_action'])
                        extension = min(review.extend_by,100-stage.max_actions,remaining)
                        log(dict(kind='stage_budget_review',tick=tick,stage=stage.id,
                            prior_max_actions=stage.max_actions,extension=extension,review=review.model_dump()))
                        if extension:
                            stage.max_actions += extension
                            continue
                    except ValueError as exc:
                        log(dict(kind='budget_review_rejected',tick=tick,stage=stage.id,detail=str(exc)))
                feedback = dict(reason=state['failures'] or 'stage_action_budget', stage=stage.model_dump(), state=state,
                                current=evidence, entry=entry)
                log(dict(kind='stage_failed', tick=tick, **feedback))
                plan = None
                continue
            questions = add_visual_question(motor_questions(state), stage)
            request, cameras, schema = prepare(log.folder, decision, obs['instruction'],
                stage, canonical_motor_state(state), questions, vision, evidence, obs, notes)
            raw = inference(clients['decision'].chat, log, DECISION_PROMPT,
                            request, cameras, schema)
            answer = validate(raw, questions)
            (log.folder/f'decision-output-{decision:04d}.json').write_text(json.dumps(answer))
            choices = {name: value['choice'] for name, value in answer.items()}
            summary['decisions'] += 1
            log(dict(kind='decision', decision=decision, tick=tick, stage=index, stage_id=stage.id,
                     motor=state, answer=answer))
            if choices.get('visual_integrity', 'consistent') != 'consistent':
                feedback = dict(reason='decision_visual_'+choices['visual_integrity'],
                    stage=stage.model_dump(), current=evidence,
                    guidance='No motor action was sent. Use fresh permitted RGB evidence and revise the sensing method or stage if needed.')
                log(dict(kind='stage_failed', tick=tick, **feedback, physical_action_sent=False))
                vision.last_localization_decision = -10**9
                plan = None
                continue
            active_motion = []
            for arm, goal in stage.arms.items():
                channels = ('j0','j1','j2','j3','j4','j5') if goal.reference == 'joints' else ('x','y','z')
                active_motion.extend(f'{arm}_{channels[j]}' for j in goal.axes)
                if goal.rotate and goal.reference != 'joints':
                    active_motion.extend(f'{arm}_{axis}' for axis in ('rx','ry','rz'))
            if (not state['ready'] and not state['motion_ready'] and state['grippers_ready']
                    and active_motion and all(choices.get(name) == 'hold' for name in active_motion)
                    and all(choices.get(f'{arm}_gripper','hold') == 'hold' for arm in stage.arms)):
                hold_stall_actions += 1
            else:
                hold_stall_actions = 0
            if cfg.get('decision_hold_stall_actions',0) and hold_stall_actions >= cfg['decision_hold_stall_actions']:
                feedback = dict(reason='decision_hold_stall', stage=stage.model_dump(), state=state,
                    current=evidence, entry=entry, consecutive_decisions=hold_stall_actions,
                    guidance='Decision model chose hold on every active motion channel while the measured hand target was unmet. No physical action was sent; recheck visible target and reachable stage.')
                log(dict(kind='stage_failed',tick=tick,**feedback,physical_action_sent=False))
                plan = None
                continue
            if state['ready']:
                stable_ready = stable_ready+1 if choices['transition'] == 'advance' else 0
                if stable_ready >= 1:
                    completed_stages.append(dict(revision=revision, id=stage.id, objective=stage.objective,
                        native_tick=tick, measured_checks=state['checks'], actions=age))
                    (log.folder/'completed-stage-history.json').write_text(json.dumps(completed_stages, indent=2))
                    completed_contracts.append(dict(**completed_stages[-1],contract=stage.model_dump()))
                    (log.folder/'completed-stage-contracts.json').write_text(json.dumps(completed_contracts,indent=2))
                    index += 1; entry = None; age = 0; stable_ready = 0
                    log(dict(kind='stage_advanced', tick=tick, new_index=index))
                    if stage.observe_after:
                        feedback=dict(reason='measured_milestone_handoff',completed_stage=completed_contracts[-1],
                            current=evidence,remaining_native_steps=meta['max_episode_steps']-tick,
                            unexecuted_intent=[dict(id=s.id,objective=s.objective) for s in plan.stages[index:]],
                            guidance='Your declared observation boundary was reached. Ground the next stages in this measured milestone and current geometry/images. Retain global identity/order and irreversible history, and recheck reversible task relations. The old unexecuted suffix is intent, not an automatically replayed controller; no native success is inferred.')
                        log(dict(kind='stage_planner_handoff',tick=tick,stage=stage.id,physical_action_sent=False))
                        plan=None
                    continue
            signs = {'negative': -1, 'hold': 0, 'positive': 1}
            def magnitude(arm, name, bound):
                if cfg.get('magnitude_mode', 'fixed') == 'fixed':
                    return bound
                # Metric limiting belongs to the actuator, not a direction
                # selector. Preserve the provider's chosen sign even if wrong.
                error = state['arms'][arm]['axes'].get(name, {}).get('error', 0.)
                return min(bound, max(.001, abs(error)))
            targets = {}
            joint_targets = {}
            translation_increments={}
            for i, arm in enumerate(('left', 'right')):
                p = np.asarray(obs['eef_positions'][i], float)
                q = np.asarray(obs['eef_quaternions_wxyz'][i], float)
                if arm in stage.arms:
                    goal = stage.arms[arm]
                    delta = np.array([signs.get(choices.get(arm+'_'+a, 'hold'), 0)*magnitude(arm,a,stage.translation_cap_m or cfg['step_m']) for a in 'xyz'])
                    delta=limit_translation_speed(delta,stage.translation_speed_m_per_s,
                        stage.ticks_per_action or cfg['ticks_per_action'],meta['control_dt'])
                    translation_increments[arm]=delta.tolist()
                    rdelta = np.array([signs.get(choices.get(arm+'_'+a, 'hold'), 0)*magnitude(arm,a,cfg['angle_rad']) for a in ('rx', 'ry', 'rz')])
                    # Bounded selected increments; no sign corrections or expert actions.
                    if np.linalg.norm(delta) > .05+1e-8 or np.linalg.norm(rdelta) > .35+1e-8:
                        raise ValueError('Combined Jev action exceeds native local bound')
                    p = p+delta
                    q = (Rotation.from_rotvec(rdelta)*rot(q)).as_quat()[[3, 0, 1, 2]]
                    if goal.reference == 'joints':
                        joint_targets[arm] = [float(obs['states'][i*7+j])+signs.get(choices.get(arm+'_j'+str(j), 'hold'), 0)*magnitude(arm,'j'+str(j),cfg.get('joint_step_rad', .06)) for j in range(6)]
                    else:
                        if not goal.rotate:
                            q = resolved[arm]['quaternion_wxyz']
                        if goal.reference == 'tcp' and not goal.rotate:
                            offset = np.asarray(evidence['robot']['nominal_grasp_points_m'][i])-evidence['robot']['eef_positions_m'][i]
                            bias = float(np.linalg.norm(offset))
                            point = np.asarray(evidence['robot']['nominal_grasp_points_m'][i])+delta
                            for j in range(3):
                                if j not in goal.axes:
                                    point[j] = entry['robot']['nominal_grasp_points_m'][i][j]
                            p = point-rot(q).apply([bias, 0., 0.])
                        else:
                            for j in range(3):
                                if j not in goal.axes:
                                    p[j] = entry['robot']['eef_positions_m'][i][j]
                    selected = choices.get(arm+'_gripper', 'hold')
                    if selected != 'hold':
                        command_opening=float(selected == 'open')
                        if command_opening!=grippers[i]:settled_actions[i]=0
                        grippers[i] = command_opening
                targets[arm] = dict(position=p.tolist(), quaternion_wxyz=np.asarray(q).tolist(),
                                    gripper_opening=grippers[i], gripper_closed=bool(grippers[i] < .5))
            terminal = None
            action_ticks = stage.ticks_per_action or cfg['ticks_per_action']
            before_action_tick=tick
            for substep in range(min(action_ticks, meta['max_episode_steps']-tick)):
                fraction = (substep+1)/action_ticks
                interpolated = deepcopy(targets)
                for i, arm in enumerate(('left', 'right')):
                    start_position = np.asarray(obs['eef_positions'][i], float)
                    final_position = np.asarray(targets[arm]['position'], float)
                    interpolated[arm]['position'] = (start_position+fraction*(final_position-start_position)).tolist()
                    start_rotation = rot(obs['eef_quaternions_wxyz'][i])
                    change = (rot(targets[arm]['quaternion_wxyz'])*start_rotation.inv()).as_rotvec()
                    interpolated[arm]['quaternion_wxyz'] = (Rotation.from_rotvec(fraction*change)*start_rotation).as_quat()[[3,0,1,2]].tolist()
                proposal = call('eef_joint_target', targets=interpolated)
                command = np.asarray(proposal['action'], np.float32)
                current = call('teacher_observation')
                for i, arm in enumerate(('left', 'right')):
                    if arm not in stage.arms:
                        command[i*7:i*7+6] = current['states'][i*7:i*7+6]
                    elif stage.arms[arm].reference == 'joints':
                        for j in range(6):
                            start_joint = float(obs['states'][i*7+j])
                            command[i*7+j] = start_joint+fraction*(joint_targets[arm][j]-start_joint)
                    command[i*7+6] = grippers[i]
                ack = call('chunk_step', actions=command.reshape(1, 14), controller='gpt6_luna_stage_ir')
                tick = ack['step_id']
                terminal = ack['steps'][-1]
                if terminal['terminated'] or terminal['truncated']:
                    summary.update(status='native_terminal', complete=True, physical_success=bool(terminal['success']))
                    break
            after, _ = observe_stage(decision+1)
            opening_changes=[]
            for i in range(2):
                change=abs(float(after['robot']['states'][i*7+6])-float(evidence['robot']['states'][i*7+6]))
                opening_changes.append(change)
                settled_actions[i]=settled_actions[i]+1 if change<cfg.get('gripper_settle_epsilon',.015) else 0
            before_vars, after_vars = variables(evidence), variables(after)
            commanded_changes = []
            for arm, goal in stage.arms.items():
                prefix = 'j' if goal.reference == 'joints' else 'tcp_' if goal.reference == 'tcp' else 'wrist_'
                for j in goal.axes:
                    channel = 'j'+str(j) if goal.reference == 'joints' else 'xyz'[j]
                    if choices.get(arm+'_'+channel) not in ('negative', 'positive'):
                        continue
                    field = 'j'+str(j) if goal.reference == 'joints' else prefix+'xyz'[j]
                    scale = .003 if goal.reference == 'joints' else .0003
                    commanded_changes.append(abs(after_vars['r'][arm][field]-before_vars['r'][arm][field])/scale)
                if goal.rotate:
                    i = ('left', 'right').index(arm)
                    if any(choices.get(arm+'_'+a) in ('negative', 'positive') for a in ('rx', 'ry', 'rz')):
                        change = (rot(after['robot']['eef_quaternions_wxyz'][i])*rot(evidence['robot']['eef_quaternions_wxyz'][i]).inv()).magnitude()
                        commanded_changes.append(change/.003)
            stagnant_actions = stagnant_actions+1 if commanded_changes and max(commanded_changes)<1 else 0
            effects = dict(choices=choices, tick=tick, stage=stage.id,
                active_protection_groups=stage.protection_group_ids if stage.protection_group_ids is not None else
                    [group.id for group in plan.protection_groups],
                native_ticks_elapsed=tick-before_action_tick,requested_translation_increment_m=translation_increments,
                measured_gripper_opening_change=opening_changes,gripper_settled_actions=list(settled_actions),
                actual_wrist_displacement_m=(np.asarray(after['robot']['eef_positions_m'])-evidence['robot']['eef_positions_m']).tolist(),
                current=after, native_tracking_diagnostics=proposal.get('diagnostics'))
            if task_acceptance:
                try:
                    effects['task_acceptance_progress'] = task_progress(
                        task_checks(task_acceptance,evidence,home),
                        task_checks(task_acceptance,after,home))
                except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                    effects['task_acceptance_progress_unavailable'] = str(exc)
            log(dict(kind='execution', decision=decision, **effects))
            history.append(dict(**{k: v for k, v in effects.items() if k != 'current'},
                                measured_motor_residuals=state['arms']))
            age += 1
            unmet_pose_actions=unmet_pose_actions+1 if endpoint_unmet(stage,state) else 0
            print(json.dumps(dict(decision=decision, tick=tick, stage=stage.id, choices=choices, ready=state['ready'])), flush=True)
            if summary['complete']:
                break
            if goal_monitor and goal_monitor.groups:
                try:
                    regressed=goal_monitor.update(task_checks(task_acceptance,after,home),
                        cfg.get('goal_regression_actions',3),stage.protection_group_ids)
                except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                    feedback=dict(reason='protected_goal_measurement_unavailable',detail=str(exc),
                        stage=stage.model_dump(),current=after)
                    log(dict(kind='stage_failed',tick=tick,**feedback))
                    plan=None
                    continue
                if regressed:
                    feedback=dict(reason='previously_achieved_goal_regressed',groups=regressed,
                        stage=stage.model_dump(),current=after,entry=entry,
                        guidance='These GPT-declared spatial relations were measured valid, then invalid for consecutive actions. Their cause is not inferred. Preserve irreversible counts/identity but re-evaluate reversible relations. Choose support, contact transfer, a different motion or repair from current measurements; no automatic corrective action was sent.')
                    log(dict(kind='stage_failed',tick=tick,**feedback))
                    plan=None
                    continue
            if stagnant_actions >= cfg.get('stagnation_actions', 6) and not state['ready']:
                feedback = dict(reason='observed_stagnation', stage=stage.model_dump(), state=state,
                    current=after, entry=entry, consecutive_actions=stagnant_actions,
                    guidance='Jev requested motion, but selected coordinates changed less than 0.3 mm or 3 mrad for consecutive actions. Cause is not known: inspect measured geometry, contacts, tracking and reachability. Revise this stage, retaining completed task operations. No success is inferred from stagnation.')
                log(dict(kind='stage_failed', tick=tick, **feedback))
                plan = None
        else:
            summary['status'] = 'decision_limit'
    except Exception as exc:
        summary.update(status='policy_error', error_type=type(exc).__name__, error=str(exc))
        log(dict(kind='error', **summary))
    finally:
        if episode:
            try:
                result = rpc.request('finish_pilot', episode_id=episode, step_id=tick, reason=summary['status'])
                summary.update(native_result=result, physical_success=bool(result['success']), complete=bool(result['terminated'] or result['truncated']))
            except Exception as exc:
                summary['finish_error'] = str(exc)
        summary.update(native_steps=tick, gpt_calls=clients['planner'].calls,
                       vision_calls=clients['vision'].calls if vision is not None else 0,
                       local_detector_calls=vision.local_detector_calls if vision is not None else 0,
                       local_detector_seconds=vision.local_detector_seconds if vision is not None else 0,
                       decision_calls=clients['decision'].calls,
                       full_planning_rounds=revision,budget_reviews=budget_reviews,
                       elapsed_s=time.monotonic()-started)
        (log.folder/'summary.json').write_text(json.dumps(summary, indent=2))
        for client in clients.values():
            client.close()
        rpc.close()
    print(json.dumps(summary), flush=True)
    return summary


def main():
    p = argparse.ArgumentParser()
    for name in ('config', 'case', 'api-config', 'output'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--port', required=True, type=int)
    p.add_argument('--max-decisions', type=int)
    p.add_argument('--policy'); p.add_argument('--observation')
    run(p.parse_args())


if __name__ == '__main__':
    main()
