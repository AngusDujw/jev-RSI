# The board is empty and the instruction gives us the first turn.
# Hold the measured joints briefly to establish temporal evidence of opponent stillness.
o = get_observation()
a = {k:v for k,v in o['state'].items() if k.endswith('joint_state')}
for i in range(5):
    o,r,terminated,truncated,info = step(a)
    if terminated or truncated: break
print(o['state'])
