cheese = robot.measure(cheese)
print(cheese)
print(robot.state())
if cheese.size is not None:
    target_center = np.array(cheese.center, dtype=float)
    target_top = float(cheese.top)
    grasp_target = (float(target_center[0]), float(target_center[1]), max(package_floor + 0.017, target_top - 0.001))
    tilted_pitch = 110
    feasible = robot.goto(grasp_target, pitch=tilted_pitch, yaw=0, dry_run=True)
    print(feasible)
    if feasible.ok:
        descent = robot.goto(grasp_target, pitch=tilted_pitch, yaw=0, grip='open')
        print(descent)
        actual = np.array(robot.state().at, dtype=float)
        aligned = (abs(actual[0] - target_center[0]) < 0.020 and
                   abs(actual[1] - target_center[1]) < 0.010 and
                   package_floor + 0.010 <= actual[2] <= target_top + 0.003)
        if not descent.blocked and aligned:
            grasp = robot.gripper('close')
            print(grasp)
            if grasp.holding:
                print(robot.goto((float(actual[0]), float(actual[1]), 0.145), pitch=tilted_pitch, yaw=0))
                cheese = robot.measure(cheese)
                print(cheese)
                print(robot.state())
            else:
                print('The fingers closed without retaining an object.')
        else:
            print('The actual pose is not suitable for closing; inspect the changed approach.')
robot.look('all', tile=True)