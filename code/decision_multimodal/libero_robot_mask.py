"""Reject RGB-D points inside public own-robot geometry bounds.

Only model-owned robot/gripper geom names and measured own FK are read. Mesh
bounds are conservative; rejection is not scene identity or contact evidence.
"""
import numpy as np


def own_geometry_rejector(native, margin=.001):
    model=native.sim.model;data=native.sim.data;robot=native.robots[0]
    names=set()
    for owner in (robot.robot_model,robot.gripper):
        for key in ('contact_geoms','visual_geoms'):
            names.update(getattr(owner,key,[]))
    geometry=[]
    for name in names:
        i=model.geom_name2id(name);kind=int(model.geom_type[i])
        if kind not in (2,3,4,5,6,7):continue
        geometry.append((kind,data.geom_xpos[i].copy(),data.geom_xmat[i].reshape(3,3).copy(),model.geom_size[i].copy()))

    def reject(points):
        result=np.zeros(len(points),bool)
        for kind,centre,R,size in geometry:
            p=(np.asarray(points)-centre)@R
            if kind==2:inside=np.sum(p*p,axis=1)<=(size[0]+margin)**2
            elif kind==3:
                closest=p.copy();closest[:,2]-=np.clip(closest[:,2],-size[1],size[1])
                inside=np.sum(closest*closest,axis=1)<=(size[0]+margin)**2
            elif kind==5:inside=(np.sum(p[:,:2]**2,axis=1)<=(size[0]+margin)**2)&(abs(p[:,2])<=size[1]+margin)
            elif kind==4:inside=np.sum((p/np.maximum(size+margin,1e-9))**2,axis=1)<=1
            else:inside=np.all(abs(p)<=size+margin,axis=1)
            result|=inside
        return result
    reject.own_geom_count=len(geometry)
    return reject
