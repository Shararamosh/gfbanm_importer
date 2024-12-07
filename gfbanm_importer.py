"""
    Script for importing animation from deserialized gfbanm file.
"""
import os
import sys
import math

import bpy
from mathutils import Vector, Euler, Quaternion, Matrix

sys.path.append(os.path.join(os.path.dirname(__file__), "."))

from GFLib.Anim.DynamicRotationTrack import DynamicRotationTrackT
from GFLib.Anim.DynamicVectorTrack import DynamicVectorTrackT
from GFLib.Anim.FixedRotationTrack import FixedRotationTrackT
from GFLib.Anim.FixedVectorTrack import FixedVectorTrackT
from GFLib.Anim.Framed16RotationTrack import Framed16RotationTrackT
from GFLib.Anim.Framed16VectorTrack import Framed16VectorTrackT
from GFLib.Anim.Framed8RotationTrack import Framed8RotationTrackT
from GFLib.Anim.Framed8VectorTrack import Framed8VectorTrackT
from GFLib.Anim.Animation import AnimationT
from GFLib.Anim.BoneTrack import BoneTrackT
from GFLib.Anim.Vec3 import Vec3T
from GFLib.Anim.sVec3 import sVec3T


def import_animation(context: bpy.types.Context, file_path: str, euler_rotation_mode: str,
                     add_euler_rotation: (float, float, float)):
    """
    Imports animation from processing gfbanm file.
    :param context: Blender's Context.
    :param file_path: Path to gfbanm file.
    :param euler_rotation_mode: Euler Rotation Mode string.
    :param add_euler_rotation: Additive Euler Rotation.
    """
    if context.object is None or context.object.type != "ARMATURE":
        raise OSError("Target Armature not selected.")
    print("Armature name: " + context.object.name + ".")
    anim_name = os.path.splitext(os.path.basename(file_path))[0]
    print("Animation name: " + anim_name + ".")
    print("Euler Rotation Mode: " + euler_rotation_mode + ".")
    with open(file_path, "rb") as file:
        anm = AnimationT.InitFromPackedBuf(bytearray(file.read()), 0)
        if anm.info is None:
            raise OSError(file_path + " contains invalid info chunk.")
        if anm.info.keyFrames < 1:
            raise OSError(file_path + " contains invalid info.keyFrames chunk.")
        print("Keyframes amount: " + str(anm.info.keyFrames) + ".")
        if anm.info.frameRate < 1:
            raise OSError(file_path + " contains invalid info.frameRate chunk.")
        print("Framerate: " + str(anm.info.frameRate) + " FPS.")
        if anm.skeleton is None:
            raise OSError(file_path + " contains invalid skeleton chunk.")
        if anm.skeleton.tracks is None:
            raise OSError(file_path + " contains invalid skeleton.tracks chunk.")
        if anm.skeleton.initData is not None:
            print("skeleton.initData.isInit: " + str(anm.skeleton.initData.isInit) + ".")
            print("skeleton.initData.transform: " + str(anm.skeleton.initData.transform) + ".")
        print("Tracks amount: " + str(len(anm.skeleton.tracks)) + ".")
        previous_mode = context.object.mode
        previous_frame = context.scene.frame_current
        select_bones = {}
        for bone in context.object.data.bones:
            select_bones.update({bone: bone.select})
        if context.object.mode != "POSE":
            bpy.ops.object.mode_set(mode="POSE")
        apply_animation_to_tracks(context, anim_name, anm.info.frameRate, anm.info.keyFrames,
                                  anm.skeleton.tracks, euler_rotation_mode, add_euler_rotation)
        for bone, select in select_bones.items():
            bone.select = select
        if previous_frame != context.scene.frame_current:
            context.scene.frame_set(previous_frame)
        if previous_mode != context.object.mode:
            bpy.ops.object.mode_set(mode=previous_mode)


def apply_animation_to_tracks(context: bpy.types.Context, anim_name: str, frame_rate: int,
                              key_frames: int, tracks: list[BoneTrackT | None],
                              euler_rotation_mode: str, add_euler_rotation: (float, float, float)):
    """
    Applies animation to bones of selected Armature.
    :param context: Blender's Context.
    :param anim_name: Action name.
    :param frame_rate: Framerate.
    :param key_frames: Keyframes amount.
    :param tracks: List of BoneTrack objects.
    :param euler_rotation_mode: Euler Rotation Mode string.
    :param add_euler_rotation: Additive Euler Rotation.
    """
    assert context.object is not None and context.object.type == "ARMATURE", \
        "Selected object is not Armature."
    previous_location = context.object.location
    previous_rotation = (context.object.rotation_mode, context.object.rotation_euler)
    previous_scale = context.object.scale
    context.object.location = Vector((0.0, 0.0, 0.0))
    context.object.rotation_mode = "XYZ"
    context.object.rotation_euler = Euler((0.0, 0.0, 0.0))
    context.object.scale = Vector((1.0, 1.0, 1.0))
    action = None
    for track in tracks:
        if track is None or track.name is None or track.name == "":
            continue
        print("Creating keyframes for " + track.name + " track.")
        pose_bone = context.object.pose.bones.get(track.name)
        if pose_bone is None:
            continue
        for bone in context.object.data.bones:
            bone.select = bone.name == track.name
        t_list = get_vector_track_transforms(track.translate, key_frames)
        r_list = get_rotation_track_transforms(track.rotate, key_frames, euler_rotation_mode,
                                               add_euler_rotation)

        s_list = get_vector_track_transforms(track.scale, key_frames)
        if context.object.animation_data is None:
            context.object.animation_data_create()
        if action is None:
            action = bpy.data.actions.new(anim_name)
            action.use_fake_user = True
            context.object.animation_data.action = action
            context.scene.render.fps = frame_rate
            context.scene.render.fps_base = 1.0
        apply_track_transforms_to_posebone(context, pose_bone, list(zip(t_list, r_list, s_list)),
                                           True)
    context.object.location = previous_location
    context.object.rotation_mode = previous_rotation[0]
    context.object.rotation_euler = previous_rotation[1]
    context.object.scale = previous_scale
    context.scene.frame_end = context.scene.frame_start + key_frames - 1


def apply_track_transforms_to_posebone(context: bpy.types.Context, pose_bone: bpy.types.PoseBone,
                                       transforms: list[
                                           (Vector | None, Euler | None, Vector | None)],
                                       print_first_frame_transforms_info: bool):
    """
    Applies global transforms to PoseBone for every keyframe of animation.
    :param context: Blender's Context.
    :param pose_bone: Target PoseBone.
    :param transforms: List of (Location, Rotation, Scaling) global transform tuples.
    :param print_first_frame_transforms_info: Print information about applied first frame transforms or not.
    """
    for i, transform in enumerate(transforms):
        context.scene.frame_set(context.scene.frame_start + i)
        bone_loc, bone_rot, bone_scale = get_posebone_global_matrix(pose_bone).decompose()
        if pose_bone.parent is not None:
            parent_loc, _, _ = get_posebone_global_matrix(pose_bone.parent).decompose()
        else:
            parent_loc, _, _ = pose_bone.id_data.matrix_world.decompose()
        loc_key = rot_key = scale_key = False
        if transform[0] is not None:
            bone_loc = parent_loc + transform[0]
            set_posebone_global_matrix(pose_bone,
                                       Matrix.LocRotScale(bone_loc, bone_rot, bone_scale))
            loc_key = True
        if transform[1] is not None:
            pose_bone.rotation_euler = transform[1].copy()
            pose_bone.rotation_quaternion = transform[1].to_quaternion()
            axis_angle = pose_bone.rotation_quaternion.to_axis_angle()
            pose_bone.rotation_axis_angle = [axis_angle[0][0], axis_angle[0][1], axis_angle[0][2],
                                             axis_angle[1]]
            rot_key = True
        if transform[2] is not None:
            pose_bone.scale = transform[2].copy()
            scale_key = True
        if i == 0 and (loc_key or rot_key or scale_key):
            print("First frame transforms:")
        if loc_key:
            if i == 0 and print_first_frame_transforms_info:
                print("Raw location: " + str(transform[0]) + ".")
                print("Parent global location: " + str(parent_loc) + ".")
                print("Global location: " + str(bone_loc) + ".")
                print("Pose location: " + str(pose_bone.location) + ".")
            bpy.ops.anim.keyframe_insert_menu(type="Location")
        if rot_key:
            if i == 0 and print_first_frame_transforms_info:
                print("Raw rotation: " + str(transform[1]) + ".")
                if pose_bone.rotation_mode == "QUATERNION":
                    print("Pose quaternion rotation: " + str(pose_bone.rotation_quaternion) + ".")
                elif pose_bone.rotation_mode == "AXIS_ANGLE":
                    print("Pose axis angle rotation: " + str(pose_bone.rotation_axis_angle) + ".")
                else:
                    print("Pose euler rotation: " + str(pose_bone.rotation_euler) + ".")
            bpy.ops.anim.keyframe_insert_menu(type="Rotation")
        if scale_key:
            if i == 0 and print_first_frame_transforms_info:
                print("Pose scale: " + str(pose_bone.scale) + ".")
            bpy.ops.anim.keyframe_insert_menu(type="Scaling")


def get_posebone_global_matrix(pose_bone: bpy.types.PoseBone) -> Matrix:
    """
    Returns global transform Matrix of PoseBone.
    :param pose_bone: PoseBone.
    :return: Global transform Matrix.
    """
    assert pose_bone is not None, "Can't get global transform Matrix for None pose bone."
    return pose_bone.id_data.matrix_world @ pose_bone.matrix


def set_posebone_global_matrix(pose_bone: bpy.types.PoseBone, m: Matrix):
    """
    Applies global transform Matrix to PoseBone.
    :param pose_bone: PoseBone.
    :param m: Global transform Matrix.
    """
    assert pose_bone is not None, "Can't set global transform Matrix for None pose bone."
    pose_bone.matrix = pose_bone.id_data.matrix_world.inverted() @ m


def get_vector_track_transforms(track: DynamicVectorTrackT | FixedVectorTrackT |
                                       Framed16VectorTrackT | Framed8VectorTrackT | None,
                                key_frames: int) -> list[Vector | None]:
    """
    Returns list with transforms from VectorTrack object.
    :param track: VectorTrack object.
    :param key_frames: Amount of keyframes in animation.
    :return: List of Vectors or None.
    """
    assert key_frames > 0, "Keyframes amount is less than 1."
    transforms: list[Vector | None] = [None] * key_frames
    if track is None or track.co is None:
        return transforms
    if isinstance(track, FixedVectorTrackT):
        v = Vector((track.co.x, track.co.y, track.co.z))
        for i in range(key_frames):
            transforms[i] = v
    elif isinstance(track, DynamicVectorTrackT):
        for i in range(min(len(track.co), key_frames)):
            transforms[i] = Vector((track.co[i].x, track.co[i].y, track.co[i].z))
    elif isinstance(track, Framed16VectorTrackT):
        for i in range(min(len(track.co), len(track.frames))):
            if -1 < track.frames[i] < key_frames:
                transforms[track.frames[i]] = Vector((track.co[i].x, track.co[i].y, track.co[i].z))
    elif isinstance(track, Framed8VectorTrackT):
        for i in range(min(len(track.co), len(track.frames))):
            if -1 < track.frames[i] < key_frames:
                transforms[track.frames[i]] = Vector((track.co[i].x, track.co[i].y, track.co[i].z))
    return transforms


def get_rotation_track_transforms(track: DynamicRotationTrackT | FixedRotationTrackT |
                                         Framed16RotationTrackT | Framed8RotationTrackT | None,
                                  key_frames: int, euler_rotation_mode: str,
                                  add_euler_rotation: (float, float, float)) -> list[Euler | None]:
    """
    Returns list with transforms from RotationTrack object.
    :param track: RotationTrack object.
    :param key_frames: Amount of keyframes in animation.
    :param euler_rotation_mode: Euler Rotation Mode string.
    :param add_euler_rotation: Additive Euler Rotation.
    :return: List of Eulers or None.
    """
    assert key_frames > 0, "Keyframes amount is less than 1."
    transforms: list[Euler | None] = [None] * key_frames
    if isinstance(track, FixedRotationTrackT):
        e = get_euler_from_vector(track.co, euler_rotation_mode)
        e.rotate_axis("X", math.radians(add_euler_rotation[0]))
        e.rotate_axis("Y", math.radians(add_euler_rotation[1]))
        e.rotate_axis("Z", math.radians(add_euler_rotation[2]))
        for i in range(key_frames):
            transforms[i] = e
    elif isinstance(track, DynamicRotationTrackT):
        for i in range(min(len(track.co), key_frames)):
            transforms[i] = get_euler_from_vector(track.co[i], euler_rotation_mode)
            transforms[i].rotate_axis("X", math.radians(add_euler_rotation[0]))
            transforms[i].rotate_axis("Y", math.radians(add_euler_rotation[1]))
            transforms[i].rotate_axis("Z", math.radians(add_euler_rotation[2]))
    elif isinstance(track, Framed16RotationTrackT):
        for i in range(min(len(track.co), len(track.frames))):
            if -1 < track.frames[i] < key_frames:
                transforms[track.frames[i]] = get_euler_from_vector(track.co[i],
                                                                    euler_rotation_mode)
                transforms[track.frames[i]].rotate_axis("X", math.radians(add_euler_rotation[0]))
                transforms[track.frames[i]].rotate_axis("Y", math.radians(add_euler_rotation[1]))
                transforms[track.frames[i]].rotate_axis("Z", math.radians(add_euler_rotation[2]))
    elif isinstance(track, Framed8RotationTrackT):
        for i in range(min(len(track.co), len(track.frames))):
            if -1 < track.frames[i] < key_frames:
                transforms[track.frames[i]] = get_euler_from_vector(track.co[i],
                                                                    euler_rotation_mode)
                transforms[track.frames[i]].rotate_axis("X", math.radians(add_euler_rotation[0]))
                transforms[track.frames[i]].rotate_axis("Y", math.radians(add_euler_rotation[1]))
                transforms[track.frames[i]].rotate_axis("Z", math.radians(add_euler_rotation[2]))
    return transforms


PI_DIVISOR = math.pi / 65535
PI_ADDEND = math.pi / 4.0


def expand_float(i: int) -> float:
    return i * PI_DIVISOR - PI_ADDEND


def quantize_float(i: float) -> int:
    result = int((i + PI_ADDEND) / PI_DIVISOR)
    return result & 0x7FFF


def unpack(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    pack = (z << 32) | (y << 16) | x
    missing_component = pack & 3
    # isNegative = (pack & 4) == 0
    tx = expand_float((pack >> 3) & 0x7FFF)
    ty = expand_float((pack >> (15 + 3)) & 0x7FFF)
    tz = expand_float((pack >> (30 + 3)) & 0x7FFF)
    tw = 1.0 - (tx * tx + ty * ty + tz * tz)
    tw = max(tw, 0.0)
    tw = math.sqrt(tw)
    if missing_component == 0:
        result = (tw, ty, tz, tx)
    elif missing_component == 1:
        result = (tx, tw, tz, ty)
    elif missing_component == 2:
        result = (tx, ty, tw, tz)
    else:
        result = (tx, ty, tz, tw)
    return result


def get_quaternion_from_vector(vec: Vec3T | sVec3T | None) -> Quaternion | None:
    if vec is None:
        return None
    # quaternion_tuple = unpack(vec.x, vec.y, vec.z)  # Get (w, x, y, z) tuple
    quaternion_tuple = packed_to_quat(vec.x, vec.y, vec.z)
    return Quaternion(quaternion_tuple)


def get_euler_from_vector(vec: Vec3T | sVec3T | None, euler_rotation_mode="XYZ") -> Euler | None:
    """
    Converts packed quaternion components into an Euler object.
    :param vec: Packed Vector object.
    :param euler_rotation_mode: Euler rotation mode string.
    :return: Euler object.
    """
    quaternion = get_quaternion_from_vector(vec)  # Create Blender Quaternion object
    if quaternion is None:
        return None
    euler = quaternion.to_euler(euler_rotation_mode)
    # These modifications helped with some rotations, but some had 90 degrees difference.
    # x = -1.0 * (math.pi + euler.z)
    # y = -1.0 * euler.y
    # z = euler.x
    # euler.x = x
    # euler.y = y
    # euler.z = z
    return euler


def unpack_s15(u15: int):
    sign = (u15 >> 14) & 1
    u15 &= 0x3FFF
    if sign == 0:
        u15 -= 0x4000
    return u15


COUNT = 15
BASE = (1 << COUNT) - 1
MAX_VAL = 1.0 / (0x399E * math.sqrt(2.0))
# Blender uses W, X, Y, Z Quaternion order instead of C#'s X, Y, Z, W, so W is moved left here.
QUATERNION_SWIZZLES = ((1, 0, 3, 2), (1, 3, 0, 2), (1, 3, 2, 0), (0, 3, 2, 1))


def packed_to_quat(z: int, y: int, x: int) -> Quaternion:
    cq = x & 0xFFFF
    cq <<= 16
    cq |= y & 0xFFFF
    cq <<= 16
    cq |= z & 0xFFFF
    extra = cq & 0x7
    num = cq >> 3
    x = unpack_s15(num >> (COUNT * 2) & BASE)
    y = unpack_s15(num >> (COUNT * 1) & BASE)
    z = unpack_s15(num >> (COUNT * 0) & BASE)
    fx = x * MAX_VAL
    fy = y * MAX_VAL
    fz = z * MAX_VAL
    quat_tuple = (math.sqrt(1.0 - fx * fx - fy * fy - fz * fz), fx, fy, fz)
    quat_map = QUATERNION_SWIZZLES[extra & 3]
    quat = Quaternion([quat_tuple[i] for i in quat_map])
    if extra >> 2 != 0:
        quat *= -1
    return quat
