"""Cold full button pipeline; no resumed exploratory presses or manual waits."""
import press_setup
import press_first
import press_sequence
from robodojo_episode import save


def run(ep):
    if not press_setup.run(ep,continue_immediately=True):
        return
    save(ep.folder/'cold_sequence_protocol.json',dict(
        scope='Single development episode, not frozen validation',
        intervention='SAM visible-cap measurements from the first press; full27mm release target also for red1; no earlier long endpoint-stall attempts',
        visual_counts_are_native_counts=False,actor_images=0,experience_injection=False))
    result=press_first.run(ep,dict(return_to_sequence=True,release_extra_gap_m=.020,
        refine_unpressed_baseline=True,require_refined_baseline=True))
    if ep.ended:
        return
    if not result or result.get('completed_proxy_cycles')!=1:
        save(ep.folder/'program_result.json',dict(program_finished=False,
            stop_reason=(result or {}).get('stop_reason','First visual cycle incomplete')))
        return
    press_sequence.run(ep)
