#####################################################################
#                                                                   #
# /labscript_devices/AndorSolis/blacs_workers.py                    #
#                                                                   #
# Copyright 2019, Monash University and contributors                #
#                                                                   #
# This file is part of labscript_devices, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################
#from zprocess import rich_print
from labscript_devices.IMAQdxCamera.blacs_workers import MockCamera, IMAQdxCameraWorker
import sys
import threading
import numpy as np
from labscript_utils import dedent
import labscript_utils.h5_lock
import h5py
import labscript_utils.properties

sys.path.append(r"C:\Users\imaq\labscript-suite\userlib\user_devices\HamamatsuCamera")
from labscript_utils.ls_zprocess import Context
import time as time
from labscript_utils.properties import set_attributes
#from user_devices.Rydberg.AndorCamera.andor_sdk.andor_solis import *
from dcam import *
from attributes import *
from labscript_utils.ls_zprocess import Context
from labscript_utils.shared_drive import path_to_local
from labscript_utils.properties import set_attributes
import zmq
from time import perf_counter
from pathlib import Path


class HamamatsuCamera(object):

    def __init__(self,iDevice=0):
        #set to predefined attribute list           
        self.attributes=default_attributes
        #self.camera_attributes=camera_attributes
        #update with user values
        #self.set_user_attributes()
        
        if Dcamapi.init() is not False:
            dcam = Dcam(iDevice)
            self.camera=dcam
            if dcam.dev_open() is not False:
                pass
        
        #self.configure_acquisition(camera_attributes)
       
    def set_attributes(self, attr_dict):
        self.attributes.update(attr_dict)
        
    def set_attribute(self, name, value):
        self.attributes[name] = value

    def get_attribute_names(self, visibility_level, writeable_only=True):
        return list(self.attributes.keys())

    def get_attribute(self, name):
        return self.attributes[name]
    
    # def grab(self):        
    #     data = self.camera.buf_getlastframedata()
    #     return data
    
    def grab(self):        
        data = self.snap()
        return data
   
    def abort_acquisition(self):
        self.camera.dev_close()
        
    def set_user_attributes(self):
        for attribute in self.camera_attributes:
            try:
                self.attributes[attribute]['value']=self.camera_attributes[attribute]
            except:
                print('Error setting attribute: '+attribute)    

   
    def grab_multiple(self, n_images, images, waitForNextBuffer=True):
        print(f"Attempting to grab {n_images}images.")
        timeout_ms=10000
        #if self.camera.wait_capevent_frameready(timeout_ms) is not False:
        if self.camera.wait_event(eventmask= 0x0004, timeout_millisec=timeout_ms):
            for i in range(n_images):
                print(self.camera.cap_status())
                        
                    
               
                images.append(self.camera.buf_getframedata(i))
                print(f"Got  image {i+1} of {n_images}.")
                print(np.shape(images))
        else:
            dcamerr = self.camera.lasterr()
            print('-NG: Dcam.wait_event() fails with error {}'.format(dcamerr))
            if dcamerr.is_timeout():
                print('===: timeout')    
        
      
            

    def stop_acquisition(self):
        pass
    
    def configure_acquisition(self,camera_attributes=default_attributes,bufferCount=1,iDevice=0):

        self.camera.buf_release()
        for attribute in camera_attributes:
            # time.sleep(0.01)
            if self.camera.prop_setvalue(attribute_encoding[attribute]['id'], camera_attributes[attribute]) is not False:
                pass
            else:
                err = self.camera.lasterr()
                print('-NG: Dcam.prop_setvalue() fails with error {}'.format(err))
                raise Exception("Failed to set {} with error {}".format(attribute, err))

        if self.camera.buf_alloc(bufferCount) is not False:
            pass
        else:
            print('-NG: Dcam.buf_alloc(1) fails with error {}'.format(self.camera.lasterr()))
            self.camera.dev_close()
        
    def snap2(self,iDevice=0):
        """
        Capture an image
        """
        dcam=self.camera
        #if dcam.dev_open() is not False:
        dcam.buf_release()
        #dcam.cap_start(bSequence=True)
        if dcam.buf_alloc(1) is not False:
            if dcam.cap_snapshot() is not False:
                timeout_milisec = 1000
                while True:
                    if dcam.wait_capevent_frameready(timeout_milisec) is not False:
                        data = dcam.buf_getlastframedata()
                        return data
                        #dcamtest_show_framedata(data)
                        break
                        
                    dcamerr = dcam.lasterr()
                    if dcamerr.is_timeout():
                        print('===: timeout')
                        break
                        #continue

                    print('-NG: Dcam.wait_event() fails with error {}'.format(dcamerr))
                    break
            else:
                print('-NG: Dcam.cap_start() fails with error {}'.format(dcam.lasterr()))

            dcam.buf_release()
        else:
            print('-NG: Dcam.buf_alloc(1) fails with error {}'.format(dcam.lasterr()))
            dcam.dev_close()
            
            
    def snap(self,iDevice=0):
        """
        Capture an image
        """
        dcam=self.camera
        #if dcam.dev_open() is not False:

        if dcam.cap_snapshot() is not False:
            timeout_milisec = 1000
            while True:
                if dcam.wait_capevent_frameready(timeout_milisec) is not False:
                    data = dcam.buf_getlastframedata()
                    return data
                    #dcamtest_show_framedata(data)
                    break
                    
                dcamerr = dcam.lasterr()
                if dcamerr.is_timeout():
                    print('===: timeout')
                    break
                    #continue
   
                print('-NG: Dcam.wait_event() fails with error {}'.format(dcamerr))
                break
        else:
            print('-NG: Dcam.cap_start() fails with error {}'.format(dcam.lasterr()))
   
            dcam.buf_release()

    
       # dcam.cap_stop(bSequence=True)


    def close(self):
        Dcamapi.uninit()




class HamamatsuCameraWorker(IMAQdxCameraWorker):
    interface_class = HamamatsuCamera
   
    def init(self):
        self.camera = self.get_camera()
        print("Setting attributes...")
        self.smart_cache = {}
        self.set_attributes_smart(self.camera_attributes)
        self.set_attributes_smart(self.manual_mode_camera_attributes)
        self.camera.configure_acquisition(self.manual_mode_camera_attributes)
        print('Sensor temperature is: '+str(self.camera.camera.prop_getvalue(DCAM_IDPROP.SENSORTEMPERATURE))+' C')
        print("Initialisation complete")
        self.images = None
        self.n_images = None
        self.attributes_to_save = None
        self.exposures = None
        self.acquisition_thread = None
        self.h5_filepath = None
        self.stop_acquisition_timeout = None
        self.exception_on_failed_shot = None
        self.continuous_stop = threading.Event()
        self.continuous_thread = None
        self.continuous_dt = None
        self.image_socket = Context().socket(zmq.REQ)
        self.image_socket.connect(
            f'tcp://{self.parent_host}:{self.image_receiver_port}'
       )
        
    def get_camera(self):
        """ Andor cameras may not be specified by serial numbers"""
       
        return self.interface_class()
      
    def get_attributes_as_dict(self, visibility_level):
        """Return a dict of the attributes of the camera for the given visibility
        level"""
        return self.camera.attributes
    
    def maxFrameRate(self):
        Exp1=self.camera_attributes['exposure']
        H1=7.2*1e-6
        Exp2=np.ceil(Exp1/H1)
        Vn1=self.camera_attributes['subarrayVsize']
        Vn2=Vn1/2+5
        #todo add conditions: this is for standard scan coaxpress external trigger
        mFR=np.floor(1/(Vn2+Exp2+3)/H1)

        return mFR

    def set_attributes_smart(self, attributes):
        """Call self.camera.set_attributes() to set the given attributes, only setting
        those that differ from their value in, or are absent from self.smart_cache.
        Update self.smart_cache with the newly-set values"""
        uncached_attributes = {}
        for name, value in attributes.items():
            if name not in self.smart_cache or self.smart_cache[name] != value:
                uncached_attributes[name] = value
                self.smart_cache[name] = value
                
        self.camera.set_attributes(uncached_attributes)
    
    def transition_to_buffered(self, device_name, h5_filepath, initial_values, fresh):
        if getattr(self, 'is_remote', False):
            h5_filepath = path_to_local(h5_filepath)
        if self.continuous_thread is not None:
            # Pause continuous acquistion during transition_to_buffered:
            self.stop_continuous(pause=True)
        if not Path(h5_filepath).exists(): # Added November 4th 2022 to prevent it from looking for the
            # file before it exists (MP)
            print(h5_filepath)
            print("Failed to find file, waiting 100 ms")
            time.sleep(.1)
        if Path(h5_filepath).exists():    #comment me out patchy solution... 04/04/2023 (AJM)
            with h5py.File(h5_filepath, 'r') as f: #and push me back starting here and ending before return {}
                group = f['devices'][self.device_name]
                if not 'EXPOSURES' in group:
                    return {}
                self.h5_filepath = h5_filepath
                self.exposures = group['EXPOSURES'][:]
                self.n_images = len(self.exposures)

                # Get the camera_attributes from the device_properties
                properties = labscript_utils.properties.get(
                    f, self.device_name, 'device_properties'
                )
                camera_attributes = properties['camera_attributes']
                self.stop_acquisition_timeout = properties['stop_acquisition_timeout']
                self.exception_on_failed_shot = properties['exception_on_failed_shot']
                saved_attr_level = properties['saved_attribute_visibility_level']
                tau2=1
                for exposure in self.exposures:
                    tau1=exposure['t']
                    dtau=np.abs(tau2-tau1)
                    tau2=exposure['t']
                    if 1/self.maxFrameRate()>=dtau:
                        raise Exception('Time difference between frames dt:'+str(dtau)+' too short.')
            # Only reprogram attributes that differ from those last programmed in, or all of
            # them if a fresh reprogramming was requested:
            if fresh:
                self.smart_cache = {}
            self.set_attributes_smart(camera_attributes)
            #Get the camera attributes, so that we can save them to the H5 file:
            if saved_attr_level is not None:
                self.attributes_to_save = self.get_attributes_as_dict(saved_attr_level)
            else:
                self.attributes_to_save = None
            print(f"Configuring camera for {self.n_images} images.")
            #self.camera.configure_acquisition(continuous=False, bufferCount=self.n_images)
            self.camera.configure_acquisition(self.smart_cache, bufferCount=self.n_images)
            #time.sleep(5)
            self.camera.camera.cap_start(bSequence=True)
            
            self.images = []

            self.acquisition_thread = threading.Thread(
                target=self.camera.grab_multiple,
                args=(self.n_images, self.images),
                daemon=True,
            )
            self.acquisition_thread.start() 
        

        return {}
   
    def continuous_loop(self, dt):
        """Acquire continuously in a loop, with minimum repetition interval dt"""
        while True:
            if dt is not None:
                t = perf_counter()
            image = self.camera.grab()
            self._send_image_to_parent(image)
            if dt is None:
                timeout = 0
            else:
                timeout = t + dt - perf_counter()
            if self.continuous_stop.wait(timeout):
                self.continuous_stop.clear()
                break

    def start_continuous(self, dt):
        """Begin continuous acquisition in a thread with minimum repetition interval
        dt"""
        assert self.continuous_thread is None
        #self.camera.configure_acquisition()
        self.continuous_thread = threading.Thread(
            target=self.continuous_loop, args=(dt,), daemon=True
        )
        self.continuous_thread.start()
        self.continuous_dt = dt

    def stop_continuous(self, pause=False):
        """Stop the continuous acquisition thread"""
        assert self.continuous_thread is not None
        self.continuous_stop.set()
        self.continuous_thread.join()
        self.continuous_thread = None
        self.camera.stop_acquisition()
        # If we're just 'pausing', then do not clear self.continuous_dt. That way
        # continuous acquisition can be resumed with the same interval by calling
        # start(self.continuous_dt), without having to get the interval from the parent
        # again, and the fact that self.continuous_dt is not None can be used to infer
        # that continuous acquisiton is paused and should be resumed after a buffered
        # run is complete:
        if not pause:
            self.continuous_dt = None

    def transition_to_manual(self):
        # self.acquisition_thread = threading.Thread(
        #     target=self.camera.grab_multiple,
        #     args=(self.n_images, self.images),
        #     daemon=True,
        # )
        # self.acquisition_thread.start() # commented out Nov 3rd 2022
        
        if self.h5_filepath is None:
            print('No camera exposures in this shot.\n')
            return True
        assert self.acquisition_thread is not None
        self.acquisition_thread.join(timeout=self.stop_acquisition_timeout)
        if self.acquisition_thread.is_alive():
            msg = """Acquisition thread did not finish. Likely did not acquire expected
                number of images. Check triggering is connected/configured correctly"""
            if self.exception_on_failed_shot:
                self.abort()
                raise RuntimeError(dedent(msg))
            else:
                self.camera.abort_acquisition()
                self.acquisition_thread.join()
                print(dedent(msg), file=sys.stderr)
        self.acquisition_thread = None
        self.camera.camera.buf_release()
        print("Stopping acquisition.")
        self.camera.camera.cap_stop()

       # self.camera.stop_acquisition()
        #self.camera.close_shutter() #  added 10th Jan 

        print(f"Saving {len(self.images)}/{len(self.exposures)} images.")

        with h5py.File(self.h5_filepath, 'r+') as f:
            # Use orientation for image path, device_name if orientation unspecified
            if self.orientation is not None:
                image_path = 'images/' + self.orientation
            else:
                image_path = 'images/' + self.device_name
            image_group = f.require_group(image_path)
            image_group.attrs['camera'] = self.device_name

            # Save camera attributes to the HDF5 file:
            if self.attributes_to_save is not None:
                set_attributes(image_group, self.attributes_to_save)

            # Whether we failed to get all the expected exposures:
            image_group.attrs['failed_shot'] = len(self.images) != len(self.exposures)

            # key the images by name and frametype. Allow for the case of there being
            # multiple images with the same name and frametype. In this case we will
            # save an array of images in a single dataset.
            images = {
                (exposure['name'], exposure['frametype']): []
                for exposure in self.exposures
            }

            # Iterate over expected exposures, sorted by acquisition time, to match them
            # up with the acquired images:
            self.exposures.sort(order='t')
            for image, exposure in zip(self.images, self.exposures):
                images[(exposure['name'], exposure['frametype'])].append(image)
            #print(len(self.images))

            # Save images to the HDF5 file:
            for (name, frametype), imagelist in images.items():
                data = imagelist[0] if len(imagelist) == 1 else np.array(imagelist)
                print(f"Saving frame(s) {name}/{frametype}.")
                group = image_group.require_group(name)
                dset = group.create_dataset(
                    frametype, data=data, dtype='uint16', compression='gzip'
                )
                # Specify this dataset should be viewed as an image
                dset.attrs['CLASS'] = np.bytes_('IMAGE')
                dset.attrs['IMAGE_VERSION'] = np.bytes_('1.2')
                dset.attrs['IMAGE_SUBCLASS'] = np.bytes_('IMAGE_GRAYSCALE')
                dset.attrs['IMAGE_WHITE_IS_ZERO'] = np.uint8(0)
                for attr in self.camera_attributes:
                    dset.attrs[attr] = self.camera_attributes[attr]                
                dset.attrs['Sensor temperature'] = str(self.camera.camera.prop_getvalue(DCAM_IDPROP.SENSORTEMPERATURE))+' C'
        # If the images are all the same shape, send them to the GUI for display:
        try:
            image_block = np.stack(self.images)
        except ValueError:
            print("Cannot display images in the GUI, they are not all the same shape")
        else:
            # Changed from sending the full image stack to only the first image to blacs GUI
            self._send_image_to_parent(image_block[0])

        self.images = None
        self.n_images = None
        self.attributes_to_save = None
        self.exposures = None
        self.h5_filepath = None
        self.stop_acquisition_timeout =  None
        self.exception_on_failed_shot = None
        print("Setting manual mode camera attributes.\n")
        self.set_attributes_smart(self.manual_mode_camera_attributes)
        self.camera.configure_acquisition(self.manual_mode_camera_attributes)
        self.camera.camera.buf_release()
        #dcam.cap_start(bSequence=True)
        #print(self.camera.get_attribute())
        self.camera.camera.buf_alloc(1)

        if self.continuous_dt is not None:
            # If continuous manual mode acquisition was in progress before the bufferd
            # run, resume it:
            self.start_continuous(self.continuous_dt)
        return True

        
def main():
    cam=HamamatsuCamera()
    #camWorker=HamatsuCameraWorker(IMAQdxCameraWorker)
   # camWorker.transition_to_buffered("testdevice","C:\\Users\\RoyTest\\Documents\\test.h5",0,True)
    data=cam.snap()
    
    data=cam.snap()

    cam.close()
    #camWorker.close()

if __name__ == "__main__":
    main()


    # def transition_to_buffered ( self , device_name , h5_file,
    # initial_values , fresh ):
        
    #     self.h5_filepath = h5_file
    #     self.device_name = device_name

    #     with h5py.File(self.h5_filepath, 'r') as hdf5_file:
            
    #         devices = hdf5_file['devices'][device_name]
    #         image=self.snap()
        
    # def transition_to_manual(self):
    #     if self.h5_filepath is None:
    #         print('No camera exposures in this shot.\n')
    #         return True
        
    #     with h5py.File(self.h5_filepath, 'r+') as f:
    #         # Use orientation for image path, device_name if orientation unspecified
           
    #         image_path = 'images/' + self.device_name
    #         image_group = f.require_group(image_path)
    #         image_group.attrs['camera'] = self.device_name

    # def transition_to_manual(self):
    #     if self.h5_filepath is None:
    #         print('No camera exposures in this shot.\n')
    #         return True
    #     assert self.acquisition_thread is not None
    #     self.acquisition_thread.join(timeout=self.stop_acquisition_timeout)
    #     if self.acquisition_thread.is_alive():
    #         msg = """Acquisition thread did not finish. Likely did not acquire expected
    #             number of images. Check triggering is connected/configured correctly"""
    #         if self.exception_on_failed_shot:
    #             self.abort()
    #             raise RuntimeError(dedent(msg))
    #         else:
    #             self.camera.abort_acquisition()
    #             self.acquisition_thread.join()
    #             print(dedent(msg), file=sys.stderr)
    #     self.acquisition_thread = None

    #     print("Stopping acquisition.")
    #     self.camera.stop_acquisition()
    #     self.camera.close_shutter()

    #     print(f"Saving {len(self.images)}/{len(self.exposures)} images.")

    #     with h5py.File(self.h5_filepath, 'r+') as f:
    #         # Use orientation for image path, device_name if orientation unspecified
    #         if self.orientation is not None:
    #             image_path = 'images/' + self.orientation
    #         else:
    #             image_path = 'images/' + self.device_name
    #         image_group = f.require_group(image_path)
    #         image_group.attrs['camera'] = self.device_name

    #         # Save camera attributes to the HDF5 file:
    #         if self.attributes_to_save is not None:
    #             set_attributes(image_group, self.attributes_to_save)

    #         # Whether we failed to get all the expected exposures:
    #         image_group.attrs['failed_shot'] = len(self.images) != len(self.exposures)

    #         # key the images by name and frametype. Allow for the case of there being
    #         # multiple images with the same name and frametype. In this case we will
    #         # save an array of images in a single dataset.
    #         images = {
    #             (exposure['name'], exposure['frametype']): []
    #             for exposure in self.exposures
    #         }

    #         # Iterate over expected exposures, sorted by acquisition time, to match them
    #         # up with the acquired images:
    #         self.exposures.sort(order='t')
    #         for image, exposure in zip(self.images, self.exposures):
    #             images[(exposure['name'], exposure['frametype'])].append(image)

    #         # Save images to the HDF5 file:
    #         for (name, frametype), imagelist in images.items():
    #             data = imagelist[0] if len(imagelist) == 1 else np.array(imagelist)
    #             print(f"Saving frame(s) {name}/{frametype}.")
    #             group = image_group.require_group(name)
    #             dset = group.create_dataset(
    #                 frametype, data=data, dtype='uint16', compression='gzip'
    #             )
    #             # Specify this dataset should be viewed as an image
    #             dset.attrs['CLASS'] = np.string_('IMAGE')
    #             dset.attrs['IMAGE_VERSION'] = np.string_('1.2')
    #             dset.attrs['IMAGE_SUBCLASS'] = np.string_('IMAGE_GRAYSCALE')
    #             dset.attrs['IMAGE_WHITE_IS_ZERO'] = np.uint8(0)

    #     # If the images are all the same shape, send them to the GUI for display:
    #     try:
    #         image_block = np.stack(self.images)
    #     except ValueError:
    #         print("Cannot display images in the GUI, they are not all the same shape")
    #     else:
    #         # Changed from sending the full image stack to only the first image to blacs GUI
    #         self._send_image_to_parent(image_block[0])

    #     self.images = None
    #     self.n_images = None
    #     self.attributes_to_save = None
    #     self.exposures = None
    #     self.h5_filepath = None
    #     self.stop_acquisition_timeout = None
    #     self.exception_on_failed_shot = None
    #     print("Setting manual mode camera attributes.\n")
    #     self.set_attributes_smart(self.manual_mode_camera_attributes)
    #     if self.continuous_dt is not None:
    #         # If continuous manual mode acquisition was in progress before the bufferd
    #         # run, resume it:
    #         self.start_continuous(self.continuous_dt)
    #     return True

