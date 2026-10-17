"""Robot-only multistart TCP IK, with explicit residual diagnostics."""
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


def solve_tcp(forward,position,rotation,seed,limits):
    def residual(q):
        t=forward(q)
        return np.r_[(t[:3,3]-position)*10,Rotation.from_matrix(rotation@t[:3,:3].T).as_rotvec()]
    starts=[np.asarray(seed,float).copy()]
    for a,b in [(0.18,-0.36),(-0.18,0.36),(0.36,-0.72),(-0.36,0.72),(.5,.5),(-.5,-.5)]:
        q=np.asarray(seed,float).copy()
        q[1]+=a
        q[2]+=b
        starts.append(q)
    best=None
    attempts=[]
    for initial in starts:
        initial=np.clip(initial,limits[:,0]+1e-6,limits[:,1]-1e-6)
        fit=least_squares(residual,initial,bounds=(limits[:,0],limits[:,1]),max_nfev=220,
                          ftol=1e-10,xtol=1e-10,gtol=1e-10)
        t=forward(fit.x)
        p=float(np.linalg.norm(t[:3,3]-position))
        r=float(Rotation.from_matrix(rotation@t[:3,:3].T).magnitude())
        attempts.append(dict(position_error_m=p,rotation_error_rad=r,nfev=fit.nfev))
        if best is None or np.linalg.norm(residual(fit.x))<best[0]:
            best=(np.linalg.norm(residual(fit.x)),fit.x,p,r)
        if p<.003 and r<.02:
            break
    return best[1],dict(position_error_m=best[2],rotation_error_rad=best[3],attempts=attempts,
                        passed=best[2]<.003 and best[3]<.02)
