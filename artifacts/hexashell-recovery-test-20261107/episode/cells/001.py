print(robot.task)
cheese = robot.measure('cream cheese')
bowl = robot.measure('bowl')
print(cheese)
print(bowl)
if max(cheese.size) < 0.20:
    cheese_yaw = cheese.grip_yaw if cheese.grip_yaw is not None else 0
    approach = (cheese.center[0], cheese.center[1], cheese.top + 0.14)
    check = robot.goto(approach, pitch=90, yaw=cheese_yaw, grip='open', dry_run=True)
    print(check)
    if check.ok:
        print(robot.goto(approach, pitch=90, yaw=cheese_yaw, grip='open'))
        cheese = robot.measure(cheese)
        print(cheese)
robot.look('all', tile=True)