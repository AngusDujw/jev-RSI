## A lift must be followed by a deliberate transfer

Keep a small same-episode ledger for the current block: pickup reference pose,
verified lift, intended support identity, observed lateral mismatch, and chosen
transfer correction. The ledger is your interpretation of RGB and measured
robot state; it does not certify contact or object pose.

After a verified lift, explicitly compare the held block with the intended
support. If they remain apart, carry the held block toward that support before
lowering. Lifting and lowering at the pickup XY does not move a block onto a
different base. Before release, compare your actual LINK6 XY with the pickup
reference and explain what current visual evidence supports the transfer. A
nonzero displacement alone does not prove alignment, and unchanged XY is valid
only when current evidence actually supports that configuration.

If the object lands beside its support, keep the recovery focused on that
observed placement error. Regrasping and repeating the same vertical lift/drop
at the same lateral location cannot repair a lateral miss.
