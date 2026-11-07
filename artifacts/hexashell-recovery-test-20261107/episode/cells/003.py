cheese = robot.measure(cheese)
print(cheese)
cheese_before = tuple(cheese.center)
grasp_xyz = (cheese.center[0], cheese.center[1], 0.002)
move = robot.goto(grasp_xyz, pitch=90, yaw=0)
print(move)
if move.ok:
    grasp = robot.gripper('close')
    print(grasp)
    if grasp.holding:
        lift = robot.goto((grasp_xyz[0], grasp_xyz[1], 0.145), pitch=90, yaw=0)
        print(lift)
        cheese_after = robot.measure(cheese)
        print(cheese_after)
        print(robot.state())
    else:
        print('The fingers did not retain a package; inspect before retrying.')
robot.look('all', tile=True)