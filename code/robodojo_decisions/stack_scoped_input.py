"""Question-specific model evidence; originals remain in the run assets.

Selection changes no sensor values, complete targets, questions or images.
Every original memory file is validated and its literal excerpts are auditable.
"""
import hashlib
import json
from pathlib import Path
from model_input_language import require_english_model_input


def project(data, kind):
    if data.get('task')!='stack_blocks':
        raise ValueError('Question-specific stack projection is task-scoped')
    require_english_model_input(data,'full evidence before question-specific projection')
    notes=data['experience_original_text'];hashes=data['experience_raw_sha256']
    selected={}
    for name,text in notes.items():
        if hashlib.sha256(text.encode()).hexdigest()!=hashes[name]:
            raise ValueError('Original memory does not match its read manifest')
        lines=[line for line in text.splitlines() if line.startswith('- ')]
        if name=='global.md':
            chosen=[line for line in lines if line.startswith((
                '- Use only current','- A measured LINK6','- Choose a whole categorical'))]
            chosen=chosen[:3] or lines[:3]
        elif kind in ('roles','identity'):
            chosen=lines[:2]+[line for line in lines if line.startswith('- A fresh conditional')][:1]
        else:
            chosen=lines[-3:]
        selected[name]=list(dict.fromkeys(chosen))
    out={k:data[k] for k in ('task','instruction','step_id','planner_task_role_assignment',
        'current_semantic_roles','role_hypothesis_provenance',
        'completed_semantic_stage_evidence','semantic_role_binding_valid') if k in data}
    out['environment_context']={'benchmark':'RoboDojo','execution':'SIMULATION_ONLY','real_robot_control':False}
    out['experience_read_manifest']={'full_original_sha256':hashes,
        'full_original_directory':data.get('experience_original_file_directory'),
        'selection':'Literal question-specific bullets; full files were read before this call and remain in saved full evidence.'}
    out['experience_literal_excerpts']=selected
    if kind in ('roles','identity'):
        out['scope']='CURRENT active-pair semantic identity only. No robot action is requested and no future third-object/grasp evidence is presumed.'
        return out
    out.update({k:data[k] for k in ('current_stage','current_stage_rule',
        'previous_stage_assessment','planner_visual_method',
        'current_robot_eef','actual_finger_encoders') if k in data})
    geometry=data.get('algorithmic_far_approach_evidence',{})
    out['current_source_reference']={k:geometry[k] for k in (
        'status','step_id','entity','current_component_pixels','high_source_basis',
        'current_full_two_view_top_supported','prior_high_source_check',
        'measured_robot_pad_midpoint_world_m','top_minus_pad_midpoint_world_xyz_mm',
        'top_minus_pad_midpoint_xyz_interval_mm','reason') if k in geometry}
    fit=geometry.get('fit',{})
    out['current_source_reference']['fit']={k:fit[k] for k in (
        'best_plane_z_m','best_mask_iou','near_best_z_m_at_iou_within_0p05') if k in fit}
    out['current_source_reference']['scope']='Uncertain source TOP reference for FAR OPEN only, not body centre, contact, enclosure or holding. A historical high reference remains historical under the stated current revalidation.'
    tool=data.get('algorithmic_tool_orientation_evidence',{})
    out['public_tool_geometry']={k:tool[k] for k in (
        'current_public_finger_extension_axis_world','assumed_source_plane_normal_world',
        'finger_extension_vs_downward_normal_angle_deg','source_plane_step_id',
        'source_plane_height_halfwidth_m','maximum_offered_rotation_mrad',
        'coupled_source_view_recovery') if k in tool}
    if kind=='stage':
        out['scope']='Classify the first unfinished current semantic stage; answers to other calls and predicted future effects do not certify completion. Stage rules are supplied in the actual question choices.'
        return out
    out.update({k:data[k] for k in ('current_robot_eef','current_robot_joint_state',
        'actual_finger_encoders','complete_programs','algorithmic_program_family',
        'same_hypothesis_complete_program_effects','baseline_translation_increment_mm') if k in data})
    out['algorithmic_proposal_objective']=data.get('candidate_generation_policy')
    offered=data.get('complete_programs',{})
    out['conditional_endpoint_relations']={k:v for k,v in geometry.get('candidate_endpoint_relations',{}).items() if k in offered}
    rows=geometry.get('public_actual_finger_facets',{}).get('rows',{})
    out['current_public_inner_facet_wrist_boxes']={k:v.get('projected_bbox_xyxy') for k,v in rows.items()}
    out['frame_and_units']='Robot poses refer to measured LINK6 in the environment/WORLD frame. WORLD +X robot-right, +Y away from bases, +Z up. Source errors are hypothesis MINUS public pad midpoint in mm: a positive pad displacement reduces a positive error. Rotations use the right-hand rule about fixed WORLD axes; wrist/image axes differ. A tool turn can move the pad as well as rotate it.'
    out['decision_scope']='Judge ONE exact complete_programs entry or STOP on these CURRENT RGB. This is a bounded OPEN simulator stage increment, not a grasp or completion claim. Future contact/holding is not a prerequisite for FAR OPEN. Current identity loss, unsupported visible short whole-hand corridor, a visible obstacle or a robot/camera contradiction still requires STOP. The harness independently checks native first IK, public five-step/source-view limits and actual2mm tracking. No diagnostic answer overrides complete_pose_program. Verify next actual robot/RGB; never infer source movement from a robot command.'
    return out


class ScopedClient:
    def __init__(self,client,output):
        self.client=client;self.output=Path(output)

    def query(self,obs,asked,evidence,record_name,**kwargs):
        data=json.loads(evidence)
        names={q['name'] for q in asked}
        kind=('action' if 'complete_pose_program' in names else
              'identity' if 'identity_stage_EXIT' in names else
              'roles' if 'source_receiver_roles' in names else 'stage')
        result=project(data,kind)
        original=self.output/f'unprojected_evidence_{record_name}.json'
        with original.open('x') as stream:stream.write(evidence)
        result['unprojected_evidence_file']=str(original)
        result['unprojected_evidence_scope']='Audit asset only, not additional model input.'
        return self.client.query(obs,asked,json.dumps(result),record_name,**kwargs)
