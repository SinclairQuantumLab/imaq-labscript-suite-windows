#####################################################################
#                                                                   #
# /labscript_devices//labscript_devices.py                #
#                                                                   #
# Copyright 2019, Monash University and contributors                #
#                                                                   #
# This file is part of labscript_devices, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################

from labscript_devices.IMAQdxCamera.labscript_devices import IMAQdxCamera
import numpy as np

class HamamatsuCamera(IMAQdxCamera):
    description = "Hamamatsu scientific camera"

    def set_single_attribute(self, name, value):
        self.camera_attributes[name] = value
    
    def set_attribute_dict(self, dictionary):
        for key in dictionary.keys():
            self.camera_attributes[key] = dictionary[key]