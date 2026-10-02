"""Bounded press primitive with separate tracking error and perception uncertainty."""
import numpy as np
from task_controller import Controller as TaskController

class Controller(TaskController):
    def _deadzone(self,uncertainty):
        if self.task=='press_by_number' and self.rules.get('bounded_press_cycle'):
            return self.rules.get('tracking_tolerance_m',.002)
        return super()._deadzone(uncertainty)
    def _targets(self):
        targets,u,opening=super()._targets()
        if self.task=='press_by_number' and self.rules.get('bounded_press_cycle'):
            arm=self.plan['arms'][0];normal=np.asarray(self.plan['normal'])
            if self.stage=='press_stroke':targets={arm:self.plan['button_surface']-normal*self.rules['press_depth_m']}
            elif self.stage=='press_retract':targets={arm:self.plan['button_surface']+normal*self.rules['retract_height_m']}
            self.debug['press_tracking_contract']=dict(perception_uncertainty_m=u,tracking_tolerance_m=self._deadzone(u),
                source='measured fixed fixture with bounded normal probing',native_activation_verified=False)
        return targets,u,opening
    def _questions(self,targets):
        questions=super()._questions(targets)
        if self.task=='press_by_number' and self.rules.get('bounded_press_cycle'):
            for q in questions.values():
                q['instructions']+=' The target is an explicitly bounded probe waypoint. Perception uncertainty is separately recorded; use the stated tracking dead zone for waypoint arrival, and do not claim button activation.'
        return questions
