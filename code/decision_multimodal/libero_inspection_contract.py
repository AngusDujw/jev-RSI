"""Scope final inspection to visual persistence, not alignment-point offsets."""
from copy import deepcopy
from string import Formatter

FACTOR_NAMES={'support_location','persistence','hand_separation'}


def final_visual_request(sent):
    state=sent['state']
    return (state.get('request_purpose')=='visual_stage_classification'
        and state.get('stage',{}).get('stage_key')=='inspect'
        and 'next_phase' in state and state['next_phase'] is None)


def validate_inspection_contract(strategy):
    factor=strategy.get('inspection_factor_contract')
    if factor is not None:
        if (not isinstance(factor,dict) or not all(isinstance(factor.get(k),str) and factor[k].strip()
                for k in ('observer_header','final_header','final_question_template'))
                or not isinstance(factor.get('observer_questions'),dict)
                or set(factor['observer_questions'])!=FACTOR_NAMES
                or not isinstance(factor.get('final_choice_descriptions'),dict)
                or set(factor['final_choice_descriptions'])!={'advance','continue','restart'}
                or not all(isinstance(v,str) and v.strip() for v in factor['final_choice_descriptions'].values())):
            raise ValueError('Invalid final visual-factor contract')
        for q in factor['observer_questions'].values():
            if (not isinstance(q.get('instructions'),str) or not q['instructions'].strip()
                    or not isinstance(q.get('criteria'),dict) or 'uncertain' not in q['criteria']
                    or not all(isinstance(k,str) and isinstance(v,str) and v.strip() for k,v in q['criteria'].items())):
                raise ValueError('Every visual factor needs categorical choices including uncertainty')
        fields=set()
        for _,field,spec,conversion in Formatter().parse(factor['final_question_template']):
            if field is not None:
                if field not in FACTOR_NAMES or spec or conversion:
                    raise ValueError('Unsupported final factor-template field')
                fields.add(field)
        if fields!=FACTOR_NAMES:
            raise ValueError('Final factor question must receive all three actual model choices')
    contract=strategy.get('inspection_contract')
    if contract is None:
        return
    if (not isinstance(contract,dict) or contract.get('exclude_alignment_point_offsets') is not True
            or not all(isinstance(contract.get(k),str) and contract[k].strip()
                       for k in ('final_header','final_question'))
            or not isinstance(contract.get('final_choice_descriptions'),dict)
            or set(contract['final_choice_descriptions'])!={'advance','continue','restart'}
            or not all(isinstance(v,str) and v.strip() for v in contract['final_choice_descriptions'].values())):
        raise ValueError('Invalid final-inspection question contract')


def revise_inspection(sent,strategy):
    state=sent['state'];contract=strategy.get('inspection_contract')
    if (contract is None or state.get('request_purpose')!='visual_stage_classification'
            or state.get('stage',{}).get('stage_key')!='inspect'
            or 'next_phase' not in state or state['next_phase'] is not None):
        return sent
    validate_inspection_contract(strategy)
    if set(sent['questions'])!={'transition'}:
        raise ValueError('Final inspection must retain its sole categorical transition question')
    revised=deepcopy(sent)
    revised['state']['formal_stage_input']=contract['final_header']
    question=revised['questions']['transition']
    question['instructions']=contract['final_question']
    if set(question['criteria'])!={'advance','continue','restart'}:
        raise ValueError('Final inspection cannot change transition categories')
    question['criteria']={k:contract['final_choice_descriptions'][k] for k in question['criteria']}
    return revised


def factor_observer(sent,strategy):
    contract=strategy.get('inspection_factor_contract')
    if contract is None or not final_visual_request(sent):
        return None
    validate_inspection_contract(strategy)
    if set(sent['questions'])!={'transition'}:
        raise ValueError('Unexpected terminal request')
    result=deepcopy(sent)
    result['state']['formal_stage_input']=contract['observer_header']
    result['questions']={name:dict(type='choice',instructions=q['instructions'],criteria=dict(q['criteria']))
                         for name,q in contract['observer_questions'].items()}
    return result


def factor_transition(sent,observed,strategy):
    """Copy model-produced visual categories; the second model call decides transition."""
    contract=strategy['inspection_factor_contract']
    if not final_visual_request(sent) or set(observed['answers'])!=FACTOR_NAMES:
        raise ValueError('Final transition requires this observation batch of visual answers')
    text=contract['final_question_template']
    for name in FACTOR_NAMES:
        answer=observed['answers'][name]
        if not isinstance(answer,dict) or 'choice' not in answer:
            raise ValueError('Missing or refused visual factor; do not fabricate a category')
        choice=answer['choice']
        if choice not in contract['observer_questions'][name]['criteria']:
            raise ValueError('Unknown visual category; do not replace an actual answer')
        text=text.replace('{'+name+'}',choice)
    result=deepcopy(sent)
    result['state']['request_purpose']='formal_stage_classification'
    result['state']['formal_stage_input']=contract['final_header']
    question=result['questions']['transition']
    if set(question['criteria'])!={'advance','continue','restart'}:
        raise ValueError('Final factor contract cannot change transition categories')
    question['instructions']=text
    question['criteria']={k:contract['final_choice_descriptions'][k] for k in question['criteria']}
    return result
