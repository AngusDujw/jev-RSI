"""GPT-selected references to measured contracts; never select motor actions."""
from __future__ import annotations

import ast
from copy import deepcopy
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field
from .stage_ir import Stage, StagePlan, Predicate, GoalProtection


class StageReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reuse_contract_id: str = Field(min_length=1, max_length=100)
    object_bindings: dict[str, str] = Field(default_factory=dict, max_length=32)
    id: str | None = None
    objective: str | None = None
    observe_after: bool | None = None
    protection_group_ids: list[str] | None = Field(default=None, max_length=32)
    requires_acceptance_indices: list[int] | None = Field(default=None, max_length=128)
    min_actions: int | None = Field(default=None, ge=0, le=10)
    max_actions: int | None = Field(default=None, ge=1, le=100)
    ticks_per_action: int | None = Field(default=None, ge=1, le=6)
    translation_cap_m: float | None = Field(default=None, ge=.002, le=.025)
    translation_speed_m_per_s: float | None = Field(default=None, ge=.03, le=.8)
    arm_tolerances: dict[Literal['left', 'right'], Annotated[float, Field(ge=.002, le=.04)]] | None = None
    finish_on: Literal['pose_and_checks', 'checks'] | None = None


class CatalogStagePlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reasoning: str
    stages: list[Stage | StageReference] = Field(min_length=1, max_length=80)
    task_acceptance: list[Predicate] = Field(default_factory=list, max_length=128)
    protection_groups: list[GoalProtection] = Field(default_factory=list, max_length=32)


CATALOG_INSTRUCTION = '''You may emit a full new Stage or explicitly choose a
reuse_contract_id attached to a measured contract in prior_experience. This
augmented schema permits references even when generic instructions show a full
Stage. Prefer a compatible measured contract over needlessly rewriting its
arithmetic, while treating current contact and endpoint evidence as authoritative.
YOU choose
the sequence, whether a reference fits current evidence, and necessary new stages.
A reference preserves that contract's expressions, endpoints, aborts and frames.
Its entry/now/home are rebound to THIS execution; no historical pose, measured
endpoint, capture label, motor action or trajectory is replayed. A successful
episode does not make every referenced grasp successful in the current state.
object_bindings explicitly maps historical object IDs to observed current IDs;
only the object segment in now.o / entry.o / home.o paths is substituted. It does
not swap arms, invent fields or change predicates. For changed targets, contact
designs or endpoint predicates, emit a full new Stage. For a compatible contract
whose old pose tolerance is physically overstrict in THIS observation, you may
set arm_tolerances for specific referenced arms. You may set finish_on=checks only
when the existing measured completion predicates themselves prove this stage's
physical event or acceptable region; this never changes task_acceptance or
allows a failed capture to pass. Otherwise emit a full new Stage. A reference may
override its ID, objective, action limits, increments, observation boundary and
protection_group_ids; declare current plan groups or explicitly reset that scope.
Compare the example execution_protocol with the current action_contract: omitted
caps inherit CURRENT defaults, not historical defaults. Preserve what fits, and
explain any altered ordering or bilateral coordination. Only provided positive
physically executed contracts have IDs. A timeline contract without a recorded
endpoint proves only that its native actions occurred during a successful
episode, not that this stage alone completed or that its current contact will
work. Never cite an abandoned unexecuted suffix or failed strategy.
Your task_acceptance and protection_groups remain current model-authored contracts.
The runtime expands only your explicit references, validates the resulting whole
plan, and otherwise uses the same official JEV and independent native evaluator.'''


def attach_catalog(examples, compact_context=False):
    """Annotate a fresh planner request without changing bank records."""
    annotated = deepcopy(examples)
    catalog = {}
    for i, example in enumerate(annotated):
        if example.get('verified_native_success') is not True:
            continue
        endpoints = list(example.get('executed_stages', []))
        terminal = example.get('native_terminal_action_stage')
        if terminal:
            endpoints.append(terminal)
        for j, endpoint in enumerate(endpoints):
            identifier = f'prior_{i}_contract_{j:03d}'
            contract = Stage.model_validate(endpoint['contract']).model_dump()
            endpoint['reuse_contract_id'] = identifier
            catalog[identifier] = contract
        for j, item in enumerate(entry for entry in example.get('physical_execution_timeline', [])
                                 if 'contract' in entry):
            identifier = f'prior_{i}_contract_{len(endpoints)+j:03d}'
            contract = Stage.model_validate(item['contract']).model_dump()
            item['reuse_contract_id'] = identifier
            catalog[identifier] = contract
        if compact_context:
            # Keep every measured contract and endpoint available for explicit
            # reuse. Historical narrative and terminal state duplicate large
            # parts of the current evidence, and can distract a new planner.
            for key in ('failure_events', 'final_physical_state', 'planning_decisions'):
                example.pop(key, None)
            example['catalog_context_note'] = (
                'Historical narratives and terminal state were omitted; all '
                'measured executed contracts and endpoint checks remain present. '
                'Use current observations to ground this plan.')
    return annotated, catalog


def catalog_schema(catalog):
    if not catalog:
        return StagePlan.model_json_schema()
    schema = CatalogStagePlan.model_json_schema()
    schema['$defs']['StageReference']['properties']['reuse_contract_id']['enum'] = list(catalog)
    return schema


def _bind_objects(contract, bindings, current_object_ids):
    if not bindings:
        return contract
    if any(not old.isidentifier() or not new.isidentifier() or new not in current_object_ids
           for old, new in bindings.items()):
        raise ValueError('Object bindings must map identifiers to observed current object IDs')
    used = set()

    class Binding(ast.NodeTransformer):
        def visit_Attribute(self, node):
            self.generic_visit(node)
            parent = node.value
            if (isinstance(parent, ast.Attribute) and parent.attr == 'o'
                    and isinstance(parent.value, ast.Name)
                    and parent.value.id in ('now', 'entry', 'home') and node.attr in bindings):
                used.add(node.attr)
                node.attr = bindings[node.attr]
            return node

    def bind(text):
        return ast.unparse(Binding().visit(ast.parse(text, mode='eval')))

    for goal in contract['arms'].values():
        goal['target'] = [bind(text) for text in goal['target']]
    for predicate in contract['completion'] + contract['abort']:
        predicate['expression'] = bind(predicate['expression'])
    if used != set(bindings):
        raise ValueError('Object bindings include names absent from the referenced contract: '
                         + ', '.join(sorted(set(bindings) - used)))
    return contract


def expand_catalog_plan(raw, catalog, current_object_ids):
    """Expand only IDs explicitly selected by GPT; validate normal IR afterwards."""
    candidate = CatalogStagePlan.model_validate(raw)
    expanded = candidate.model_dump()
    stages, references = [], []
    for index, stage in enumerate(candidate.stages):
        if isinstance(stage, Stage):
            stages.append(stage.model_dump())
            continue
        if stage.reuse_contract_id not in catalog:
            raise ValueError(f'Unknown measured contract ID {stage.reuse_contract_id!r}')
        contract = _bind_objects(deepcopy(catalog[stage.reuse_contract_id]),
                                 stage.object_bindings, set(current_object_ids))
        overrides = {}
        for key in stage.model_fields_set - {'reuse_contract_id', 'object_bindings', 'arm_tolerances'}:
            value = getattr(stage, key)
            if value is not None or key == 'protection_group_ids':
                overrides[key] = deepcopy(value)
        contract.update(overrides)
        if stage.arm_tolerances is not None:
            for arm, tolerance in stage.arm_tolerances.items():
                if arm not in contract['arms']:
                    raise ValueError(f'Cannot override absent arm {arm!r} in referenced contract')
                contract['arms'][arm]['tolerance'] = tolerance
            overrides['arm_tolerances'] = dict(stage.arm_tolerances)
        stages.append(Stage.model_validate(contract).model_dump())
        references.append(dict(stage_index=index, reuse_contract_id=stage.reuse_contract_id,
                               object_bindings=stage.object_bindings, overrides=overrides))
    expanded['stages'] = stages
    return StagePlan.model_validate(expanded), references
