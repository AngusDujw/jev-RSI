# The opponent stayed at its initial pose across a measured hold and the center cell is empty.
# Approach above the leftmost ring to calibrate the downward grasp frame.
o = get_observation()
s = o['state']
a = {'left_ee_pose': [-0.20,-0.20,0.94,0.7071068,0,0.7071068,0], 'right_ee_pose':s['right_ee_pose'], 'left_ee_joint_state':[1.0], 'right_ee_joint_state':s['right_ee_joint_state']}
for i in range(35):
    o,r,t,u,info=step(a)
    if t or u: break
print(o['state'])
