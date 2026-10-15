"""Opt-in robot-only refinement inside the unchanged native joint-step box."""
import numpy as np
from scipy.spatial.transform import Rotation


def refine(fk,q,limits,root,target,seed):
    q=np.asarray(q,float);seed=np.asarray(seed,float);limits=np.asarray(limits,float)
    now=root@fk.matrix(q)
    desired_rotation=Rotation.from_quat(np.asarray(target['quaternion_wxyz'])[[1,2,3,0]])
    translation=np.asarray(target['position'])-now[:3,3]
    rotation=(desired_rotation*Rotation.from_matrix(now[:3,:3]).inv()).as_rotvec()
    def bound(value,cap):
        return value*min(1.,cap/max(1e-12,np.linalg.norm(value)))
    goal_position=now[:3,3]+bound(translation,.020)
    goal_rotation=Rotation.from_rotvec(bound(rotation,.100))*Rotation.from_matrix(now[:3,:3])
    lower=np.maximum(limits[:,0],q-.050);upper=np.minimum(limits[:,1],q+.050)

    def errors(joints):
        pose=root@fk.matrix(joints)
        return np.r_[goal_position-pose[:3,3],(goal_rotation*Rotation.from_matrix(pose[:3,:3]).inv()).as_rotvec()]

    def residual(joints):
        return errors(joints)/np.r_[np.full(3,.020),np.full(3,.100)]

    start=np.clip(seed,lower,upper)
    best=start.copy();best_cost=float(residual(best)@residual(best));damping=.05;iterations=0
    for iteration in range(8):
        iterations=iteration+1
        value=residual(best)
        jacobian=np.zeros((6,len(q)))
        for i in range(len(q)):
            high=best.copy();low=best.copy()
            high[i]=min(upper[i],best[i]+.0001);low[i]=max(lower[i],best[i]-.0001)
            if high[i]-low[i]>1e-12:
                jacobian[:,i]=.050*(residual(high)-residual(low))/(high[i]-low[i])
        u,s,v=np.linalg.svd(jacobian,full_matrices=False)
        dx=-(v.T*(s/(s*s+damping*damping)))@(u.T@value)
        improved=False
        for scale in (1.,.5,.25):
            candidate=np.clip(best+.050*scale*dx,lower,upper)
            cost=float(residual(candidate)@residual(candidate))
            if np.isfinite(cost) and cost<best_cost-1e-12:
                change=float(np.max(abs(candidate-best)))
                best=candidate;best_cost=cost;improved=True;break
        if not improved:
            damping=min(1.,2*damping)
            break
        e=errors(best)
        if change<.00001 or (np.linalg.norm(e[:3])<=.0001 and np.linalg.norm(e[3:])<=.001):
            break
    native=errors(start);candidate=errors(best)
    native_p=float(np.linalg.norm(native[:3]));native_r=float(np.linalg.norm(native[3:]))
    candidate_p=float(np.linalg.norm(candidate[:3]));candidate_r=float(np.linalg.norm(candidate[3:]))
    accepted=bool(candidate_p<=native_p+.000001 and candidate_r<=native_r+.00001 and
        (native_p<=.0001 or candidate_p<native_p-.000001) and
        (native_r<=.001 or candidate_r<native_r-.00001) and
        (candidate_p<native_p-.000001 or candidate_r<native_r-.00001))
    poses=[root@fk.matrix(q+alpha*(best-q)) for alpha in np.linspace(0,1,7)]
    path=float(sum(np.linalg.norm(b[:3,3]-a[:3,3]) for a,b in zip(poses,poses[1:])))
    angle=float(sum(Rotation.from_matrix(b[:3,:3]@a[:3,:3].T).magnitude() for a,b in zip(poses,poses[1:])))
    accepted=bool(accepted and path<=.0205 and angle<=.1005 and np.isfinite(best).all())
    return (best if accepted else start).astype(np.float32),dict(
        method='bounded_robot_only_iterative_FK_refinement',accepted=accepted,iterations=iterations,
        seed_joint_target=start.tolist(),refined_joint_target=best.tolist(),
        immediate_seed_position_error_m=native_p,immediate_seed_rotation_error_rad=native_r,
        immediate_refined_position_error_m=candidate_p,immediate_refined_rotation_error_rad=candidate_r,
        fixed_joint_box_lower=lower.tolist(),fixed_joint_box_upper=upper.tolist(),
        predicted_linear_joint_path_translation_m=path,predicted_linear_joint_path_rotation_rad=angle,
        interpretation='Robot-only numerical predictions; not measured tracking, forces, clearance or object progress')


def install():
    from hybrid_rollout.robodojo.robodojo_server.kinematics import ArmFK,DualKinematics
    native=ArmFK.bounded_target;native_target=DualKinematics.target

    def target(self,targets):
        checks=self.check()
        for arm,fk in self.fk.items():
            check=checks['arms'][arm]
            fk._refinement_eligible=check['position_error_m']<=.0005 and check['rotation_error_rad']<=.005
        return native_target(self,targets)

    def bounded(self,q,limits,root,target):
        seed,diagnostic=native(self,q,limits,root,target)
        if not getattr(self,'_refinement_eligible',False):
            return seed,dict(diagnostic,refinement=dict(accepted=False,reason='Public robot FK tighter consistency gate unavailable'))
        try:
            result,extra=refine(self,q,limits,root,target,seed)
            return result,dict(diagnostic,refinement=extra)
        except (ValueError,np.linalg.LinAlgError,FloatingPointError) as error:
            return seed,dict(diagnostic,refinement=dict(accepted=False,reason=type(error).__name__))
    ArmFK.bounded_target=bounded
    DualKinematics.target=target
