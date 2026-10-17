"""Matched current-gripper arrows versus unchanged RGB; identical actor text."""
import hashlib
from pathlib import Path

from libero_inframe_axes import InFrameAxesAPI, overlay_gripper_axes

ARROWS_PROFILE = 'libero-rgb-gripper-pair-arrows-v1'
RAW_PROFILE = 'libero-rgb-gripper-pair-raw-v1'
DESCRIPTION_FILE = Path(__file__).with_name('libero_gripper_pair_description_v1.txt')


class PairedArrowsAPI(InFrameAxesAPI):
    profile = ARROWS_PROFILE
    condition = 'matched_current_gripper_arrows'
    draw_arrows = True

    def input_audit(self):
        # The common dispatcher supplies this field itself. Keep it in the
        # archived preview metadata, but never duplicate a dispatcher keyword.
        audit = dict(self.last_input_metadata)
        audit.pop('experience_injection', None)
        return audit

    def transform_views(self, views, robot):
        if self.draw_arrows:
            folder = self.asset_root/'gripper-inputs'
            folder.mkdir(exist_ok=True)
            for view in views:
                raw, _, audit = overlay_gripper_axes(view['raw'], view['camera_to_world'],
                    view['K'], robot['robot0_eef_pos'], view['camera'])
                path = folder/f'{view["native_observation_counter"]:06d}-{self.calls:04d}-{view["camera"]}.png'
                path.write_bytes(raw)
                view.update(original_rgb_path=view['rgb_path'], rgb_path=str(path), raw=raw,
                    sha256=hashlib.sha256(raw).hexdigest(), overlay_audit=audit)
        # Captions and all other actor text are exactly the same in both arms.
        return views

    def payload_from_views(self, sent, views, robot):
        payload = super().payload_from_views(sent, views, robot)
        if payload is not None:
            description = DESCRIPTION_FILE.read_text()
            payload['input'][0]['content'].insert(1, dict(type='input_text', text=description))
            self.last_input_metadata.update(arrows_drawn=self.draw_arrows,
                axis_origin_uses_current_own_gripper_position=self.draw_arrows,
                axis_description_sha256=hashlib.sha256(description.encode()).hexdigest())
            self.validate_payload(payload)
        return payload


class PairedRawAPI(PairedArrowsAPI):
    profile = RAW_PROFILE
    condition = 'matched_unmodified_rgb'
    draw_arrows = False
