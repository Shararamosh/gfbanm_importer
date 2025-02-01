"""
    Script for exporting armature animation to gfbanm/tranm format.
"""
import os
import sys
import math

import bpy
from mathutils import Vector, Quaternion
import flatbuffers

sys.path.append(os.path.join(os.path.dirname(__file__), "."))

# pylint: disable=wrong-import-position, import-error, too-many-branches, consider-using-dict-items

from GFLib.Anim.Animation import AnimationT
from GFLib.Anim.BoneAnimation import BoneAnimationT
from GFLib.Anim.BoneTrack import BoneTrackT
from GFLib.Anim.FixedVectorTrack import FixedVectorTrackT
from GFLib.Anim.DynamicVectorTrack import DynamicVectorTrackT
from GFLib.Anim.Framed16VectorTrack import Framed16VectorTrackT
from GFLib.Anim.Framed8VectorTrack import Framed8VectorTrackT
from GFLib.Anim.FixedRotationTrack import FixedRotationTrackT
from GFLib.Anim.DynamicRotationTrack import DynamicRotationTrackT
from GFLib.Anim.Framed16RotationTrack import Framed16RotationTrackT
from GFLib.Anim.Framed8RotationTrack import Framed8RotationTrackT
from GFLib.Anim.Info import InfoT
from GFLib.Anim.Vec3 import Vec3T
from GFLib.Anim.sVec3 import sVec3T

VectorTrackType = (FixedVectorTrackT | DynamicVectorTrackT | Framed16VectorTrackT |
                   Framed8VectorTrackT)
RotationTrackType = (FixedRotationTrackT | DynamicRotationTrackT | Framed16RotationTrackT |
                     Framed8RotationTrackT)


def export_animation(context: bpy.types.Context, does_loop: bool,
                     use_action_range: bool) -> int | bytearray:
    """
    Exports armature animation to GFBANM/TRANM format.
    :param context: Blender's Context.
    :param does_loop: True if animation is looping.
    :param use_action_range: True if using action's frame range instead of scene's.
    :return: GFBANM/TRANM bytearray.
    """
    assert context.object is not None and context.object.type == "ARMATURE", \
        "Target Armature not selected."
    current_frame = context.scene.frame_current
    if use_action_range and context.object.animation_data and context.object.animation_data.action:
        frame_range = (int(context.object.animation_data.action.frame_range[0]),
                       int(context.object.animation_data.action.frame_range[1]))
        assert frame_range[1] - frame_range[0] > -1, "Action has invalid frame range set."
    else:
        frame_range = (context.scene.frame_start, context.scene.frame_end)
        assert frame_range[1] - frame_range[0] > -1, "Scene has incorrect frame range set."
    animation = AnimationT()
    animation.info = InfoT()
    animation.info.keyFrames = frame_range[1] - frame_range[0] + 1
    animation.info.frameRate = int(context.scene.render.fps / context.scene.render.fps_base)
    animation.info.doesLoop = int(does_loop)
    animation.skeleton = BoneAnimationT()
    animation.skeleton.tracks = []
    transforms = get_all_track_transforms(context, frame_range)
    for bone_name in transforms:
        print(f"Exporting keyframes for {bone_name} track.")
        track = BoneTrackT()
        track.name = bone_name
        track.translate = vector_list_to_vector_track(transforms[bone_name][0])
        track.translateType = vector_track_to_type(track.translate)
        track.rotate = quaternion_list_to_rotation_track(transforms[bone_name][1])
        track.rotateType = rotation_track_to_type(track.rotate)
        track.scale = vector_list_to_vector_track(transforms[bone_name][2])
        track.scaleType = vector_track_to_type(track.scale)
        animation.skeleton.tracks.append(track)
    context.scene.frame_set(current_frame)
    builder = flatbuffers.Builder()
    animation = animation.Pack(builder)
    builder.Finish(animation)
    return builder.Output()


PI_DIVISOR = math.pi / 65536
PI_ADDEND = math.pi / 4.0


def quantize_float(f: float) -> int:
    """
    Packs expanded float into integer.
    :param f: Expanded float.
    :return: Packed integer.
    """
    result = int((f + PI_ADDEND) / PI_DIVISOR)
    return result & 0x7FFF


def pack_quaternion_to_48bit(q: Quaternion) -> (int, int, int):
    """
    Packs Blender Quaternion into 48-bit integer Vector.
    :param q: Blender Quaternion.
    :return: X, Y, Z values of integer Vector.
    """
    q_list = [q.w, q.x, q.y, q.z]
    max_val = max(q_list)
    min_val = min(q_list)
    is_negative = 0
    if abs(min_val) > max_val:
        max_val = min_val
        is_negative = 1
    max_index = q_list.index(max_val)
    if is_negative == 1:
        q_list = [-x for x in q_list]
    if max_index == 0:
        tx = quantize_float(q_list[1])
        ty = quantize_float(q_list[2])
        tz = quantize_float(q_list[3])
    elif max_index == 1:
        tx = quantize_float(q_list[2])
        ty = quantize_float(q_list[3])
        tz = quantize_float(q_list[0])
    elif max_index == 2:
        tx = quantize_float(q_list[1])
        ty = quantize_float(q_list[3])
        tz = quantize_float(q_list[0])
    else:
        tx = quantize_float(q_list[1])
        ty = quantize_float(q_list[2])
        tz = quantize_float(q_list[0])
    pack = (tz << 30) | (ty << 15) | tx
    pack = (pack << 3) | ((is_negative << 2) | max_index)
    x, y, z = pack & 0xFFFF, (pack >> 16) & 0xFFFF, (pack >> 32) & 0xFFFF
    # Fixes for X offset across all packed values.
    if max_index == 0:
        x = min(65535, x + 3)
    else:
        x = max(0, x - 1)
    return x, y, z


def vector_list_to_vector_track(vector_list: list[Vector | None]) -> None | VectorTrackType | None:
    """
    Converts list of Vectors to appropriate VectorTrack.
    :param vector_list: List of Vectors
    :return: VectorTrack.
    """
    val = None
    for i, _ in enumerate(vector_list):
        if vector_list[i] is not None:
            vector_list[i][0] = round(vector_list[i][0], 6)
            vector_list[i][1] = round(vector_list[i][1], 6)
            vector_list[i][2] = round(vector_list[i][2], 6)
            # Fix for negative zero appearing sometimes.
            vector_list[i][0] += 0.0
            vector_list[i][1] += 0.0
            vector_list[i][2] += 0.0
        if val is None:
            val = vector_list[i]
            continue
        if vector_list[i] == val:
            vector_list[i] = None
        else:
            val = vector_list[i]
    indexes = [i for i, vector in enumerate(vector_list) if vector is not None]
    if len(indexes) < 1:
        return None
    if len(indexes) == 1:
        track = FixedVectorTrackT()
        vector = vector_list[indexes[0]]
        val = vector[0], vector[1], vector[2]
        track.co = Vec3T()
        track.co.x, track.co.y, track.co.z = val
        return track
    if len(indexes) > 65535 or len(indexes) == len(vector_list):
        track = DynamicVectorTrackT()
        track.co = []
        vector = vector_list[indexes[0]]
        val = vector[0], vector[1], vector[2]
        for vector in vector_list:
            if vector is not None:
                val = vector[0], vector[1], vector[2]
            vec = Vec3T()
            vec.x, vec.y, vec.z = val
            track.co.append(vec)
        return track
    if len(indexes) < 256:
        track = Framed8VectorTrackT()
    else:
        track = Framed16VectorTrackT()
    track.frames = []
    track.co = []
    for i in indexes:
        vector = vector_list[i]
        val = vector[0], vector[1], vector[2]
        track.frames.append(i)
        vec = Vec3T()
        vec.x, vec.y, vec.z = val
        track.co.append(vec)
    return track


def quaternion_list_to_rotation_track(
        quat_list: list[Quaternion | None]) -> RotationTrackType | None:
    """
    Converts list of Quaternions to appropriate RotationTrack.
    :param quat_list: List of Quaternions
    :return: RotationTrack.
    """
    val = None
    for i, _ in enumerate(quat_list):
        if val is None:
            val = quat_list[i]
            continue
        if quat_list[i] == val:
            quat_list[i] = None
        else:
            val = quat_list[i]
    indexes = [i for i, quat in enumerate(quat_list) if quat is not None]
    if len(indexes) < 1:
        return None
    if len(indexes) == 1:
        track = FixedRotationTrackT()
        quat = quat_list[indexes[0]]
        val = pack_quaternion_to_48bit(quat)
        track.co = sVec3T()
        track.co.x, track.co.y, track.co.z = val
        return track
    if len(indexes) > 65535 or len(indexes) == len(quat_list):
        track = DynamicRotationTrackT()
        track.co = []
        quat = quat_list[indexes[0]]
        val = pack_quaternion_to_48bit(quat)
        for quat in quat_list:
            if quat is not None:
                val = pack_quaternion_to_48bit(quat)
            vec = sVec3T()
            vec.x, vec.y, vec.z = val
            track.co.append(vec)
        return track
    if len(indexes) < 256:
        track = Framed8RotationTrackT()
    else:
        track = Framed16RotationTrackT()
    track.frames = []
    track.co = []
    for i in indexes:
        quat = quat_list[i]
        val = pack_quaternion_to_48bit(quat)
        track.frames.append(i)
        vec = sVec3T()
        vec.x, vec.y, vec.z = val
        track.co.append(vec)
    return track


def vector_track_to_type(track: VectorTrackType) -> int:
    """
    Returns integer based on VectorTrack type.
    :param track: VectorTrack.
    :return: Integer.
    """
    if isinstance(track, FixedVectorTrackT):
        return 1
    if isinstance(track, DynamicVectorTrackT):
        return 2
    if isinstance(track, Framed16VectorTrackT):
        return 3
    if isinstance(track, Framed8VectorTrackT):
        return 4
    return 0


def rotation_track_to_type(track: RotationTrackType) -> int:
    """
    Returns integer based on RotationTrack type.
    :param track: RotationTrack.
    :return: Integer.
    """
    if isinstance(track, FixedRotationTrackT):
        return 1
    if isinstance(track, DynamicRotationTrackT):
        return 2
    if isinstance(track, Framed16RotationTrackT):
        return 3
    if isinstance(track, Framed8RotationTrackT):
        return 4
    return 0


def get_posebone_transforms(pose_bone: bpy.types.PoseBone) -> (Vector, Quaternion, Vector):
    """
    Gets armature space transforms of PoseBone.
    :param pose_bone: Target PoseBone.
    :return: Tuple of Translation, Rotation, Scale in armature space.
    """
    matrix = pose_bone.matrix
    if pose_bone.parent:
        matrix = pose_bone.parent.matrix.inverted() @ matrix
    translation = matrix.to_translation()
    rotation = matrix.to_quaternion()
    scale = pose_bone.matrix_basis.to_scale()
    return translation, rotation, scale


def get_all_track_transforms(context: bpy.types.Context, frame_range: (int, int)) -> dict[
    str, (list[Vector], list[Quaternion], list[Vector])]:
    """
    Gets transforms for each PoseBone of Armature on each frame of action.
    :param context: Blender's Context.
    :param frame_range: Frame range.
    :return: Dict containing PoseBone name and list of (Location, Rotation, Scale) transforms.
    """
    transforms = {}
    for i in range(frame_range[0], frame_range[1] + 1):
        context.scene.frame_set(i)
        for pose_bone in context.object.pose.bones:
            translation, rotation, scale = get_posebone_transforms(pose_bone)
            if pose_bone.name not in transforms:
                transforms.update({pose_bone.name: ([translation], [rotation], [scale])})
            else:
                transforms[pose_bone.name][0].append(translation)
                transforms[pose_bone.name][1].append(rotation)
                transforms[pose_bone.name][2].append(scale)
    return transforms
