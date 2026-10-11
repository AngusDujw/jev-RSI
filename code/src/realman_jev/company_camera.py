"""Robot-only calibrated image geometry; accepts no scene objects or depth."""
import numpy as np
from scipy.spatial.transform import Rotation


def project(point, calibration, origin):
    camera_point = np.linalg.inv(calibration["camera_to_world"]) @ np.r_[np.asarray(point)+origin, 1.]
    optical = camera_point[:3] * [1., -1., -1.]
    if optical[2] <= 1e-5:
        return None
    pixel = (np.asarray(calibration["intrinsic"]) @ optical)[:2] / optical[2]
    return pixel / np.asarray(calibration["size"])


def robot_image_geometry(positions, quaternions, calibration, origin, offsets):
    views = {}
    for camera, parameters in calibration.items():
        arms = {}
        for i, arm in enumerate(("left", "right")):
            q = np.asarray(quaternions[i])
            point = np.asarray(positions[i]) + Rotation.from_quat(q[[1, 2, 3, 0]]).apply([offsets[i], 0., 0.])
            uv = project(point, parameters, origin)
            record = dict(nominal_grasp_uv01=None if uv is None else uv.round(5).tolist(),
                          inside_image=bool(uv is not None and np.all((uv >= 0) & (uv <= 1))))
            if camera == "cam_high" and uv is not None:
                responses = {}
                for axis, name in enumerate("xyz"):
                    shifted = point.copy()
                    shifted[axis] += .01
                    nxt = project(shifted, parameters, origin)
                    responses[name] = None if nxt is None else (nxt-uv).round(6).tolist()
                record["image_delta_for_positive_1cm_world_translation"] = responses
            arms[arm] = record
        views[camera] = dict(size=parameters["size"], robot=arms,
            response_validity="Static calibrated head camera; local projection of robot point" if camera == "cam_high"
                else "Wrist camera moves with arm; no fixed-camera translation response is assumed")
    return dict(source="known camera calibration + robot encoder/FK geometry only; no object positions, depth or reward",
        nominal_grasp_offset_along_link6_x_m=offsets, views=views,
        caution="Projected nominal grasp reference is not measured finger contact. Pixel alignment alone does not establish depth alignment.")
