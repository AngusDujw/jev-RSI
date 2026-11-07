cheese = robot.measure(('agentview', (355, 196)))
print(cheese)
print(bowl)
if cheese.size is not None and max(cheese.size) < 0.16:
    cheese_yaw = cheese.grip_yaw if cheese.grip_yaw is not None else 0
    approach = (cheese.center[0], cheese.center[1], cheese.top + 0.14)
    check = robot.goto(approach, pitch=90, yaw=cheese_yaw, grip='open', dry_run=True)
    print(check)
    if check.ok:
        move = robot.goto(approach, pitch=90, yaw=cheese_yaw, grip='open')
        print(move)
        if move.ok:
            cheese = robot.measure(cheese)
            print(cheese)
robot.look('all', tile=True)