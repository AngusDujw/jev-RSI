# The board is empty and I move first, but one still image cannot establish opponent motion.
# Hold the measured joints briefly to obtain temporal evidence before an approach.
o = get_observation()
a = {k:v for k,v in o['state'].items() if k.endswith('joint_state')}
for i in range(10):
    o,r,t,u,info = step(a)
    if t or u: break
print(o['state'])
