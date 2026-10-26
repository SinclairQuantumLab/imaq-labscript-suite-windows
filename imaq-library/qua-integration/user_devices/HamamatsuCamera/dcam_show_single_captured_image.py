# dcam_show_single_captured_image.py : Jun 18, 2021
#
# Copyright (C) 2021 Hamamatsu Photonics K.K.. All right reserved.
#
# This sample source code just shows how to use DCAM-API.
# The performance is not guranteed.

"""
Sample script for showing a captured image with dcam.py
"""

from user_devices.HamamatsuCamera.dcam import *
import matplotlib as plt
# pip install opencv-python
#import cv2
from user_devices.HamamatsuCamera.attributes import *
test_camera_attributes={'exposure':100e-6,'triggerMode':2,'binning':1,
    'subarrayMode':2,
    'subarrayHsize':100,
    'subarrayVsize':100,
    'subarrayHpos':2200,
    'subarrayVpos':1460,
    'FrameBundEn':2,
    'FrameBundFrames':2
    }
def dcamtest_show_framedata(data):
    """
    Show numpy buffer as an image

    Arg1:   NumPy array
    """
    if data.dtype == np.uint16:
        imax = np.amax(data)
        if imax > 0:
            imul = int(65535 / imax)
            # print('Multiple %s' % imul)
            data = data * imul

        #cv2.imshow('test', data)
        #cv2.waitKey(0)
    else:
        print('-NG: dcamtest_show_image(data) only support Numpy.uint16 data')

def applyAttributes(camera,camera_attributes):
    for attribute in camera_attributes:
        if camera.prop_setvalue(attribute_encoding[attribute]['id'], camera_attributes[attribute]) is not False:
            pass
        else:
            print('-NG: Dcam.prop_setvalue() fails with error {}'.format(camera.lasterr()))

 
x=5
def dcam_show_single_captured_image(attributes,iDevice=0):
    """
    Capture and show a image
    """
    if Dcamapi.init() is not False:
        dcam = Dcam(iDevice)
        if dcam.dev_open() is not False:        
            applyAttributes(dcam,attributes)
            if dcam.buf_alloc(1) is not False:
                if dcam.cap_start(True) is not False:
                    timeout_milisec = 1000
                    while True:
                        if dcam.wait_capevent_frameready(timeout_milisec) is not False:
                            data = dcam.buf_getframe_bundle(-1)
                            plt.pyplot.imshow(data[1])
                            break

                        dcamerr = dcam.lasterr()
                        if dcamerr.is_timeout():
                            print('===: timeout')
                            continue

                        print('-NG: Dcam.wait_event() fails with error {}'.format(dcamerr))
                        break
                else:
                    print('-NG: Dcam.cap_start() fails with error {}'.format(dcam.lasterr()))

                dcam.buf_release()
            else:
                print('-NG: Dcam.buf_alloc(1) fails with error {}'.format(dcam.lasterr()))
            dcam.dev_close()
        else:
            print('-NG: Dcam.dev_open() fails with error {}'.format(dcam.lasterr()))
    else:
        print('-NG: Dcamapi.init() fails with error {}'.format(Dcamapi.lasterr()))

    Dcamapi.uninit()


if __name__ == '__main__':

     
    test_camera_attributes={'exposure':10e-6,'triggerMode':1,
    'subarrayMode':2,
    'subarrayHsize':16,
    'subarrayVsize':24,
    'subarrayHpos':2200,
    'subarrayVpos':1460,
    'FrameBundEn': 2,
    'FrameBundFrames': 2}
    
    dcam_show_single_captured_image(attributes=test_camera_attributes)
