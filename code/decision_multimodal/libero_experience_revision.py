"""Run the existing actor with a pinned, bounded question-input skill snapshot."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import runpy
import sys

from experience_harness import context, digest, validate
from legacy_decisions import english


def revise_questions(sent, contract):
    revised = deepcopy(sent)
    state = revised['state']
    stage = state.get('stage', {}).get('stage_key')
    if stage not in ('align_source_above_receiver', 'lower_to_place'):
        return revised
    purpose = state.get('request_purpose')
    if (purpose == 'multimodal_reference_selection' and stage == 'align_source_above_receiver'
            and contract.get('transport_reference_instructions') and 'reference' in revised['questions']):
        revised['questions']['reference']['instructions'] = contract['transport_reference_instructions']
    if purpose == 'multimodal_reference_selection' and 'receiver' in revised['questions']:
        revised['questions']['receiver']['instructions'] = contract['receiver_instructions']
    if purpose in ('multimodal_policy', 'multimodal_rotation_gripper_transition'):
        # Numeric axes are already decided in the preceding scoped request and
        # removed from these questions. Do not edit that numeric path or answer.
        numeric = state.get('numeric_axis_decisions', {})
        for axis in ('x', 'y'):
            if axis in revised['questions'] and axis not in numeric:
                revised['questions'][axis]['instructions'] = contract['visual_' + axis + '_instructions']
                revised['questions'][axis]['criteria'] = dict(contract['visual_choice_descriptions'])
    return revised


def revise_reference_header(payload, sent, contract):
    """Keep a provisional transport question consistent with its image header."""
    state = sent['state']
    header = contract.get('transport_reference_header')
    if (not header or state.get('request_purpose') != 'multimodal_reference_selection'
            or state.get('stage', {}).get('stage_key') != 'align_source_above_receiver'):
        return payload
    revised = deepcopy(payload)
    matches = 0
    for message in revised['input']:
        for part in message['content']:
            if (part['type'] == 'input_text'
                    and part['text'].startswith('Select physical features from CURRENT images')):
                part['text'] = header
                matches += 1
    if matches != 1:
        raise ValueError('Transport reference header contract no longer matches the actor payload')
    return revised


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--experience-snapshot', type=Path, required=True)
    parser.add_argument('--experience-sha256', required=True)
    parser.add_argument('--frozen-source', type=Path, required=True)
    parser.add_argument('--frozen-source-sha256', required=True)
    parser.add_argument('--experience-mode', choices=['skill_only', 'skill_and_lessons'], required=True)
    parser.add_argument('--rotation-strategy-file', type=Path)
    parser.add_argument('--rotation-strategy-sha256')
    args, remaining = parser.parse_known_args()
    task_parser = argparse.ArgumentParser(add_help=False)
    task_parser.add_argument('--task', type=int, required=True)
    task_args, _ = task_parser.parse_known_args(remaining)
    strategy = None
    if args.rotation_strategy_file:
        if task_args.task != 1458 or digest(args.rotation_strategy_file) != args.rotation_strategy_sha256:
            raise ValueError('Posture strategy task or frozen hash differs')
        strategy = json.loads(args.rotation_strategy_file.read_text())
        english(strategy)
        if (set(strategy['choice_descriptions']) != {'positive', 'negative', 'hold'}
                or set(strategy['readiness_choices']) != {'ready', 'not_ready', 'unclear'}):
            raise ValueError('Posture strategy cannot change categorical options')
        if (not all(isinstance(strategy.get(key), str) and strategy[key] for key in (
                'posture_preparation_goal', 'current_phase_readiness_question', 'axis_question_template'))
                or '{axis}' not in strategy['axis_question_template']
                or not isinstance(strategy.get('common_instructions'), list)
                or not all(isinstance(line, str) for line in strategy['common_instructions'])):
            raise ValueError('Incomplete planner posture contract')
    elif args.rotation_strategy_sha256:
        raise ValueError('Missing frozen posture strategy file')
    validate(args.experience_snapshot, args.experience_sha256)
    source = args.frozen_source.resolve()
    if digest(source) != args.frozen_source_sha256:
        raise ValueError('Native actor source changed')
    contract_path = args.experience_snapshot / 'harness/skills/question_contract.json'
    contract = json.loads(contract_path.read_text())
    skill = runpy.run_path(str(args.experience_snapshot / 'harness/skills/question_skill.py'))['revise_questions']
    if set(contract['visual_choice_descriptions']) != {'positive', 'negative', 'hold'}:
        raise ValueError('Question skill cannot change the motor categories')
    sys.path.insert(0, str(source.parent))
    namespace = runpy.run_path(str(source), run_name='pinned_actor_with_experience')
    from libero_budget_audit import install
    install(remaining)
    cls = namespace['DirectAPI']
    original_build, original_audit = cls.build_payload, cls.input_audit
    original_post = cls.post

    def post(self, endpoint, sent):
        if strategy is None:
            return original_post(self, endpoint, sent)
        if digest(args.rotation_strategy_file) != args.rotation_strategy_sha256:
            raise ValueError('Frozen posture strategy changed')
        from libero_posture_strategy import revise_rotation, revise_phase, separate_readiness
        revised = revise_rotation(sent, strategy)
        revised = revise_phase(revised, getattr(self, 'actor_posture_readiness', None), self.tick, strategy)
        answer = original_post(self, endpoint, revised)
        if sent['state'].get('request_purpose') == 'multimodal_rotation_axes':
            answer, self.actor_posture_readiness = separate_readiness(answer, self.tick)
            self.log(dict(kind='actor_posture_readiness', **self.actor_posture_readiness))
        return answer

    def build(self, sent):
        validate(args.experience_snapshot, args.experience_sha256)
        revised = skill(sent, contract)
        payload = revise_reference_header(original_build(self, revised), revised, contract)
        if strategy is not None:
            from libero_posture_strategy import revise_rotation_payload
            payload = revise_rotation_payload(payload, revised, strategy)
        state = sent['state']
        stage = state.get('stage', {}).get('stage_key', '')
        lessons = []
        if args.experience_mode == 'skill_and_lessons' and state.get('request_purpose') in (
                'multimodal_reference_selection', 'multimodal_policy', 'multimodal_rotation_gripper_transition'):
            lessons = context(args.experience_snapshot, task_args.task, stage)
        if lessons:
            payload['input'][0]['content'].insert(0, dict(type='input_text', text=(
                'Historical task lessons, not current measurements:\n' + '\n'.join(lessons))))
        self.log(dict(kind='experience_read', snapshot_sha256=args.experience_sha256,
                      mode=args.experience_mode, stage=stage, native_tick=self.tick,
                      lesson_count=len(lessons), question_skill_changed=revised['questions'] != sent['questions']))
        return payload

    def audit(self):
        result = original_audit(self)
        result.update(experience_snapshot_sha256=args.experience_sha256,
                      experience_mode=args.experience_mode, frozen_source_sha256=args.frozen_source_sha256)
        if strategy is not None:
            result['rotation_strategy_sha256'] = args.rotation_strategy_sha256
        return result

    cls.build_payload, cls.input_audit, cls.post = build, audit, post
    original_save = cls.compact_post.__globals__['save']

    def save(path, value):
        if path.name in ('manifest.json', 'dispatch.json'):
            value = dict(value, experience_injection=args.experience_mode == 'skill_and_lessons',
                         experience_snapshot_sha256=args.experience_sha256,
                         question_skill_applied=True, experience_mode=args.experience_mode)
            if strategy is not None:
                value['rotation_strategy_sha256'] = args.rotation_strategy_sha256
                if path.name == 'manifest.json':
                    value['planner_posture_strategy'] = strategy
                    original_save(path.parent / 'planner-posture-strategy.json', strategy)
        return original_save(path, value)

    cls.compact_post.__globals__['save'] = save
    sys.argv = [str(source), *remaining]
    namespace['main']()


if __name__ == '__main__':
    main()
