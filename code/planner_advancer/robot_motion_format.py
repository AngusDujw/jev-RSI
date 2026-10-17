"""Alternative lossless presentations of current-robot numerical IK checks."""
from copy import deepcopy
from itertools import product


def present_motion_checks(information, representation='matrix'):
    """Keep all 189 checks, fixed ordering and meanings; never select an action."""
    if representation == 'matrix':
        return deepcopy(information)
    if representation != 'named':
        raise ValueError('Unknown robot IK input representation')
    axes = ('x', 'y', 'z')
    rotation_axes = ('yaw', 'pitch', 'roll')
    signs = ('negative', 'hold', 'positive')
    rows = information['translation_rows']
    columns = information['rotation_columns']
    checks = information['numerical_ik_path_passes']
    expected_columns = [dict.fromkeys(rotation_axes, 'hold')]
    for axis in rotation_axes:
        for sign in ('negative', 'positive'):
            expected_columns.append(dict(dict.fromkeys(rotation_axes, 'hold'), **{axis: sign}))
    if rows != [list(values) for values in product(signs, repeat=3)] or columns != expected_columns:
        raise ValueError('Unexpected robot IK comparison ordering')
    if len(checks) != 27 or any(len(row) != 7 or any(type(value) is not bool for value in row) for row in checks):
        raise ValueError('Invalid robot IK comparison values')
    labels = ['all_rotations_hold'] + [axis+'_'+sign for axis in rotation_axes for sign in ('negative', 'positive')]
    result = {key: deepcopy(value) for key, value in information.items()
              if key not in ('translation_rows', 'rotation_columns', 'numerical_ik_path_passes', 'meaning')}
    result['complete_motion_checks'] = [dict(translation=dict(zip(axes, xyz)),
        rotation_path_passes=dict(zip(labels, row))) for xyz, row in zip(rows, checks)]
    result['meaning'] = (
        'Each record names one complete XYZ choice. Its rotation_path_passes fields report the seven '
        'possible rotation choices combined with exactly that XYZ choice. all_rotations_hold means '
        'yaw, pitch and roll all hold. A field such as pitch_positive means pitch positive and yaw/roll hold. '
        'True means all five interpolated waypoints pass the existing numerical robot IK gate for that '
        'complete combination. False means at least one waypoint fails that same gate and the current '
        'controller would reject that combination before execution. All 189 combinations are retained '
        'in fixed order, without ranking or selecting an action. These checks apply to continue decisions; '
        'advance executes no motion.')
    return result
