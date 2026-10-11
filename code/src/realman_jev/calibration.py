"""Calibration math uses measured correspondences, no invented rig transforms."""
import json
from pathlib import Path
import cv2
import numpy as np
from .hardware import rigid


def fit_points(camera_points,base_points):
    a,b=np.asarray(camera_points,float),np.asarray(base_points,float)
    if a.shape!=b.shape or a.ndim!=2 or a.shape[1]!=3 or len(a)<6 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("Need >=6 finite measured 3D correspondences")
    # Last two samples are held out: never certify only a training fit.
    aa,bb=a[:-2],b[:-2]
    if np.linalg.matrix_rank(aa-aa.mean(0),tol=.003)<2:
        raise ValueError("Calibration samples are collinear or insufficiently spread")
    u,_,vt=np.linalg.svd((aa-aa.mean(0)).T@(bb-bb.mean(0)))
    D=np.eye(3); D[-1,-1]=np.linalg.det(vt.T@u.T)
    R=vt.T@D@u.T
    t=bb.mean(0)-R@aa.mean(0)
    T=np.eye(4); T[:3,:3]=R; T[:3,3]=t
    errors=np.linalg.norm(a@R.T+t-b,axis=1)
    return {"T_base_camera":T.tolist(),"fit_rmse_m":float(np.sqrt(np.mean(errors[:-2]**2))),
            "holdout_max_error_m":float(errors[-2:].max()),"verified":False,
            "note":"Check held-out error and hardware frame identity before explicit verification"}


def handeye(samples):
    if len(samples)<12: raise ValueError("Need >=12 diverse wrist/board pose samples")
    g=[rigid(s["T_base_tool"]) for s in samples]
    c=[rigid(s["T_camera_board"]) for s in samples]
    from scipy.spatial.transform import Rotation
    rotations=np.array([Rotation.from_matrix(x[:3,:3]@g[0][:3,:3].T).as_rotvec() for x in g[1:-3]])
    if np.linalg.matrix_rank(rotations,tol=.05)<2:
        raise ValueError("Hand-eye calibration needs rotation about multiple axes")
    R,t=cv2.calibrateHandEye([x[:3,:3] for x in g[:-3]],[x[:3,3] for x in g[:-3]],
                            [x[:3,:3] for x in c[:-3]],[x[:3,3] for x in c[:-3]],method=cv2.CALIB_HAND_EYE_PARK)
    X=np.eye(4); X[:3,:3]=R; X[:3,3]=t.flatten(); rigid(X)
    board=[a@X@b for a,b in zip(g,c)]
    center=np.mean([b[:3,3] for b in board[:-3]],axis=0)
    holdout=max(float(np.linalg.norm(b[:3,3]-center)) for b in board[-3:])
    return {"T_tool_camera":X.tolist(),"holdout_board_translation_error_m":holdout,"verified":False}


def solve_file(input_path,output_path,method):
    d=json.loads(Path(input_path).read_text())
    result=fit_points(d["camera_points_m"],d["base_points_m"]) if method=="points" else handeye(d["samples"])
    p=Path(output_path)
    with p.open("x") as f: json.dump(result,f,indent=2)
    return result


def sample_marker(robot,camera,marker_id,marker_size,output,base_point=None):
    """Read-only capture. Manually reposition robot/board between invocations."""
    if marker_size<=0 or marker_size>.3: raise ValueError("Marker side length must be measured in metres")
    obs=robot.observe(); frame=obs.cameras[camera]
    detector=cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50))
    corners,ids,_=detector.detectMarkers(frame.rgb)
    if ids is None or marker_id not in ids: raise ValueError("Requested marker not visible")
    corner=corners[list(ids.flatten()).index(marker_id)].reshape(4,2)
    s=marker_size/2
    points=np.array([[-s,s,0],[s,s,0],[s,-s,0],[-s,-s,0]],float)
    ok,rvec,tvec=cv2.solvePnP(points,corner.astype(float),frame.K,np.zeros(5),flags=cv2.SOLVEPNP_IPPE_SQUARE)
    if not ok: raise ValueError("Marker PnP failed")
    T=np.eye(4); T[:3,:3]=cv2.Rodrigues(rvec)[0];T[:3,3]=tvec.flatten()
    proj=cv2.projectPoints(points,rvec,tvec,frame.K,np.zeros(5))[0].reshape(4,2)
    error=float(np.sqrt(np.mean((proj-corner)**2)))
    if error>1.5: raise ValueError("Marker reprojection error too large")
    tool=np.eye(4);tool[:3,:3]=obs.rotation;tool[:3,3]=obs.tcp
    p=Path(output)
    d=json.loads(p.read_text()) if p.exists() else {"samples":[],"camera_points_m":[],"base_points_m":[],"camera":camera,"marker_id":marker_id,"marker_size_m":marker_size}
    if d["camera"]!=camera or d["marker_id"]!=marker_id or d["marker_size_m"]!=marker_size:
        raise ValueError("Do not mix calibration camera/marker identities")
    d["samples"].append({"T_base_tool":tool.tolist(),"T_camera_board":T.tolist(),"reprojection_rmse_px":error})
    if base_point is not None:
        b=np.array(base_point,float)
        if b.shape!=(3,) or not np.isfinite(b).all(): raise ValueError("Invalid measured base point")
        d["camera_points_m"].append(tvec.flatten().tolist()); d["base_points_m"].append(b.tolist())
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,indent=2))
    return {"samples":len(d["samples"]),"reprojection_rmse_px":error,"motion_sent":False}
