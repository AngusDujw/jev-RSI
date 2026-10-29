# The opponent has remained at its initial pose across a five-step hold, and the board is empty.
# Approach above the leftmost ring with a downward gripper to calibrate the grasp from the wrist camera.
o = get_observation()
right_hold = o['state']['right_ee_pose'].copy()
target = [-0.16, -0.18, 0.92, 0.7071068, 0, 0.7071068, 0]
for i in range(35):
    o,r,terminated,truncated,info=step({'left_ee_pose':target,'right_ee_pose':right_hold,'left_ee_joint_state':[1.0],'right_ee_joint_state':[1.0]})
    if terminated or truncated: break
print(o['state']['left_ee_pose'])
