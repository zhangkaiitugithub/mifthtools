# ***** BEGIN GPL LICENSE BLOCK *****
#
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.    See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ***** END GPL LICENCE BLOCK *****

import bpy
import bgl
import blf
import string
import bmesh

from bpy.props import *
from bpy.types import Operator, AddonPreferences

from bpy_extras import view3d_utils

import math
import mathutils as mathu
import random
from mathutils import Vector, Matrix

from . import mi_utils_base as ut_base
from . import mi_color_manager as col_man
from . import mi_linear_widget as l_widget


class MI_Linear_Deformer(bpy.types.Operator):
    """Draw a line with the mouse"""
    bl_idname = "mira.linear_deformer"
    bl_label = "LinearDeformer"
    bl_description = "Linear Deformer"
    bl_options = {'REGISTER', 'UNDO'}

    pass_keys = ['NUMPAD_0', 'NUMPAD_1', 'NUMPAD_3', 'NUMPAD_4',
                 'NUMPAD_5', 'NUMPAD_6', 'NUMPAD_7', 'NUMPAD_8',
                 'NUMPAD_9', 'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
                 'MOUSEMOVE']

    # curve tool mode
    tool_modes = ('IDLE', 'MOVE_POINT', 'DRAW_TOOL', 'SCALE_ALL', 'SCALE_FRONT', 'MOVE_ALL', 'TWIST', 'TAPE', 'ROTATE_ALL', 'BEND_ALL', 'BEND_SPIRAL')
    tool_mode = 'IDLE'

    lw_tool = None
    active_lw_point = None
    deform_mouse_pos = None
    deform_vec_pos = None

    bend_spiral_len = None

    start_work_center = None
    work_verts = None
    apply_tool_verts = None

    def invoke(self, context, event):
        reset_params(self)

        if context.area.type == 'VIEW_3D':
            # the arguments we pass the the callbackection
            args = (self, context)
            active_obj = context.scene.objects.active
            bm = bmesh.from_edit_mesh(active_obj.data)

            if bm.verts:
                work_verts = ut_base.get_selected_bmverts(bm)
                if not work_verts:
                    work_verts = bm.verts

                self.start_work_center = ut_base.get_vertices_center(work_verts, active_obj, False)
                self.work_verts = [vert.index for vert in work_verts]

                # Add the region OpenGL drawing callback
                # draw in view space with 'POST_VIEW' and 'PRE_VIEW'
                # self.lin_deform_handle_3d = bpy.types.SpaceView3D.draw_handler_add(lin_def_draw_3d, args, 'WINDOW', 'POST_VIEW')
                self.lin_deform_handle_2d = bpy.types.SpaceView3D.draw_handler_add(lin_def_draw_2d, args, 'WINDOW', 'POST_PIXEL')
                context.window_manager.modal_handler_add(self)

                return {'RUNNING_MODAL'}
            else:
                self.report({'WARNING'}, "No verts!!")
                return {'CANCELLED'}
        else:
            self.report({'WARNING'}, "View3D not found, cannot run operator")
            return {'CANCELLED'}


    def modal(self, context, event):
        context.area.tag_redraw()

        region = context.region
        rv3d = context.region_data
        m_coords = event.mouse_region_x, event.mouse_region_y
        active_obj = context.scene.objects.active
        bm = bmesh.from_edit_mesh(active_obj.data)

        # make picking
        if self.tool_mode == 'IDLE' and event.value == 'PRESS':
            if event.type in {'LEFTMOUSE', 'SELECTMOUSE'}:
                if self.lw_tool:
                    # pick point test
                    picked_point = pick_lw_point(context, m_coords, self.lw_tool)
                    if picked_point:
                        self.deform_mouse_pos = m_coords
                        self.active_lw_point = picked_point
                        #print(picked_point)

                        self.tool_mode = 'MOVE_POINT'
                else:
                    picked_point = ut_base.get_mouse_on_plane(context, self.start_work_center, None, m_coords)
                    if picked_point:
                        self.lw_tool = l_widget.MI_Linear_Widget()

                        self.lw_tool.start_point = l_widget.MI_LW_Point(picked_point.copy())
                        self.lw_tool.middle_point = l_widget.MI_LW_Point(picked_point.copy())
                        self.lw_tool.end_point = l_widget.MI_LW_Point(picked_point)

                        self.active_lw_point = self.lw_tool.end_point

                        self.tool_mode = 'MOVE_POINT'

            elif event.type in {'S', 'G', 'R', 'B', 'T'}:
                # set tool type
                if event.type == 'S':
                    if event.shift:
                        self.tool_mode = 'SCALE_FRONT'
                    else:
                        self.tool_mode = 'SCALE_ALL'
                elif event.type == 'R':
                    self.tool_mode = 'ROTATE_ALL'
                elif event.type == 'G':
                    self.tool_mode = 'MOVE_ALL'
                elif event.type == 'B':
                    if event.shift:
                        self.tool_mode = 'BEND_SPIRAL'
                    else:
                        self.tool_mode = 'BEND_ALL'
                elif event.type == 'T':
                    if event.shift:
                        self.tool_mode = 'TWIST'
                    else:
                        self.tool_mode = 'TAPE'

                # get tool verts
                if self.tool_mode in {'SCALE_FRONT', 'TAPE'}:
                    # do not clamp for SCALE_FRONT mode
                    self.apply_tool_verts = l_widget.get_tool_verts(self.lw_tool, self.work_verts, bm, active_obj, False)
                else:
                    self.apply_tool_verts = l_widget.get_tool_verts(self.lw_tool, self.work_verts, bm, active_obj, True)

                # set some settings for tools
                if self.tool_mode in {'SCALE_ALL', 'SCALE_FRONT', 'TAPE'}:
                    self.deform_mouse_pos = Vector(m_coords)

                elif self.tool_mode == 'MOVE_ALL':
                    mouse_pos_3d = ut_base.get_mouse_on_plane(context, self.lw_tool.start_point.position, None, m_coords)
                    self.deform_vec_pos = mouse_pos_3d  # 3d location

                elif self.tool_mode in {'ROTATE_ALL', 'TWIST', 'BEND_ALL', 'BEND_SPIRAL'}:
                    start_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, self.lw_tool.start_point.position)
                    self.deform_vec_pos = (Vector(m_coords) - start_2d).normalized()  # 2d direction
                    self.deform_mouse_pos = 0.0  # we will use it as angle counter

                    if self.tool_mode == 'BEND_SPIRAL':
                        self.bend_spiral_len = (Vector(m_coords) - start_2d).length


                return {'RUNNING_MODAL'}

        elif self.tool_mode == 'MOVE_POINT':
            if event.value == 'RELEASE':
                self.tool_mode = 'IDLE'
                return {'RUNNING_MODAL'}
            else:
                # move points
                new_point_pos = ut_base.get_mouse_on_plane(context, self.active_lw_point.position, None, m_coords)
                if self.active_lw_point.position == self.lw_tool.start_point.position or self.active_lw_point.position == self.lw_tool.end_point.position:
                    self.active_lw_point.position = new_point_pos
                    l_widget.update_middle_point(self.lw_tool)
                elif self.active_lw_point.position == self.lw_tool.middle_point.position:
                    self.lw_tool.start_point.position += new_point_pos - self.active_lw_point.position
                    self.lw_tool.end_point.position += new_point_pos - self.active_lw_point.position
                    self.lw_tool.middle_point.position = new_point_pos

                return {'RUNNING_MODAL'}

        elif self.tool_mode in {'SCALE_ALL', 'SCALE_FRONT', 'TAPE'}:
            if event.value == 'RELEASE' and event.type in {'LEFTMOUSE', 'SELECTMOUSE'}:
                self.tool_mode = 'IDLE'
            else:
                # move points
                start_point_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, self.lw_tool.start_point.position)
                if start_point_2d:
                    tool_dist = (start_point_2d - self.deform_mouse_pos).length
                    now_dist = (start_point_2d - Vector(m_coords)).length
                    apply_value = (now_dist - tool_dist) / tool_dist
                    if apply_value != 0.0:
                        tool_orig = active_obj.matrix_world.inverted() * self.lw_tool.start_point.position
                        tool_end = active_obj.matrix_world.inverted() * self.lw_tool.end_point.position
                        tool_vec = tool_end - tool_orig
                        tool_dir = (tool_end - tool_orig).normalized()
                        for vert_data in self.apply_tool_verts:
                            scale_vec = None
                            scale_value = vert_data[1]

                            if self.tool_mode == 'SCALE_ALL':
                                scale_vec = (vert_data[2] - tool_orig)
                            elif self.tool_mode == 'SCALE_FRONT':
                                scale_vec = (tool_end - tool_orig)
                            else:
                                # TAPE
                                scale_vec = vert_data[2] - ( tool_orig + (tool_dir * vert_data[1] * (tool_vec).length) )
                                scale_value = min(1.0, vert_data[1])

                            bm.verts[vert_data[0]].co = vert_data[2] + ( scale_vec * scale_value * apply_value)
                        bmesh.update_edit_mesh(active_obj.data)

            return {'RUNNING_MODAL'}

        elif self.tool_mode == 'MOVE_ALL':
            if event.value == 'RELEASE' and event.type in {'LEFTMOUSE', 'SELECTMOUSE'}:
                self.tool_mode = 'IDLE'
            else:
                mouse_pos_3d = ut_base.get_mouse_on_plane(context, self.lw_tool.start_point.position, None, m_coords)
                mouse_pos_3d = active_obj.matrix_world.inverted() * mouse_pos_3d
                start_pos = active_obj.matrix_world.inverted() * self.lw_tool.start_point.position
                orig_pos = active_obj.matrix_world.inverted() * self.deform_vec_pos
                orig_vec = orig_pos - start_pos
                move_vec = (mouse_pos_3d - start_pos) - orig_vec

                for vert_data in self.apply_tool_verts:
                    move_value = vert_data[1]
                    bm.verts[vert_data[0]].co = vert_data[2] + (move_vec * move_value)

                bmesh.update_edit_mesh(active_obj.data)

            return {'RUNNING_MODAL'}

        elif self.tool_mode in {'ROTATE_ALL', 'TWIST', 'BEND_ALL', 'BEND_SPIRAL'}:
            if event.value == 'RELEASE' and event.type in {'LEFTMOUSE', 'SELECTMOUSE'}:
                self.tool_mode = 'IDLE'
            else:
                m_coords = Vector(m_coords)  # convert into vector for operations
                start_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, self.lw_tool.start_point.position)
                new_vec_dir = (m_coords - start_2d).normalized()
                rot_angle = new_vec_dir.angle(self.deform_vec_pos)

                start_3d = active_obj.matrix_world.inverted() * self.lw_tool.start_point.position
                end_3d = active_obj.matrix_world.inverted() * self.lw_tool.end_point.position

                if rot_angle != 0.0:
                    vec_check_1 = Vector((new_vec_dir[0], new_vec_dir[1], 0))
                    vec_check_2 = Vector((new_vec_dir[0]-self.deform_vec_pos[0], new_vec_dir[1]-self.deform_vec_pos[1], 0))
                    checker_side_dir = vec_check_1.cross(vec_check_2).normalized()[2]
                    if checker_side_dir > 0.0:
                        rot_angle = -rot_angle

                    start_pos = active_obj.matrix_world.inverted() * self.lw_tool.start_point.position
                    rot_dir = None
                    if self.tool_mode in {'ROTATE_ALL', 'BEND_ALL', 'BEND_SPIRAL'}:
                        rot_dir = (rv3d.view_rotation * Vector((0.0, 0.0, -1.0))).normalized()
                    else:
                        # ROTATE_FRONT code
                        rot_dir = (end_3d - start_3d).normalized()

                    rot_angle += self.deform_mouse_pos  # add rot angle

                    bend_side_dir = None
                    faloff_len = None
                    spiral_value = 0.0
                    if self.tool_mode in {'BEND_ALL', 'BEND_SPIRAL'}:
                        bend_side_dir = (((end_3d - start_3d).normalized()).cross(rot_dir)).normalized()
                        faloff_len = end_3d - start_3d

                        if self.tool_mode == 'BEND_SPIRAL':
                            val_spin = None
                            if rot_angle > 0.0:
                                val_spin = ( 1.0 - ( (m_coords - start_2d).length / self.bend_spiral_len) )
                            else:
                                val_spin = (  ( (m_coords - start_2d).length / self.bend_spiral_len) )
                            spiral_value = 1.0 - ( faloff_len.length * val_spin )

                    for vert_data in self.apply_tool_verts:
                        apply_value = vert_data[1]
                        rot_mat = Matrix.Rotation(rot_angle * apply_value, 3, rot_dir)
                        vert = bm.verts[vert_data[0]]

                        if self.tool_mode in {'BEND_ALL', 'BEND_SPIRAL'}:
                            vert.co = vert_data[2] - ((faloff_len) * apply_value)

                            back_offset = (((faloff_len).length / (rot_angle * apply_value)) + spiral_value) * apply_value
                            vert.co += bend_side_dir * back_offset
                        else:
                            # set original position
                            vert.co[0] = vert_data[2][0]
                            vert.co[1] = vert_data[2][1]
                            vert.co[2] = vert_data[2][2]

                        vert.co = rot_mat * (vert.co - start_pos) + start_pos
                        self.deform_vec_pos = new_vec_dir

                        if self.tool_mode in {'BEND_ALL', 'BEND_SPIRAL'}:
                            back_offset = ((faloff_len).length / (rot_angle * apply_value)) * apply_value
                            vert.co -= bend_side_dir * back_offset

                        self.deform_mouse_pos = rot_angle  # set new angle rotation for next step

                    bmesh.update_edit_mesh(active_obj.data)

            return {'RUNNING_MODAL'}

        else:
            if event.value == 'RELEASE' and event.type in {'LEFTMOUSE', 'SELECTMOUSE'}:
                self.tool_mode = 'IDLE'
                return {'RUNNING_MODAL'}

        # main stuff
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            # bpy.types.SpaceView3D.draw_handler_remove(self.lin_deform_handle_3d, 'WINDOW')
            bpy.types.SpaceView3D.draw_handler_remove(self.lin_deform_handle_2d, 'WINDOW')

            # clear
            #display_bezier = None

            return {'FINISHED'}

        elif event.type in self.pass_keys:
            # allow navigation
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}


def reset_params(self):
    self.tool_mode = 'IDLE'
    self.deform_mouse_pos = None
    self.deform_vec_pos = None
    self.bend_spiral_len = None

    self.lw_tool = None
    self.active_lw_point = None

    self.start_work_center = None
    self.work_verts = None
    self.apply_tool_verts = None


def lin_def_draw_2d(self, context):
    # active_obj = context.scene.objects.active
    rv3d = context.region_data
    if self.lw_tool:
        lw_dir = (self.lw_tool.start_point.position - self.lw_tool.end_point.position).normalized()
        cam_view = (rv3d.view_rotation * Vector((0.0, 0.0, -1.0))).normalized()
        side_dir = lw_dir.cross(cam_view).normalized()
        l_widget.draw_lw(context, self.lw_tool, side_dir)


def pick_lw_point(context, m_coords, lw):
    region = context.region
    rv3d = context.region_data

    return_point = None
    good_distance = None

    mouse_coords = Vector(m_coords)

    lw_points = [lw.start_point, lw.middle_point, lw.end_point]
    for lw_point in lw_points:
        vec_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, lw_point.position)
        dist = (vec_2d - mouse_coords).length
        if dist <= 9.0:
            if not return_point:
                return_point = lw_point
                good_distance = dist
            elif good_distance > dist:
                return_point = lw_point

    return return_point
