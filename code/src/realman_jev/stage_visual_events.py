"""Camera-only relative landmark cycles; no simulator joints or rewards."""
from __future__ import annotations


def update_visual_cycle(method, state, objects, tick):
    """Count a measured down/return cycle against a fixed visual landmark."""
    state = dict(state or {})
    state.setdefault('count', 0)
    state.setdefault('phase', 'released')
    state.setdefault('baseline_m', None)
    state.setdefault('press_streak', 0)
    state.setdefault('release_streak', 0)
    if state.get('last_tick') == tick:
        return state
    state['last_tick'] = tick
    state['valid'] = False
    moving, reference = objects.get(method.moving_id), objects.get(method.reference_id)
    if not all(obj is not None and obj.get('position_provenance') ==
               'stereo_RGB_triangulation' and obj.get('position_measurement') is not None
               for obj in (moving, reference)):
        state['press_streak'] = 0
        state['release_streak'] = 0
        return state
    axis = 'xyz'.index(method.axis)
    relative = float(moving['position_m'][axis] - reference['position_m'][axis])
    state['relative_m'] = relative
    state['valid'] = True
    if state['baseline_m'] is None:
        state['baseline_m'] = relative
        return state
    sign = 1. if method.press_direction == 'increase' else -1.
    displacement = sign * (relative - state['baseline_m'])
    state['displacement_m'] = displacement
    if state['phase'] == 'released':
        state['press_streak'] = (state['press_streak'] + 1
                                 if displacement >= method.press_delta_m else 0)
        if state['press_streak'] >= method.confirmations:
            state['phase'] = 'down'
            state['press_streak'] = 0
            state['release_streak'] = 0
    else:
        state['release_streak'] = (state['release_streak'] + 1
                                   if displacement <= method.release_delta_m else 0)
        if state['release_streak'] >= method.confirmations:
            state['count'] += 1
            state['phase'] = 'released'
            state['release_streak'] = 0
            state['baseline_m'] = .8 * state['baseline_m'] + .2 * relative
    return state
