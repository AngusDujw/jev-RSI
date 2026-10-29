# The gripper is above and slightly right of the leftmost ring; the opponent remains unchanged and center is empty.
# Correct toward the ring and lower partway to inspect alignment before closure.
target = [-0.20, -0.22, 0.84, 0.7071068, 0, 0.7071068, 0]
for i in range(25):
    o,r,terminated,truncated,info=step({'left_ee_pose':target,'right_ee_pose':right_hold,'left_ee_joint_state':[1.0],'right_ee_joint_state':[1.0]})
    if terminated or truncated: break
print(o['state']['left_ee_pose'])
