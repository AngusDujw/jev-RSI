"""Bounded press primitive with separate tracking error and perception uncertainty."""
import numpy as np
from task_controller import Controller as TaskController

class Controller(TaskController):
    def _deadzone(self,uncertainty):
        if self.stage=='press_stroke' and self.rules.get('bounded_press_cycle'):
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
    def _movement(self,targets,uncertainty,opening,obs,ask_jev):
        if self.stage=='press_stroke' and self.rules.get('bounded_press_cycle'):
            arm=self.plan['arms'][0];normal=np.asarray(self.plan['normal'])
            advancement=float(np.dot(self.plan['button_surface']-self.robot[arm]['grasp'],normal))
            if advancement>=.5*self.rules['press_depth_m']:
                self._transition('press_retract',dict(source='measured end-effector normal advancement',
                    normal_advancement_m=advancement,button_activation_verified=False))
                targets,uncertainty,opening=self._targets()
        return super()._movement(targets,uncertainty,opening,obs,ask_jev)

    @staticmethod
    def waypoint_state(state):
        return dict(task=state['task'],instruction=state['instruction'],stage=state['stage'],frame=state['frame'],
            geometry=state['geometry'],robot=state['robot'],constraints=dict(
                max_delta_norm_m=state['constraints']['max_delta_norm_m'],dead_zone_m=state['constraints']['dead_zone_m']),
            reference_contract=dict(kind='requested robot waypoint anchored to initially observed stationary fixture',
                not_a_claim_of_current_object_visibility=True,perception_uncertainty_is_not_waypoint_tracking_error=True,
                motion_bounds_and_contact_limits_checked_by_external_controller=True,
                historical_reference_warning='Do not infer button activation or actual object displacement from the waypoint'),
            native_step=state['native_step'],remaining_steps=state['remaining_steps'],
            active_arms=state['active_arms'],episode_history=state['history'][-3:])
    def _state(self,targets,uncertainty,opening,obs):
        full=super()._state(targets,uncertainty,opening,obs)
        self.debug['full_observation_before_waypoint_query']=full
        state=self.waypoint_state(full)
        state['reference_records']=self.debug.get('fixture_references',[])
        return state
    def _questions(self,targets):
        return {f'{arm}_{axis}':dict(type='choice',instructions=(
            f'For the {arm} robot waypoint in world {axis}, choose the sign of target coordinate minus current grasp coordinate. '
            'Use constraints.dead_zone_m: hold only if absolute coordinate difference is within this tracking dead zone. '
            'This query tracks an explicitly bounded robot waypoint; it does not estimate an object position or decide activation. '
            'Do not choose arm, phase, rotation, opening or task success.'),criteria=dict(
                negative=f'decrease robot {axis} coordinate toward requested waypoint',
                hold=f'zero {axis}: already within tracking dead zone',
                positive=f'increase robot {axis} coordinate toward requested waypoint')) for arm in targets for axis in 'xyz'}
