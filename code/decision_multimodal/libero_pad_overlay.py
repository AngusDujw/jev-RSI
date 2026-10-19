"""Project public own finger-pad faces; no scene pose, target or contact input."""
import numpy as np


def overlay_pad_faces(image,native,K,T):
    from PIL import ImageDraw,ImageFont
    robot=native.robots[0];model=native.sim.model;data=native.sim.data
    groups={side:[model.geom_name2id(name) for name in robot.gripper.important_geoms[side]]
            for side in ('left_fingerpad','right_fingerpad')}
    centres={side:np.mean([data.geom_xpos[i] for i in ids],axis=0) for side,ids in groups.items()}
    camera_from_world=np.linalg.inv(T);draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13)
    polygons=[]
    for side,other,label,colour in [('left_fingerpad','right_fingerpad','PAD-L','#ff80f0'),('right_fingerpad','left_fingerpad','PAD-R','#ff80f0')]:
        inward=centres[other]-centres[side]
        for i in groups[side]:
            if int(model.geom_type[i])!=6:continue
            R=data.geom_xmat[i].reshape(3,3);size=model.geom_size[i]
            local_inward=R.T@inward;axis=int(np.argmax(abs(local_inward)))
            sign=1 if local_inward[axis]>=0 else -1
            others=[a for a in range(3) if a!=axis]
            points=[]
            for a,b in [(-1,-1),(-1,1),(1,1),(1,-1)]:
                p=np.zeros(3);p[axis]=sign*size[axis];p[others]=[a*size[others[0]],b*size[others[1]]]
                points.append(data.geom_xpos[i]+R@p)
            camera=(camera_from_world@np.c_[points,np.ones(4)].T)[:3]
            if np.any(camera[2]<=0):continue
            uv=(K@camera);uv=(uv[:2]/uv[2]).T
            if np.max(abs(uv))>image.width*10:continue
            if np.any(uv[:,0]>=0) and np.any(uv[:,0]<image.width) and np.any(uv[:,1]>=0) and np.any(uv[:,1]<image.height):
                xy=[tuple(map(float,p)) for p in uv]
                draw.line(xy+[xy[0]],fill=colour,width=2)
                u,v=np.mean(uv,axis=0);u=float(np.clip(u,0,image.width-55));v=float(np.clip(v,0,image.height-18))
                draw.text((u,v),label,font=font,fill=colour,stroke_width=1,stroke_fill='#000000')
                polygons.append(dict(label=label,pixel_corners=np.round(uv,2).tolist()))
    return polygons
