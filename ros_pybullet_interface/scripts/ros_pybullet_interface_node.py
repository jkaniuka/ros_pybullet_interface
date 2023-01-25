#!/usr/bin/env python3
import pybullet
import traceback
from functools import partial

from rpbi.ros_node import RosNode
from rpbi.pybullet_instance import PybulletInstance
from rpbi.pybullet_visualizer import PybulletVisualizer
from rpbi.pybullet_robot import PybulletRobot
from rpbi.pybullet_visual_object import PybulletVisualObject
from rpbi.pybullet_dynamic_object import PybulletDynamicObject
from rpbi.pybullet_collision_object import PybulletCollisionObject
from rpbi.pybullet_rgbd_sensor import PybulletRGBDSensor
from rpbi.pybullet_soft_body import PybulletSoftBodyObject
from rpbi.pybullet_urdf import PybulletURDF

from ros_pybullet_interface.msg import PybulletObject
from ros_pybullet_interface.msg import ObjectDynamics
from ros_pybullet_interface.srv import AddPybulletObject, AddPybulletObjectResponse
from ros_pybullet_interface.srv import GetObjectDynamics, GetObjectDynamicsResponse
from ros_pybullet_interface.srv import ChangeObjectDynamics, ChangeObjectDynamicsResponse

from custom_ros_tools.config import load_config, load_configs
from cob_srvs.srv import SetString, SetStringResponse

class PybulletObjects(dict):

    def __init__(self, node):
        super().__init__()
        self.node = node

    def add(self, config, object_type):
        name = config['name']
        if name in self:
            raise KeyError(f'{name} already exists, pybullet objects must be given unique names!')
        self[name] = object_type(pybullet, self.node, config)

    def __setitem__(self, name, obj):
        if name in self:
            raise KeyError(f'{name} already exists, pybullet objects must be given unique names!')
        super().__setitem__(name, obj)
        # self.node.loginfo(f'added pybullet object "{name}"')

    def __delitem__(self, name):
        self[name].destroy()
        super().__delitem__(name)


class Node(RosNode):

    def __init__(self):

        # Initialize node
        super().__init__('ros_pybullet_interface')
        self.on_shutdown(self.close)

        # Get configuration
        self.config = self.get_param('~config')

        # Connect to pybullet
        self.pybullet_instance = PybulletInstance(pybullet, self)

        # Setup camera
        self.pybullet_visualizer = PybulletVisualizer(pybullet, self)

        # Collect pybullet objects
        self.pybullet_objects = PybulletObjects(self)

        def add_list(filenames, object_type):
            for filename in filenames:
                self.pybullet_objects.add(load_config(filename), object_type)

        add_list(self.config.get('visual_objects', []), PybulletVisualObject)
        add_list(self.config.get('collision_objects', []), PybulletCollisionObject)
        add_list(self.config.get('dynamic_objects', []), PybulletDynamicObject)
        add_list(self.config.get('robots', []), PybulletRobot)
        add_list(self.config.get('soft_objects', []), PybulletSoftBodyObject)
        add_list(self.config.get('urdfs', []), PybulletURDF)

        rgbd_sensor = self.config.get('rgbd_sensor')
        if rgbd_sensor:
            self.pybullet_objects.add(rgbd_sensor, PybulletRGBDSensor)

        # Start services
        self.Service('rpbi/add_pybullet_object', AddPybulletObject, self.service_add_pybullet_object)
        self.Service('rpbi/remove_pybullet_object', SetString, self.service_remove_pybullet_object)
        self.Service('rpbi/get_pybullet_object_dynamics', GetObjectDynamics, self.service_get_pybullet_object_dynamics)
        self.Service('rpbi/change_pybullet_object_dynamics', ChangeObjectDynamics, self.service_change_pybullet_object_dynamics)

        # Start pybullet
        if self.pybullet_instance.start_pybullet_after_initialization:
            self.pybullet_instance.start()

    def print_exc(self):
        err = traceback.format_exc()
        self.logerr("Traceback error:\n%s\n%s\n%s", "-"*70, err, "-"*70)

    @staticmethod
    def is_list_str(ls):
        return all(isinstance(el, str) for el in ls)

    @staticmethod
    def is_list_int(ls):
        return all(isinstance(el, int) for el in ls)

    @staticmethod
    def parse_options(options):

        # Special case
        if isinstance(options, int):
            return options

        # When string make list of strings
        if isinstance(options, str):
            options = options.split('|')

        # Make list of strings a list of ints
        if Node.is_list_str(options):
            options = [getattr(pybullet, opt) for opt in options]

        # Make list of ints an int
        if Node.is_list_int(options):
            out = options[0]
            for opt in options[1:]:
                out |= opt
            return out

        raise ValueError("did not recognize options type!")

    def service_add_pybullet_object(self, req):

        success = True
        message = 'added pybullet object'

        # Get object type
        if req.pybullet_object.object_type == PybulletObject.VISUAL:
            object_type = PybulletVisualObject
        elif req.pybullet_object.object_type == PybulletObject.COLLISION:
            object_type = PybulletCollisionObject
        elif req.pybullet_object.object_type == PybulletObject.DYNAMIC:
            object_type = PybulletDynamicObject
        elif req.pybullet_object.object_type == PybulletObject.ROBOT:
            object_type = PybulletRobot
        elif req.pybullet_object.object_type == PybulletObject.SOFT:
            object_type = PybulletSoftBodyObject
        elif req.pybullet_object.object_type == PybulletObject.URDF:
            object_type = PybulletURDF
        else:
            success = False
            message = f"did not recognize object type, given '{req.pybullet_object.object_type}', expected either 0, 1, 2, 3. See PybulletObject.msg"
            self.logerr(message)
            return AddPybulletObjectResponse(success=success, message=message)

        # Add using filename (if given)
        if req.pybullet_object.filename:
            try:
                self.pybullet_objects.add(load_config(req.pybullet_object.filename), object_type)
            except Exception as err:
                success = False
                message = str(err)
                self.print_exc()
                self.logerr(message)
            return AddPybulletObjectResponse(success=success, message=message)

        # Add using config string
        if req.pybullet_object.config:
            try:
                self.pybullet_objects.add(load_configs(req.pybullet_object.config), object_type)
            except Exception as err:
                success = False
                message = str(err)
                self.print_exc()
                self.logerr(message)
            return AddPybulletObjectResponse(success=success, message=message)

        success = False
        message = 'failed to add pybullet object, neither filename of config was given in request!'
        return AddPybulletObjectResponse(success=success, message=message)

    def service_get_pybullet_object_dynamics(self, req):

        success = True
        message = 'got pybullet object dynamics'

        # Get object
        if req.object_name in self.pybullet_objects:
            object = self.pybullet_objects[req.object_name]
        else:
            success = False
            message = f"did not recognize object name"
            self.logerr(message)
            return GetObjectDynamicsResponse(success=success, message=message, object_dynamics=None)
        
        # Get object type
        if isinstance(object, PybulletCollisionObject):
            object_type = PybulletCollisionObject
        elif isinstance(object, PybulletDynamicObject):
            object_type = PybulletDynamicObject
        else:
            success = False
            message = f"did not recognize object type"
            self.logerr(message)
            return GetObjectDynamicsResponse(success=success, message=message, object_dynamics=None)

        object_dynamics = object.get_dynamics()

        object_dynamics_msg = ObjectDynamics()
        object_dynamics_msg.mass = object_dynamics['mass']
        object_dynamics_msg.lateral_friction = object_dynamics['lateral friction']
        object_dynamics_msg.local_inertia_diagonal = object_dynamics['local inertia diagonal']
        object_dynamics_msg.local_inertia_pos = object_dynamics['local inertia pos']
        object_dynamics_msg.local_inertia_orn = object_dynamics['local inertia orn']
        object_dynamics_msg.restitution = object_dynamics['restitution']
        object_dynamics_msg.rolling_friction = object_dynamics['rolling friction']
        object_dynamics_msg.spinning_friction = object_dynamics['spinning friction']
        object_dynamics_msg.contact_damping = object_dynamics['contact damping']
        object_dynamics_msg.contact_stiffness = object_dynamics['contact stiffness']
        object_dynamics_msg.body_type = object_dynamics['body type']
        object_dynamics_msg.collision_margin = object_dynamics['collision margin']

        return GetObjectDynamicsResponse(success=success, message=message, object_dynamics=object_dynamics_msg)


    def service_change_pybullet_object_dynamics(self, req):

        success = True
        message = 'changed pybullet object dynamics'

        # Get object
        if req.object_name in self.pybullet_objects:
            object = self.pybullet_objects[req.object_name]
        else:
            success = False
            message = f"did not recognize object name"
            self.logerr(message)
            return ChangeObjectDynamicsResponse(success=success, message=message)

        # Get object type
        if isinstance(object, PybulletCollisionObject):
            object_type = PybulletCollisionObject
        elif isinstance(object, PybulletDynamicObject):
            object_type = PybulletDynamicObject
        else:
            success = False
            message = f"did not recognize object type"
            self.logerr(message)
            return ChangeObjectDynamicsResponse(success=success, message=message)
        
        object_dynamics_msg = req.object_dynamics
        object_dynamics = {}

        object_dynamics['mass'] = object_dynamics_msg.mass
        object_dynamics['lateralFriction'] = object_dynamics_msg.lateral_friction
        object_dynamics['localInertiaDiagonal'] = object_dynamics_msg.local_inertia_diagonal
        object_dynamics['restitution'] = object_dynamics_msg.restitution
        object_dynamics['rollingFriction'] = object_dynamics_msg.rolling_friction
        object_dynamics['spinningFriction'] = object_dynamics_msg.spinning_friction
        object_dynamics['contactDamping'] = object_dynamics_msg.contact_damping
        object_dynamics['contactStiffness'] = object_dynamics_msg.contact_stiffness
        object_dynamics['collisionMargin'] = object_dynamics_msg.collision_margin

        object.change_dynamics(object_dynamics)

        return ChangeObjectDynamicsResponse(success=success, message=message)


    def service_remove_pybullet_object(self, req):

        success = True
        message = 'removed pybullet object'
        name = req.data

        try:
            del self.pybullet_objects[name]

        except KeyError:
            success = False
            message = f'given object "{name}" does not exist!'

        except Exception as e:
            success = False
            message = 'failed to remove Pybullet object, exception: ' + str(e)
            self.print_exc()

        # Log message
        if success:
            self.loginfo(message)
        else:
            self.logerr(message)

        return SetStringResponse(message=message, success=success)

    def close(self):

        # Remove all objects
        while len(self.pybullet_objects.keys()):
            k = list(self.pybullet_objects.keys())[0]
            del self.pybullet_objects[k]

        # Disconnect pybullet
        self.pybullet_instance.close()


def main():
    Node().spin()

if __name__ == '__main__':
    main()
