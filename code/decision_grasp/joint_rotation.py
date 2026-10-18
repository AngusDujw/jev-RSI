"""Proposed lossless seven-choice rotation encoding; no action projection."""


def questions_with_joint_rotation(axis_questions):
    result=[]
    for arm in ('left','right'):
        result.extend(q for q in axis_questions if q['name'] in [f'{arm}_{a}' for a in ('x','y','z')])
        choices=[dict(value='hold',description='Hold all three rotation channels.')]
        for axis,world_axis in (('yaw','Z'),('pitch','X'),('roll','Y')):
            for direction in ('negative','positive'):
                choices.append(dict(value=axis+'_'+direction,
                    description=f'Apply {direction} 0.10 rad about world {world_axis} around the TCP; hold the other two rotation channels.'))
        result.append(dict(type='choice',name=f'{arm}_rotation',
            instructions=f'Select the single rotation for the {arm} arm in this joint action, or hold orientation. Use the current RGB, measured geometry and task. Translation may accompany this rotation.',
            choices=choices))
        result.extend(q for q in axis_questions if q['name']==f'{arm}_gripper')
    return result


def expand_rotation_choices(answers):
    expected={f'{arm}_{field}' for arm in ('left','right') for field in ('x','y','z','rotation','gripper')}
    if set(answers)!=expected:raise ValueError('Unexpected joint-rotation answer names')
    result={k:v for k,v in answers.items() if not k.endswith('_rotation')}
    for arm in ('left','right'):
        selected=answers[f'{arm}_rotation']
        valid={'hold'}|{a+'_'+s for a in ('yaw','pitch','roll') for s in ('negative','positive')}
        if selected not in valid:raise ValueError('Unknown rotation choice')
        for axis in ('yaw','pitch','roll'):result[f'{arm}_{axis}']='hold'
        if selected!='hold':
            axis,direction=selected.split('_')
            result[f'{arm}_{axis}']=direction
    return result
