print(robot.state())
bowl = robot.measure(bowl)
print(bowl)
if robot.state().holding and bowl.size is not None and max(bowl.size) < 0.15:
    offset = np.array(package_offset_xy, dtype=float)
    bottom_below_grasp = float(actual[2]) - package_floor
    if np.linalg.norm(offset) < 0.035 and 0.010 <= bottom_below_grasp <= 0.035:
        placement = (float(bowl.center[0] - offset[0]), float(bowl.center[1] - offset[1]), float(bowl.top + bottom_below_grasp + 0.008))
        print('Placement grasp point:', placement)
        feasible = robot.goto(placement, pitch=110, yaw=0, dry_run=True)
        print(feasible)
        if feasible.ok:
            lower = robot.goto(placement, pitch=110, yaw=0)
            print(lower)
            if lower.ok and robot.state().holding:
                print(robot.gripper('open'))
                h = robot.state().at
                print(robot.goto((h[0], h[1], 0.160), pitch=110, yaw=0))
                cheese = robot.measure(cheese)
                bowl = robot.measure(bowl)
                print(cheese)
                print(bowl)
                print(robot.state())
            else:
                print('Placement descent did not reach a retained release pose; inspect before proceeding.')
robot.look('all', tile=True)