"""Task1252 transfer with the frozen coarse-X interface and its own Pro plan."""
import json
from pathlib import Path

from legacy_decisions import english
from libero_hybrid_vision import HybridAPI

PLAN_FILE=Path(__file__).with_name('plans')/'libero_hybrid_cabinet_x_v2.json'


class CabinetHybridAPI(HybridAPI):
    def __init__(self,cfg,log,role):
        if int(log.__self__.cfg['task_id'])!=1252:
            raise ValueError('Cabinet hybrid is declared only for task1252')
        super().__init__(cfg,log,role)
        self.plan=json.loads(PLAN_FILE.read_text());english(self.plan)
