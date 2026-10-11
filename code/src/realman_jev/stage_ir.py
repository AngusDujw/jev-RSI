"""Task-independent relational stages. No task names or expert action policies."""
from __future__ import annotations
import ast
import math
import operator
from difflib import get_close_matches
from typing import Literal
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.spatial.transform import Rotation


class Predicate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expression: str
    comparison: Literal['lt', 'le', 'ge', 'gt']
    threshold: float = Field(allow_inf_nan=False)
    description: str


class ArmGoal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reference: Literal['tcp', 'wrist', 'joints'] = 'tcp'
    target: list[str]  # Three Cartesian scalar expressions or six joint expressions.
    axes: list[int]   # Only these axes move; all others retain the stage-entry value.
    orientation: Literal['entry', 'home', 'frame'] = 'entry'
    approach: list[float] | None = None
    closing: list[float] | None = None
    rotate: bool = False
    gripper: Literal['open', 'close', 'hold'] = 'hold'
    tolerance: float = Field(default=.009, ge=.002, le=.04)
    rotation_tolerance: float = Field(default=.11, ge=.025, le=.2)


class VisualRequirement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^v_[a-z][a-z0-9_]*$')
    quality: Literal['visible_rgb', 'fresh_stereo', 'last_stereo_bounded']
    max_age_ticks: int = Field(default=12, ge=0, le=80)


class Stage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    objective: str
    arms: dict[Literal['left', 'right'], ArmGoal]
    completion: list[Predicate] = Field(default_factory=list)
    abort: list[Predicate] = Field(default_factory=list)
    finish_on: Literal['pose_and_checks', 'checks'] = 'pose_and_checks'
    ticks_per_action: int | None = Field(default=None, ge=1, le=6)
    translation_cap_m: float | None = Field(default=None,ge=.002,le=.025)
    translation_speed_m_per_s: float | None = Field(default=None,ge=.03,le=.8)
    observe_after: bool = False
    visual_requirements: list[VisualRequirement] = Field(default_factory=list, max_length=12)
    protection_group_ids: list[str] | None = Field(default=None,max_length=32)
    requires_acceptance_indices: list[int] = Field(default_factory=list,max_length=128)
    min_actions: int = Field(default=0, ge=0, le=10)
    max_actions: int = Field(default=35, ge=1, le=100)


class GoalProtection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1,max_length=80)
    acceptance_indices: list[int] = Field(min_length=1,max_length=128)


class GoalMonitor:
    """Detect measured regression; select no targets, grasps or directions."""
    def __init__(self, groups, checks):
        if len({g.id for g in groups})!=len(groups):
            raise ValueError('Protection group IDs must be unique')
        self.groups=groups
        self.state={}
        for g in groups:
            if len(set(g.acceptance_indices))!=len(g.acceptance_indices) or any(
                    not 0<=i<len(checks) for i in g.acceptance_indices):
                raise ValueError('Protection indices must identify distinct task acceptance predicates')
            self.state[g.id]=dict(armed=all(checks[i]['satisfied'] for i in g.acceptance_indices),violations=0)

    def update(self, checks, persistence=3, active_groups=None):
        if persistence<1:
            raise ValueError('Regression persistence must be positive')
        if active_groups is not None and not set(active_groups)<=set(self.state):
            raise ValueError('Active protection groups must be declared by the plan')
        alerts=[]
        for g in self.groups:
            state=self.state[g.id]
            if active_groups is not None and g.id not in active_groups:
                # GPT can deliberately change a coupled relation in this stage.
                # Resume with fresh consecutive evidence, retaining prior arming.
                state['violations']=0
                continue
            selected=[checks[i] for i in g.acceptance_indices]
            if all(c['satisfied'] for c in selected):
                state.update(armed=True,violations=0)
            elif state['armed']:
                state['violations']+=1
                if state['violations']>=persistence:
                    alerts.append(dict(id=g.id,acceptance_indices=g.acceptance_indices,
                        consecutive_violations=state['violations'],measurements=selected))
                    # One notification until the relation is achieved again.
                    state.update(armed=False,violations=0)
        return alerts


class StagePlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reasoning: str
    stages: list[Stage] = Field(min_length=1, max_length=80)
    task_acceptance: list[Predicate] = Field(default_factory=list,max_length=128)
    protection_groups: list[GoalProtection] = Field(default_factory=list,max_length=32)

    @model_validator(mode='after')
    def validate_protection_scopes(self):
        declared={group.id for group in self.protection_groups}
        for stage in self.stages:
            required=stage.requires_acceptance_indices
            if len(set(required))!=len(required) or any(i<0 for i in required):
                raise ValueError('Stage requires_acceptance_indices must name distinct nonnegative indices')
            scope=stage.protection_group_ids
            if scope is not None:
                if not set(scope)<=declared:
                    raise ValueError('Stage protection_group_ids must name declared plan groups')
                # Repeating the same group changes no protection semantics.
                stage.protection_group_ids=list(dict.fromkeys(scope))
        return self


def visual_checks(requirements, evidence):
    """Sensor evidence gates; never consult simulator truth or reward."""
    objects = {obj['id']: obj for obj in evidence['objects']}
    checks = []
    for requirement in requirements:
        obj = objects.get(requirement.id)
        boxes = obj.get('visual_boxes', {}) if obj else {}
        visible = any(box.get('observed') for box in boxes.values())
        age = (evidence['tick']-obj['last_seen_tick'] if obj and
               obj.get('last_seen_tick') is not None else None)
        age_ok = age is not None and 0 <= age <= requirement.max_age_ticks
        stereo = bool(obj and obj.get('position_provenance') == 'stereo_RGB_triangulation'
                      and obj.get('position_measurement') is not None)
        last_stereo = obj.get('last_stereo') if obj else None
        stereo_age = (evidence['tick']-last_stereo['tick'] if last_stereo else None)
        bounded_stereo = bool(stereo_age is not None and
                              0 <= stereo_age <= requirement.max_age_ticks and
                              not obj.get('possibly_mobile', False) and
                              not obj.get('visual_motion_confirmed', False))
        satisfied = bool((requirement.quality == 'visible_rgb' and age_ok and visible) or
                         (requirement.quality == 'fresh_stereo' and age_ok and visible and stereo) or
                         (requirement.quality == 'last_stereo_bounded' and bounded_stereo))
        checks.append(dict(id=requirement.id, quality=requirement.quality,
                           max_age_ticks=requirement.max_age_ticks,
                           age_ticks=age, last_stereo_age_ticks=stereo_age,
                           visible=visible, fresh_stereo=stereo,
                           satisfied=satisfied,
                           reason='measured' if satisfied else 'missing_or_stale_visual_evidence'))
    return checks


class StageBudgetReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reasoning: str
    extend_by: int = Field(ge=0, le=40)


BUDGET_PROMPT = '''You are GPT-6 reviewing ONLY the action budget of your current RoboDojo stage.
You retain ownership of the whole task. Return JSON with reasoning and extend_by (integer 0..40).
An extension preserves this exact stage's target expressions, coordinate frames, entry snapshot,
completion and abort predicates. It cannot repair a wrong target, missing grasp or lost capture.
Choose a positive extension only when measured progress supports the existing physical relation,
it remains useful for the task, and the remaining native steps also allow the pending operations.
Native robot IK clips per-tick joint changes and task deltas: requested caps are not measured progress.
Small but consistent actual progress can justify more actions. Stagnation or a wrong contact needs
full replanning instead: return zero. Abort checks and native task limits remain active throughout.
Do not infer task success. Do not output a new task plan or any action direction.'''


OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv}
FUNCS = {'min': min, 'max': max, 'abs': abs, 'sqrt': math.sqrt, 'hypot': math.hypot}


def expression(text, context):
    """Evaluate arithmetic and dictionary paths only; never execute generated code."""
    if len(text) > 4000:
        raise ValueError('Expression exceeds length limit')
    tree = ast.parse(text, mode='eval')
    if sum(1 for _ in ast.walk(tree)) > 500:
        raise ValueError('Expression exceeds arithmetic-node limit')
    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in context:
                raise ValueError(f'Unknown expression root {node.id!r}; available roots: {", ".join(context)}')
            return context[node.id]
        if isinstance(node, ast.Attribute) and not node.attr.startswith('_'):
            parent=visit(node.value)
            path=ast.unparse(node)
            if not isinstance(parent,dict):
                raise ValueError(f'Observation path {path!r} does not address a dictionary')
            if node.attr not in parent:
                keys=[str(key) for key in parent]
                nearby=get_close_matches(node.attr,keys,n=8,cutoff=.35)
                available=', '.join((nearby+[key for key in keys if key not in nearby])[:24])
                raise ValueError(f'Unavailable observation path {path!r} in expression {text!r}; available fields at {ast.unparse(node.value)!r}: {available}')
            return parent[node.attr]
        if isinstance(node, ast.BinOp) and isinstance(node.op,ast.Pow):
            if not isinstance(node.right,ast.Constant) or type(node.right.value) is not int or node.right.value!=2:
                raise ValueError('Only a literal square exponent is supported')
            return float(visit(node.left))**2
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS and not node.keywords:
            return FUNCS[node.func.id](*[visit(x) for x in node.args])
        raise ValueError('Unsupported expression syntax')
    value = float(visit(tree.body))
    if not math.isfinite(value):
        raise ValueError('Non-finite expression result')
    return value


def variables(evidence):
    out = {'o': {}, 'r': {}}
    for obj in evidence['objects']:
        if not obj['id'].isidentifier():
            raise ValueError('Object IDs must be valid identifiers')
        fields = dict(zip('xyz', obj['position_m']))
        if obj.get('kind') == 'VisualDetection':
            provenance = obj.get('position_provenance')
            fields['stereo_valid'] = float(provenance == 'stereo_RGB_triangulation')
            fields['stereo_streak'] = float(obj.get('stereo_streak', 0))
            fields['xy_fresh'] = float(provenance in (
                'stereo_RGB_triangulation', 'single_view_XY_depth_proxy_Z_UNVERIFIED'))
            last_stereo = obj.get('last_stereo')
            if last_stereo is not None:
                fields.update({'last_stereo_'+axis: float(value) for axis, value in
                    zip('xyz', last_stereo['position_m'])})
                fields['last_stereo_age_ticks'] = float(obj['last_stereo_age_ticks'])
            fields['visual_motion_confirmed'] = float(obj.get('visual_motion_confirmed', False))
            visual_velocity = obj.get('visual_xy_velocity_m_per_s')
            if visual_velocity is not None:
                fields['vx'], fields['vy'] = map(float, visual_velocity)
                fields['visual_xy_velocity_age_ticks'] = float(obj['visual_xy_velocity_age_ticks'])
        fields.update(dict(zip(('qw', 'qx', 'qy', 'qz'), obj['quaternion_wxyz'])))
        fields.update({'up_'+a: float(v) for a, v in zip('xyz', rot(obj['quaternion_wxyz']).apply([0., 0., 1.]))})
        geometry = obj.get('geometry', {})
        for prefix, key in [('min_', 'world_bbox_min_m'), ('max_', 'world_bbox_max_m')]:
            if key in geometry:
                fields.update({prefix+a: x for a, x in zip('xyz', geometry[key])})
        if 'grasp_point_m' in obj:
            fields.update({'grasp_'+a: x for a, x in zip('xyz', obj['grasp_point_m'])})
        if 'velocity_m_per_s' in obj:
            fields.update({'v'+a: x for a, x in zip('xyz', obj['velocity_m_per_s'])})
        for name, point in obj.get('keypoints', {}).items():
            fields.update({name+'_'+a: x for a, x in zip('xyz', point)})
            local = rot(obj['quaternion_wxyz']).inv().apply(np.asarray(point,float)-obj['position_m'])
            fields.update({name+'_local_'+a: float(x) for a,x in zip('xyz',local)})
        for name, value in obj.get('joints', {}).items():
            if name.isidentifier():
                fields['joint_'+name] = float(value)
        for arm,reference in obj.get('material_references',{}).items():
            if arm in ('left','right'):
                fields.update({'material_'+arm+'_'+a:float(v) for a,v in zip('xyz',reference['position_m'])})
                fields['material_'+arm+'_distance']=float(reference['distance_to_fingertip_m'])
                fields['material_'+arm+'_identity_frozen']=float(reference['identity_frozen'])
        out['o'][obj['id']] = fields
    robot = evidence['robot']
    for i, arm in enumerate(('left', 'right')):
        fields = {}
        for prefix, key in [('tcp_', 'nominal_grasp_points_m'), ('wrist_', 'eef_positions_m')]:
            fields.update({prefix+a: x for a, x in zip('xyz', robot[key][i])})
        fields.update({'j'+str(j): float(robot['states'][7*i+j]) for j in range(6)})
        fields.update({'wrist_'+name:float(x) for name,x in zip(('qw','qx','qy','qz'),robot['eef_quaternions_wxyz'][i])})
        fields['opening'] = float(robot['states'][7*i+6])
        finger = robot.get('finger_geometry', {}).get(arm, {})
        for prefix, key in [('finger_min_', 'world_bbox_min_m'), ('finger_max_', 'world_bbox_max_m'),
                            ('tip_', 'distal_midpoint_m')]:
            if key in finger:
                fields.update({prefix+a: x for a, x in zip('xyz', finger[key])})
        frame = robot.get('measured_gripper_frames', {}).get(arm, {})
        for prefix,key in [('approach_', 'approach_world'),('closing_', 'closing_world')]:
            if key in frame:
                fields.update({prefix+a: x for a,x in zip('xyz',frame[key])})
        out['r'][arm] = fields
    return out


def task_checks(predicates, evidence, home):
    context = {'now':variables(evidence),'home':variables(home)}
    checks = []
    for p in predicates:
        value = expression(p.expression,context)
        passed = {'lt':operator.lt,'le':operator.le,'ge':operator.ge,'gt':operator.gt}[p.comparison](value,p.threshold)
        margin = value-p.threshold if p.comparison in ('ge','gt') else p.threshold-value
        checks.append(dict(description=p.description,value=value,comparison=p.comparison,
                           threshold=p.threshold,margin=margin,satisfied=bool(passed)))
    return checks


def task_progress(before, after):
    """Report measured signed-margin changes without choosing a recovery action."""
    if len(before)!=len(after):
        raise ValueError('Task acceptance contract changed during progress measurement')
    return [dict(acceptance_index=i, description=current['description'],
                 before_margin=previous['margin'], after_margin=current['margin'],
                 delta_margin=current['margin']-previous['margin'],
                 before_satisfied=previous['satisfied'], after_satisfied=current['satisfied'])
            for i,(previous,current) in enumerate(zip(before,after))]


def stage_prerequisites(stage, predicates, evidence, home):
    """Evaluate only GPT-declared entry dependencies; select no replacement stage."""
    required=stage.requires_acceptance_indices
    if len(set(required))!=len(required) or any(not 0<=i<len(predicates) for i in required):
        raise ValueError('Stage prerequisites must index the current task_acceptance contract')
    if not required:
        return []
    checks=task_checks(predicates,evidence,home)
    return [dict(acceptance_index=i,**checks[i]) for i in required]


def rot(q):
    return Rotation.from_quat(np.asarray(q)[[1, 2, 3, 0]])


def orientation(goal, entry, home, index):
    if goal.orientation != 'frame':
        return rot((entry if goal.orientation == 'entry' else home)['robot']['eef_quaternions_wxyz'][index])
    approach = np.asarray(goal.approach, float)
    closing = np.asarray(goal.closing, float)
    if approach.shape != (3,) or closing.shape != (3,):
        raise ValueError('Frame requires three-dimensional approach and closing axes')
    approach /= np.linalg.norm(approach)
    closing -= np.dot(closing, approach)*approach
    closing /= np.linalg.norm(closing)
    if not np.isfinite(np.r_[approach, closing]).all():
        raise ValueError('Degenerate orientation frame')
    return Rotation.from_matrix(np.column_stack((approach, closing, np.cross(approach, closing))))


def compile_stage(stage, evidence, entry, home, actions, gripper_commands=None, gripper_settled=None):
    context = {'now': variables(evidence), 'entry': variables(entry), 'home': variables(home), 'actions': actions}
    errors, resolved = {}, {}
    ready = actions >= stage.min_actions
    grips_ready = True
    motion_ready = True
    robot = evidence['robot']
    for arm, goal in stage.arms.items():
        index = ('left', 'right').index(arm)
        count = 6 if goal.reference == 'joints' else 3
        if len(goal.target) not in (count, len(goal.axes)) or len(set(goal.axes)) != len(goal.axes) or any(type(i) is not int or not 0 <= i < count for i in goal.axes):
            raise ValueError('Target/active-axis shape mismatch')
        current = (np.asarray(robot['states'][7*index:7*index+6],float) if count == 6 else
                   np.asarray(robot['nominal_grasp_points_m' if goal.reference == 'tcp' else 'eef_positions_m'][index],float))
        if len(goal.target) == count:
            target = np.array([expression(s, context) for s in goal.target])
        else:
            target = current.copy()
            for j, s in zip(goal.axes, goal.target):
                target[j] = expression(s, context)
        error = target-current
        desired_rot = orientation(goal, entry, home, index)
        rerr = (desired_rot*rot(robot['eef_quaternions_wxyz'][index]).inv()).as_rotvec()
        values = {}
        for j in goal.axes:
            name = 'j'+str(j) if count == 6 else 'xyz'[j]
            values[name] = dict(error=round(float(error[j]), 6), tolerance=goal.tolerance)
            ready &= abs(values[name]['error']) <= goal.tolerance
            motion_ready &= abs(values[name]['error']) <= goal.tolerance
        if goal.rotate and count != 6:
            for j, name in enumerate(('rx', 'ry', 'rz')):
                values[name] = dict(error=round(float(rerr[j]), 6), tolerance=goal.rotation_tolerance)
                ready &= abs(values[name]['error']) <= goal.rotation_tolerance
                motion_ready &= abs(values[name]['error']) <= goal.rotation_tolerance
        opening = float(robot['states'][7*index+6])
        # A captured object may keep the fingers partially open. The commanded
        # opening is an actuator goal; capture remains a separate temporal test.
        command = gripper_commands[index] if gripper_commands is not None else None
        grip_ready = (goal.gripper == 'hold' or
                      (opening > .92 if goal.gripper == 'open' else
                       command is not None and command < .5 or opening < .15))
        if goal.gripper=='close' and gripper_settled is not None:
            grip_ready=bool(command is not None and command<.5 and gripper_settled[index])
        ready &= grip_ready
        grips_ready &= grip_ready
        errors[arm] = dict(axes=values, gripper=goal.gripper, opening=round(opening, 4), gripper_ready=bool(grip_ready),
                          last_commanded_opening=command, opening_is_capture_evidence=False,
                          closing_settled=gripper_settled[index] if gripper_settled is not None else None)
        resolved[arm] = dict(target=target.tolist(), quaternion_wxyz=desired_rot.as_quat()[[3, 0, 1, 2]].tolist())
    checks = []
    checks_ready = True
    for p in stage.completion:
        value = expression(p.expression, context)
        passed = bool({'lt': operator.lt, 'le': operator.le, 'ge': operator.ge, 'gt': operator.gt}[p.comparison](value, p.threshold))
        checks.append(dict(description=p.description, value=value, comparison=p.comparison, threshold=p.threshold, satisfied=passed))
        ready &= passed
        checks_ready &= passed
    if stage.finish_on == 'checks':
        if not stage.completion:
            raise ValueError('finish_on=checks requires measured completion predicates')
        ready = actions >= stage.min_actions and grips_ready and checks_ready
    failures = [p.description for p in stage.abort if {'lt': operator.lt, 'le': operator.le, 'ge': operator.ge, 'gt': operator.gt}[p.comparison](expression(p.expression, context), p.threshold)]
    return dict(stage=stage.id, objective=stage.objective, finish_on=stage.finish_on, arms=errors, checks=checks,
                actions=actions, min_actions=stage.min_actions, ready=bool(ready), failures=failures,
                motion_ready=bool(motion_ready),grippers_ready=bool(grips_ready),checks_ready=bool(checks_ready)), resolved


def endpoint_unmet(stage, state):
    """Reached an active motion target, but its measured object endpoint failed."""
    return bool(any(g.axes or g.rotate for g in stage.arms.values()) and
        state['actions']>=state['min_actions'] and state['motion_ready'] and
        state['grippers_ready'] and not state['checks_ready'] and not state['failures'])


def limit_translation_speed(delta, speed, ticks, control_dt):
    """Uniformly scale selected increments; never change any selected sign."""
    delta=np.asarray(delta,float)
    if speed is None:return delta
    if not np.isfinite(speed) or not .03<=speed<=.8 or ticks<1 or not np.isfinite(control_dt) or control_dt<=0:
        raise ValueError('Invalid selected translation speed or physical interval')
    bound=speed*ticks*control_dt
    length=float(np.linalg.norm(delta))
    return delta*min(1.,bound/length) if length else delta


def motor_questions(state):
    def question(instructions, criteria):
        return dict(type='choice', instructions=instructions, criteria=criteria)
    if state['ready']:
        return {'transition': question('Judge ONLY this current stage. All measured endpoint conditions are satisfied. Advance to the next GPT stage.',
                   {'advance': 'Current stage endpoint is satisfied', 'hold': 'Need another observation', 'blocked': 'Evidence inconsistent'})}
    questions = {}
    for arm, values in state['arms'].items():
        for name, axis in values['axes'].items():
            scale, unit = (1000, 'millimetres') if name in 'xyz' else (1000, 'milliradians')
            questions[arm+'_'+name] = question(
                f'{arm} {name}: current coordinate=0 {unit}, target coordinate={axis["error"]*scale:+.3f} {unit}. '
                f'Deadband +/-{axis["tolerance"]*scale:.3f} {unit}. '
                'If target is smaller than current by more than deadband decrease; if larger increase; otherwise hold. '
                'This is a relative coordinate; answer this axis independently. Do not plan or change stages.',
                {'negative': 'Move along the negative direction', 'hold': 'Retain this axis', 'positive': 'Move along the positive direction'})
        if values['gripper'] != 'hold' and not values['gripper_ready']:
            questions[arm+'_gripper'] = question(f'Current stage finger target is {values["gripper"]}. Measured normalized opening={values["opening"]}. Follow that command only.',
                  {'open': 'Open fingers', 'close': 'Close fingers', 'hold': 'Retain current command'})
    if not questions:
        questions['wait'] = question('The arm target is reached but temporal evidence/minimum actions is incomplete. Keep the commanded pose and fingers while observing.', {'hold': 'Observe one bounded action interval'})
    return questions


def canonical_motor_state(state):
    """One unit system per channel; remove task semantics from the local model."""
    channels = {}
    for arm, fields in state['arms'].items():
        for name, axis in fields['axes'].items():
            channels[arm+'_'+name] = dict(current=0, target=round(axis['error']*1000, 3),
                deadband=round(axis['tolerance']*1000, 3),
                unit='millimetres' if name in 'xyz' else 'milliradians')
        if fields['gripper'] != 'hold':
            channels[arm+'_gripper'] = dict(command=fields['gripper'], ready=fields['gripper_ready'],
                                            observed_opening=fields['opening'])
    return dict(endpoint_ready=state['ready'], motor_channels=channels)


COMPACT_PROMPT = '''You are GPT-6. Author a task-independent relational stage plan for the current RoboDojo simulation.
You own object identity, geometry, interaction design, sequence, coordination, verification, recovery and budget.
Official Jev owns only local signed motor channels, fingers and advance when your measured endpoint is ready.
Return JSON satisfying the supplied StagePlan schema. No executable code or native-success declaration.

CURRENT physical_features, variables and RGB are evidence. Retain first-observed identity and irreversible
counts/order in completed_stages. Recheck reversible geometry. Prior planning prose is a hypothesis when
current measurements contradict it. Native-positive experience passed independently in its recorded scene:
use compatible measured relational designs as the starting point, re-grounding bindings and geometry and
explaining necessary changes. execution_protocol supplies historical inherited defaults and stage overrides.
Past failed diagnostics do not invalidate later validated designs. You author the new plan; no trace is replayed.

task_acceptance must express the EXACT public final intervals using available measurements, including any
release, orientation and return obligations. Internal motion waypoints may have recoil margin; final checks
must retain the public region. A satisfied region needs retention and remaining obligations, not exact point
coincidence. Spatial completion is reversible. Lists, closed fingers and old successful episodes do not prove success.

Expressions use now (live), entry (this stage's frozen start), home (reset) and actions, with + - * / **2 abs min max sqrt hypot.
Use only supplied variable paths. Predicate thresholds are numeric literals: move variable thresholds into the
expression. World points are motion coordinates; point_local_xyz differences implement object-local relations.
Observed grasp/bbox points are absolute world coordinates and geometric references, never proof of a contact.
reference=tcp is the nominal gripper_bias point; wrist is link6; joints is j0..j5. Tip/finger extents are measured
collision geometry. Choose contacts and clearance using their actual frame and shape, including empty interiors.
For an intended tip position, convert with observed tcp-tip offsets. A fingertip can reach support while TCP remains above it.

target contains all 3 Cartesian/6 joint expressions or exactly one per selected axis, in axes order. Empty axes
retain position. Unselected axes retain entry wrist coordinates; inspect tip consequences when changing frame.
orientation=entry/home retains/restores the frame; frame uses world approach=local +X and closing=local +Y.
Choose the equivalent closing sign nearest the current frame. Normally separate rotation and translation,
with clearance before large rotation. Read-only endpoint IK checks do not advance time or prove grasp/collision validity.
Revise unreachable endpoints rather than repeating them. Explicit bounded waiting advances moving-source time.

Use short physical relations: contact approach, commanded closure/settling, following verification, transport,
release and withdrawal are distinct when their outcomes differ. Finger-only close needs at least 3 actions,
open/release at least 2; honor gripper_settle_actions and epsilon. A partially open stopped jaw may hold a wide
object, so closure is NOT holding. Prove following in a bounded test and continue checking it during held transport.
For deforming/articulating objects, select a justified invariant rather than assuming a distant landmark is rigid.
Frozen material references follow an observed mesh vertex only after closure settles; they do not prove that vertex
is captured. Verify nearby material movement and distance. Supported push/slide/transfer is an alternative interaction
to plan and measure explicitly; do not relabel a failed pinch or simply weaken its guard. Inspect contact, depth,
frame, displacement and current destination relations before repeating a failed operation. Keep tracking active
during closure when the source itself moves. Freeze or stabilize destinations that would move under coupled manipulation.

completion proves the stage's measurable endpoint. pose_and_checks requires hand waypoint and checks;
checks can end contact/event/region probing without exact waypoint coincidence. Every endpoint must be attainable
by that stage, not require a later release/withdrawal. abort describes failure conditions, not desired invariants.
Plan a bounded probe with max_actions; reached pose but false object checks can return you for repair. Explicit
empty-axis waiting is distinct. Capture loss is not automatically task failure if the released region is already valid.

protection_groups identify whole achieved final relations to retain. A stage's protection_group_ids selects the
declared groups stable DURING that interaction; null means all and [] defers notifications. Explain deliberate
deferral during necessary coupled transformation, resume after released/stable observation and recheck all final
relations. Do not protect changing preparation/home goals or hide unexpected attachment failure.

Budget the entire remaining task, recovery and final obligations. Per-stage translation_cap_m, speed and 1..6
ticks are available. ONE selected increment is interpolated across those ticks. Read action_contract: Cartesian
IK caps translation-error norm at 20 mm, rotation at 0.1 rad and joint proposals at 0.05 rad; joints-reference
commands instead use joint_step_rad. Requested caps are not measured progress. Use observed displacement and
consumed ticks; delicate contact may need gentle take-up/smaller increments, while free-space motion can use
larger bounded increments/fewer ticks. Preserve enough travel budget for reset posture when required: joints
targets home.r.<arm>.j0..j5, axes all six, tolerance .04, open fingers is one option. Native home regions may
be reached earlier. Inactive arms retain measured joints and their last finger command, including a deliberate anchor.

planning_contract.mode=milestone_handoffs: describe whole remaining intent, emit only the executable prefix
through ONE next substantive measured milestone, and set observe_after=true only on its last stage.
With non-null max_stages, emit at most that many distinct stages and retain whole intent. Otherwise cover the
whole remaining task, choosing observe_after boundaries where a measured capture/release/interaction changes
what follows; avoid needless handoffs after each alignment. Current measurements, irreversible history and
remaining budget are available after handoff. Include concise reasoning and necessary adaptations.
'''


PROMPT = '''You are GPT-6, the high-level planner of a real RoboDojo SIMULATION, with no physical robot connection.
Generate a complete remaining task plan as relational, machine-checkable motor stages, or revise from observed failures.
When revising, retain already completed irreversible operations and their order from completed_stages. Do not restart
press counts or forget the first observed identity. Prior planning memory records your earlier identity/strategy choices;
check them against current evidence and explicitly correct mistaken assumptions rather than silently losing history.
You own object identity, task order, grasp frame, geometry, motion constraints and completion predicates.
TypeSafe Jev receives only signed residuals of your CURRENT stage and chooses motion signs/fingers or advancement.
It does not see the task images or infer grasp points, stage order, geometry, unknown depth or task semantics.
The runtime has NO task-specific stage generator, grasp policy, motion direction selector or reward input.
Input mode is explicitly privileged physical observation, NOT an RGB-only performance claim. Labels/rewards are excluded.
The object IDs, geometry, keypoints and measured joint fields listed in variables are available; never invent fields.
Object up_x/up_y/up_z are measured world components of the object's local +Z; qw/qx/qy/qz are observed WXYZ.
These can test uprightness when present. Older experience saying orientation is unavailable must not override them.
Output exactly StagePlan JSON schema. target entries are scalar ARITHMETIC expressions using now/entry/home paths.
Also provide task_acceptance: measurable FINAL task relations using now/home expressions, never entry/actions.
These are continuously reported to YOU, not to Jev, and do not end the episode or replace native evaluation.
Use the EXACT public acceptable intervals for final verification; do not shrink or approximate them for margin.
Margin belongs in motion waypoints, not in what counts as an acceptable final state. If measured object goals
are already valid, prioritize release/clearance/home obligations instead of unnecessary object re-grasp/repair.
Record only measurable final relations; irreversible counts/order are retained separately in completed_stages.
Past completion of a spatial relation does NOT make it irreversible: subsequent coupled motion can undo it.
Native-positive experience independently passed the original evaluator in its recorded scene. Re-ground compatible
tested declarative relations and contact/transport designs using CURRENT bindings and measurements, changing what
the new evidence requires. Historical warnings describe the earlier failures they refer to; they do not invalidate
every later positive example. Explain which tested relations fit and which need adaptation. The framework never
automatically replays a historical motor trace; you may reuse a compatible measured relational design in your new plan.
Provide protection_groups for achieved geometric relations that should remain valid during later operations.
Each group has id and acceptance_indices: zero-based indices into task_acceptance. A group arms when ALL
its predicates are satisfied; three consecutive physical actions outside that region request your replanning.
This reports a measured regression, not its cause. It does not select corrective actions or declare success.
Group the whole meaningful region, not isolated bounds that happen to hold before a relation is achieved.
Do not protect preparation/home/finger goals that you intentionally change, or geometric goals you deliberately
need to violate temporarily. Empty groups are allowed when no such protection is appropriate.
Each stage may set protection_group_ids to the declared groups that must remain stable DURING that interaction.
Null monitors every plan group as before; [] pauses regression notifications for that stage. For deliberately
coupled motion, defer only relations expected to change temporarily until a released/stable measured milestone,
and keep unrelated established relations protected. Explain this choice in the objective. Their actual values
remain observed and all final relations still require verification; this does not relax completion or abort guards.
Do not interrupt a physically necessary transformation solely because its intermediate geometry differs from the
final region, and do not use deferral to hide an unexpected lost grasp or a failed final endpoint.
For coupled bodies, retain/stabilize an achieved contact with one arm while manipulating another part if needed.
An inactive arm retains its measured joints and LAST finger command; leaving it closed can maintain an anchor.
Choose release/transfer of that anchor deliberately and verify earlier spatial goals after subsequent manipulation.
Simulation advances ONLY on motor/wait physical steps, not planning or read-only IK probes. If a moving target
is currently outside a feasible contact window, use a bounded observed waiting stage rather than repeatedly
planning/probing the same unreachable pose while expecting time to pass. Keep live tracking active during
closure when the source is moving; a fingers-only stage freezes the hand while that source continues moving.
Omit default-valued optional fields to keep the plan concise. Sparse targets are preferable when only one axis moves.
Example now.o.block_9_1.x, entry.r.right.tcp_z, home.r.left.wrist_x, now.o.block_9_1.max_z.
now is LIVE each decision; entry freezes at stage entry; home freezes at episode reset. Allowed + - * / **2 min max abs sqrt hypot.
Axes numbered 0,1,2. reference=tcp means robot gripper_bias center, wrist means link6; joints means six j0..j5.
The nominal tcp is NOT the distal fingertip. robot.finger_geometry reports URDF collision meshes transformed
by measured finger-link poses, their bounding boxes, distal +X boundary and reach beyond nominal TCP.
tip_x/y/z and finger_min/max_x/y/z are WORLD geometry variables, not contact force or capture evidence.
Use this geometry and images when selecting thin contacts; a fingertip can reach a supporting surface while
the nominal tcp remains above it. Do not demand the nominal tcp touch the surface if fingers already extend
past it. After observed_stagnation, revise the contact offset, orientation or valid completion region rather
than issuing the same blocked waypoint repeatedly. Geometry alone still does not prove capture.
Expression target coordinates use the named reference. Unselected axes retain the entry pose during execution.
Robot kinematic_specs describe measured bases, joint limits and chain lengths. Before a motion stage the runtime
may probe YOUR endpoint with read-only numerical IK. A failed probe requests revision without motion. Numerical IK
success does not certify collisions or grasp contact. A far-forward target may need a shallow forward/downward grasp
approach rather than a vertical downward wrist frame; choose frame and arm from robot geometry and actual evidence.
For object placement you may use live hand-object displacement to align the HELD object, e.g.
now.o.dest.x + now.r.right.tcp_x - now.o.held.x; bottom/top clearance uses actual bbox surfaces.
For held-object clearance use a surface-relative target: now.o.dest.max_z + clearance + now.r.right.tcp_z - now.o.held.min_z.
This accounts for tilted geometry; verify attachment while doing so.
Do NOT use a live hand coordinate plus a constant as a target for a lift: freeze the anchor with entry.
orientation=entry/home retains/restores that frame. orientation=frame needs approach and closing world unit vectors:
local +X points into the grasp, local +Y is finger closing, world +Z is up. Pick the sign of the closing axis nearest
initial orientation (both opposing closing-axis signs are equivalent grasps). Rotation occurs about wrist, not TCP.
Keep translation axes empty when rotating. Raise wrist before large downward rotation, then align TCP.
Observed grasp_x/y/z and min_x/max_x etc are ABSOLUTE WORLD coordinates, NOT offsets. Never add them to object x/y/z.
Named point_x/y/z fields are WORLD motion coordinates. point_local_x/y/z fields express the same current point
in the object's observed coordinate frame. Their differences project world displacement onto object axes.
Use local coordinates when the public relation is defined in object-local X/Y; do not substitute world X/Y.
Do not use point_local_x/y/z directly as WORLD hand targets. World points remain available for all motions.
Use observed grasp_x/y/z when present instead of object origin; otherwise explain the selected grasp offset.
Check grasp_point_provenance: a bounding-box center is only a geometric reference, not evidence of a valid grasp.
Inspect the shape and images to select a physically graspable contact. For hollow or oversized objects the center
can lie in empty space or exceed finger span; choose a suitable rim/contact offset and closing direction yourself.
The measured_gripper_frames/approach_x,y,z/closing_x,y,z expose actual world axes without quaternion arithmetic.
For a narrow wall or rim, closing generally needs to straddle its local thickness rather than follow its tangent;
infer the contact and normal from THIS object's geometry and images. A fixed offset that worked on another size
can lie in this object's hollow interior. Do not treat old offsets or jaw orientation as size-independent grasps.
target has either ALL coordinates (3 Cartesian / 6 joints), or exactly one expression per selected axis in axes order.
target=[] when axes=[] means fingers-only or orientation-only; all translation coordinates retain their entry values.
For a required minimum lift distance, target beyond it by one or two motion increments and verify the actual object
exceeds the requested distance. Reaching a hand waypoint within tolerance does not relax the task instruction.
Each stage should establish ONE short physical relation. Translation and rotation are normally separate.
For a grasp: open, raise for rotation clearance, orient, align XY, descend Z, close, lift with object follow evidence.
Closure is only commanded opening feedback, never proof of holding; abort the lift if hand rises but object does not.
When material_references are present, material_<arm>_xyz and distance follow the SAME observed mesh vertex while
that arm's command remains closed AFTER closure has physically settled. Before settling, or with open commands,
the nearest vertex changes, so identity_frozen=0 and it
is not a temporal correspondence. Pinning a geometric ID does NOT establish capture: prove that this material
actually follows the fingertip during a bounded lift. A distant named landmark can deform or rotate even while
the local pinch remains held; use this near-finger material correspondence and named destination relations for
separate attachment and task-progress checks. The nearest vertex may belong to an ungrasped layer or be far
from the fingers; inspect distance and observed movement, never assume contact from a frozen ID alone.
When action_contract.gripper_settle_actions is positive, closure completion additionally waits for that many
consecutive physical observations with normalized opening change below gripper_settle_epsilon. This permits
a wide captured object to stop the jaws partially open, without treating a closing command as settled motion.
Settled width is still NOT proof of capture; retain separate lift-follow and transport attachment checks.
Separate object placement/release/retreat. Follow actual task instruction, including returning BOTH hands home when required.
For home use reference=joints, targets home.r.<arm>.j0 through j5, axes all six, tolerance .04, rotate=false, open.
Read action_contract.magnitude_mode: fixed mode needs tolerance >= half the fixed increment. In residual_bounded mode
the actuator clips magnitude to the measured absolute residual, with a 1 mm / 1 mrad minimum and the configured cap;
it never chooses or corrects Jev's sign. Use 2..4 mm position tolerance for narrow contacts and .04 rad for precise frames;
coarser free-space stages can use .009 m and .11 rad. Translation and rotation caps are in action_contract.
Do not demand conditions the available state cannot measure. Predicates describe scalar expression threshold comparisons.
Every threshold field must be a NUMERIC LITERAL, never an expression or variable path. If a threshold depends
on observed coordinates, move it into the expression, e.g. expression="now.o.item.z-entry.o.item.z", threshold=0.03.
Partial-stage experience records endpoints from episodes that may have failed later. It is measured evidence
of those specific relations, not whole-task success or an executable expert. Pose and closure alone do not prove capture.
When capture is lost, inspect the actual destination relations: an object already in a valid final region may
need release/withdrawal and verification rather than another full grasp/transport. Choose this from current measurements.
Finger-only stages: min_actions=3 for close and min_actions=2 for open/release; max_actions normally 10.
Motion stages max_actions 15..45 based on travel. Native steps are limited, usually two ticks per action.
Requested motion caps are upper bounds, NOT guaranteed measured progress: the Cartesian RPC solver caps
its translation-error NORM at 0.02 m, rotation-error norm at 0.1 rad and each joint proposal delta at 0.05 rad.
Read the explicit cartesian_ik_* caps in action_contract; multi-axis translation may therefore advance less
than the sum of its requested components. Joint-reference actions bypass this Cartesian proposal and use
joint_step_rad. Interpolation spreads ONE selected joint/Cartesian increment across ticks_per_action native
ticks rather than repeating that increment each tick. Physical tracking can be slower; use measured progress.
Budget travel, recovery, release and final obligations together. When geometry permits, choose fewer interpolation
ticks and larger bounded free-space increments, retaining deliberate slower contact motion where measured evidence
requires it. Do not leave a substantial reference-posture return until less than its observed travel budget remains.
For substantial orientation changes allow enough actions (often 40..65 at one tick), or multiple ticks.
You may set ticks_per_action from 1 to 6 per stage; null uses the configured default. One selected increment is
smoothly interpolated across those native ticks. Fragile contacts may need 3..4 ticks; faster free-space stages can
use 1..2. Count actual native ticks in the WHOLE task budget, including rotations, release and home return.
Use completion predicates to prove intended object displacement, release retention and task relations.
Continue checking attachment during EVERY held-object transport, not only the first lift. An object or garment point
can follow vertically and then slip during horizontal motion. Compare current hand-object/keypoint displacement to
the stage-entry displacement with a bounded abort predicate; do not keep chasing an object after loss of capture.
Choose the tracking invariant from the actual contact. A landmark away from the pinch may rotate, swing or deform
relative to the hand while the contacted material stays held. A rigid Cartesian hand-landmark offset can then
give a false slip alarm. Prefer a bounded Euclidean hand-landmark distance when rotation/deformation is expected,
with allowance justified by the entry contact-to-landmark distance; use available other points and lift evidence
to distinguish plausible articulation from actual loss. Do not simply enlarge guards until a missed grasp passes.
If repeated motion loses following, inspect contact/frame/depth and the task region; try a closer suitable contact,
a supported low route, a deliberate contact transfer or a smaller stage translation_cap_m chosen from measurements.
translation_cap_m optionally overrides the default per-axis cap for THIS stage, between .002 and .025 metres.
Several interpolation ticks spread one selected increment; a smaller cap reduces that increment itself.
translation_speed_m_per_s optionally bounds the NORM of that increment divided by the actual native action interval,
between .03 and .8 m/s. The interpreter scales all selected components together, retaining every Jev-selected sign.
For example, two 10 mm axes at one 40 ms tick request about .35 m/s, even though each axis seems small.
Closure plus a vertical lift does not prove that a pinch tolerates abrupt horizontal acceleration. If local
material following is repeatedly lost, inspect contact and try a slower justified transport, supported route or
gentle take-up before a larger move. Use larger bounded free-space increments to preserve the whole-task budget.
Read native_control_dt_s, measured displacements and consumed ticks; requested speed is an upper bound, not
proof of actual object movement. Longer interpolation intervals also consume native ticks.
Use larger bounded free-space steps where safe and small increments for delicate contact; all use the same Jev
direction interface. A smaller increment does not fix an unreachable endpoint or prove capture.
For coupled/deformable bodies, a live destination may move with the manipulated point. Consider freezing the destination
at entry or stabilizing another observed contact with the other arm. Choose this from evidence; no scripted skill exists.
Choose the physical interaction the goal requires. Held transport needs evidence of continuing attachment.
A supported push, slide or contact transfer can instead be planned and measured as that interaction; do not claim
capture or weaken a failed holding guard just to continue. Ground the new contact, task-region progress and bounded
failure conditions in current geometry. The final task relations, rather than an assumed rigid grasp, own success.
finish_on=pose_and_checks normally requires both the waypoint and all predicates. For contact or event-driven stages,
finish_on=checks stops once measured predicates are satisfied even if a probing waypoint is not reached. Use this for
press/release or waiting for a moving object; it still requires minimum actions and commanded finger conditions.
For a task defined by a geometric acceptable region, use checks to stop when that REGION is reached rather than
requiring exact point coincidence. A reachable valid endpoint is better than pursuing an unnecessarily distant point.
Every completion predicate must be attainable with THIS stage's actions. Do not require effects that need a later
stage first: opening fingers and withdrawing from contact are separate; check settled support/levelness after retreat.
If the configured unmet_pose_actions is positive, a motion stage whose hand targets and finger conditions are
already reached but whose object predicates remain false for that many physical actions returns to you for replanning.
This is missing endpoint evidence, not a success or a diagnosis of contact loss. Inspect grasp, offsets, support,
deformation and predicates. Use an explicit bounded stage with no motion axes for deliberate temporal waiting.
Use a bounded probing target and max_actions, then let measured contact/joint changes stop the stage. Never use an
unreachable contact waypoint with pose_and_checks after a physical joint condition already proves the intended event.
abort predicates are failure conditions, not invariants already false before the stage starts.
All actions consume native physical steps. Do not spend a whole episode testing irrelevant preparation.
Return a JSON plan covering the WHOLE task, using two-arm stages when coordination is needed.
If planning_contract.max_stages is non-null, use receding-stage mode instead: describe the remaining
whole-task intent concisely in reasoning, but emit ONLY the next max_stages executable stages from CURRENT
measurements. Do not compress distinct contact, closure, verification or release operations merely to fit.
After these stages, you will observe again and choose the next stages. Retain irreversible order/counts,
identity and completed history; recheck reversible geometry. task_acceptance still describes the final task,
and protection_groups still protect achieved relations across this short horizon. Account for the remaining
planning rounds and native steps, using that budget for meaningful observed decisions rather than repeated preparation.
Native evaluation is independent; never declare native success. Include concise planning reasoning.
You may set observe_after=true on a substantive measured milestone: after a proved capture, settled release,
or another interaction whose result changes what should happen next. Once that stage completes, Jev hands control
back to you with the measured outcome and current images; an unexecuted suffix is only prior intent. Use these
semantic observation boundaries where future geometry is uncertain, instead of handoffs after every open/align
microstep. Retain global intent, identity, completed irreversible events, remaining native budget and reversible checks.
When planning_contract.mode is milestone_handoffs, describe the whole remaining intent but emit only the prefix
through your NEXT substantive measured milestone, and mark its last stage observe_after=true. Final obligations
can be the last milestone. Choose that boundary from the actual interaction; no fixed stage count is prescribed.
'''
