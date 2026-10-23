## Include the robot-return stage in this stacking task

This stacking task includes returning both robot arms to their episode-start
EEF positions and orientations after the blocks have been placed. Save the
measured initial poses from the step-zero observation and reserve control steps
for this final stage.

Once the three-block stack is visibly stable, open the grippers, retreat clear
of the stack, and use bounded EEF motions to return each arm to its saved initial
position and orientation. Verify the measured poses during the return. A high
clearance waypoint is a transit pose; the final parking target is the saved
episode-start pose. Keep the stack undisturbed throughout the return.
