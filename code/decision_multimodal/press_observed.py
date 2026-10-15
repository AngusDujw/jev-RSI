"""Independent RGB observer and one latched world pressing reference."""
import json
from pathlib import Path
import press_full
from robodojo_episode import save


def run(ep):
    save(ep.folder/'observed_press_plan.json',json.loads(Path(__file__).with_name('plans').joinpath('press_observed_v1.json').read_text()))
    press_full.run(ep,balanced=True,independent_observer=True,anchored=True)
