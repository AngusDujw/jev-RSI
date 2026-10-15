"""Cold full button pipeline; no resumed exploratory presses or manual waits."""
import press_setup
import press_first
import press_sequence
from robodojo_episode import save


def run(ep,balanced=False,independent_observer=False,anchored=False,differential=False):
    ep.balanced_button_pair=balanced
    ep.independent_button_observer=independent_observer
    ep.anchored_button_reference=anchored
    ep.differential_button_observer=differential
    if not press_setup.run(ep,continue_immediately=True):
        return
    if independent_observer:
        from press_observer import prepare
        cap=json_load_cap(ep)
        if not prepare(ep,cap,'right','red1',closed_tool=False):
            save(ep.folder/'program_result.json',dict(program_finished=False,stop_reason='Independent first-red cap observation unavailable'))
            return
    save(ep.folder/'cold_sequence_protocol.json',dict(
        scope='Single development episode, not frozen validation',
        intervention='SAM visible-cap measurements from the first press; full27mm release target also for red1; no earlier long endpoint-stall attempts',
        visual_counts_are_native_counts=False,actor_images=0,experience_injection=False))
    result=press_first.run(ep,dict(return_to_sequence=True,release_extra_gap_m=.020,balanced_pair=balanced,
        anchored_world_reference=anchored,
        adaptive_press_endpoint=differential,
        independent_observer_arm='right' if independent_observer else None,
        refine_unpressed_baseline=True,require_refined_baseline=True))
    if ep.ended:
        return
    if not result or result.get('completed_proxy_cycles')!=1:
        save(ep.folder/'program_result.json',dict(program_finished=False,
            stop_reason=(result or {}).get('stop_reason','First visual cycle incomplete')))
        return
    press_sequence.run(ep)


def json_load_cap(ep):
    import json
    return json.loads((ep.folder/'button_geometry.json').read_text())['caps']['red_1']
