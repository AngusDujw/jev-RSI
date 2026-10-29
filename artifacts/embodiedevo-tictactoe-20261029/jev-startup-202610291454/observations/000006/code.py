# Wrist view now aligns the first ring along one image axis, but it remains to the right along world y.
# Move toward the front of the table at the achieved safe height for a final grasp alignment check.
target=[-0.20,-0.30,0.95,0.7071068,0,0.7071068,0]
for i in range(20):
    o,r,terminated,truncated,info=step({'left_ee_pose':target,'right_ee_pose':right_hold,'left_ee_joint_state':[1.0],'right_ee_joint_state':[1.0]})
    if terminated or truncated: break
print(o['state']['left_ee_pose'])
