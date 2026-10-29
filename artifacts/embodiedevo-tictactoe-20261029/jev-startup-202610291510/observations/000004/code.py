def move_ee(arm, xyz, quat, grip, max_steps=30, tolerance=0.002, min_steps=6):
    o = get_observation()
    s = o['state']
    a = {k:s[k] for k in ('left_ee_pose','right_ee_pose','left_ee_joint_state','right_ee_joint_state')}
    target = list(xyz) + list(quat)
    a[arm+'_ee_pose'] = target
    a[arm+'_ee_joint_state'] = [grip]
    stable = 0
    for i in range(max_steps):
        o,r,t,u,info = step(a)
        if t or u: return o, True
        actual = o['state'][arm+'_ee_pose']
        error = sum((actual[j]-target[j])**2 for j in range(3))**0.5
        stable = stable+1 if error < tolerance else 0
        if i+1 >= min_steps and stable >= 3: break
    print('move',arm,'steps',i+1,'position',o['state'][arm+'_ee_pose'][:3],'error',error)
    return o, False

def hold_measured(steps):
    o = get_observation()
    a = {k:v for k,v in o['state'].items() if k.endswith('joint_state')}
    for i in range(steps):
        o,r,t,u,info = step(a)
        if t or u: return o, True
    return o, False


# The downward approach reached its target, but the wrist view shows lateral ring offset.
# Shift toward the ring and lower slightly, then inspect alignment before closing.
o, ended = move_ee('left',[-0.20,-0.16,0.91],[0.7071068,0,0.7071068,0],1.0,25)
