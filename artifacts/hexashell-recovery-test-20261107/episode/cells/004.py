package_reference = np.array(cheese_before, dtype=float)
package_floor = -0.012

def refresh_package():
    global cheese
    cheese = robot.measure(cheese)
    state = robot.state()
    print(cheese)
    print(state)
    valid = cheese.size is not None and cheese.center is not None
    return {'state': state, 'target': cheese, 'valid': valid}

def package_lift_verified(obs):
    if not obs['valid']:
        return False
    p = np.array(obs['target'].center)
    h = np.array(obs['state'].at)
    return bool(obs['state'].holding and p[2] > package_reference[2] + 0.055 and np.linalg.norm(p[:2] - h[:2]) < 0.065)

def low_package_available(obs):
    if not obs['valid'] or obs['state'].holding:
        return False
    p = np.array(obs['target'].center)
    return bool(np.linalg.norm(p[:2] - package_reference[:2]) < 0.045 and obs['target'].top < 0.025 and max(obs['target'].size) < 0.13)

def current_pose_encloses(obs):
    if not low_package_available(obs):
        return False
    p = np.array(obs['target'].center)
    h = np.array(obs['state'].at)
    return bool(abs(h[0] - p[0]) < 0.025 and abs(h[1] - p[1]) + 0.037 / 2 + 0.004 < 0.077 / 2 and package_floor + 0.010 <= h[2] <= obs['target'].top + 0.004)

def close_and_lift():
    grasp_result = robot.gripper('close')
    print(grasp_result)
    if grasp_result.holding:
        h = robot.state().at
        print(robot.goto((h[0], h[1], 0.145), pitch=90, yaw=0))

def pinch_current_pose(obs):
    close_and_lift()

def recenter_above_table(obs):
    p = np.array(obs['target'].center)
    h = obs['state'].at
    raised = robot.goto((h[0], h[1], max(h[2], 0.045)), pitch=90, yaw=0, grip='open')
    print(raised)
    if not raised.ok:
        return
    target = (float(p[0]), float(p[1]), max(package_floor + 0.017, float(obs['target'].top) - 0.001))
    descent = robot.goto(target, pitch=90, yaw=0)
    print(descent)
    if descent.ok:
        close_and_lift()

methods = {
    'pinch_current_pose': {
        'description': 'Close at the present low pose only when the measured package fits between the open fingers with lateral clearance, then lift vertically to inspect whether the package rose.',
        'eligible': current_pose_encloses,
        'run': pinch_current_pose,
        'max_uses': 1
    },
    'recenter_above_table': {
        'description': 'Raise clear of the table, open and realign over the measured package at a slightly higher grasp height, then close and lift if the descent reaches its target.',
        'eligible': low_package_available,
        'run': recenter_above_table,
        'max_uses': 1
    }
}
recovery_result = robot.recover(methods, observe=refresh_package, resolved=package_lift_verified, context={'goal': 'Grasp and lift the blue cream cheese package for transfer to the bowl', 'target': 'cream cheese package', 'previous_motion': 'The descent ended short of its requested pose; no close command has been executed.'}, max_attempts=2)
print(recovery_result)
robot.look('all', tile=True)