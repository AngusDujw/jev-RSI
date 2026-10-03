"""X5 robot self mask from encoder/FK and robot-only geometry (no object truth).

Bounds are from X5A.urdf joint7/8 origins and link7/8.STL bounds.
This is robot calibration, not task/object-specific geometry.
"""
import numpy as np
from scipy.spatial.transform import Rotation


def robot_pixels(cloud,robot):
    mask=np.zeros(cloud.shape[:2],bool)
    for i in range(2):
        q=np.asarray(robot['eef_quaternions_wxyz'][i],float)
        rot=Rotation.from_quat(q[[1,2,3,0]]).as_matrix()
        p=(cloud-np.asarray(robot['eef_positions'][i]))@rot
        opening=float(robot['states'][7*i+6]);joint=-.01+.054*opening
        # Finger convex bounds; 1mm calibration allowance, no gap-spanning capsule.
        boxes=[([.0705,.024896+joint-.0255,-.0317],[.1586,.024896+joint+.0139,.0314]),
               ([.0705,-.0249-joint-.0139,-.0317],[.1586,-.0249-joint+.0255,.0314]),
               ([-.055,-.045,-.045],[.073,.045,.045])]
        for lo,hi in boxes:mask|=((p>=lo)&(p<=hi)).all(-1)
    return mask
