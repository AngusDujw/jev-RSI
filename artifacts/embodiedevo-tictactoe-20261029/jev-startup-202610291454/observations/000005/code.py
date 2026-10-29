# The last target was not reached and the fingertips appear at table level.
# Recover a vertical pose with clearance, then align toward the ring before another height check.
for target,n in [([-0.20,-0.22,1.02,0.7071068,0,0.7071068,0],20),([-0.20,-0.15,0.95,0.7071068,0,0.7071068,0],20)]:
    for i in range(n):
        o,r,terminated,truncated,info=step({'left_ee_pose':target,'right_ee_pose':right_hold,'left_ee_joint_state':[1.0],'right_ee_joint_state':[1.0]})
        if terminated or truncated: break
    if terminated or truncated: break
print(o['state']['left_ee_pose'])
