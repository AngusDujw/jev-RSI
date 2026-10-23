## Default grasp strategy for simple blocks

For these tabletop blocks, prefer a near-vertical top-down pinch over a shallow
side approach. Before final descent, aim the actual finger-extension axis to
within about 15 degrees of world down, with the closing direction approximately
in the tabletop plane. Check this using the measured quaternion and images;
an Euler angle alone is insufficient. Choose your own quaternion and bounded
sequence. Reacquire the chosen block after changing orientation. Retain the
validated grasp orientation while translating, rather than silently accepting
orientation drift at every new observation. This is a strategy prior, not
evidence of clearance, contact or capture; verify the remaining conditions.
