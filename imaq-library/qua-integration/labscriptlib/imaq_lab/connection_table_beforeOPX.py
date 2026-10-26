from labscript import start, stop, add_time_marker, AnalogOut, DigitalOut, AnalogIn, Trigger
import labscript as lab
from labscript_devices.PulseBlasterUSB import PulseBlasterUSB
from labscript_devices.NI_DAQmx.models.NI_PXIe_6738 import NI_PXIe_6738
from labscript_devices.NI_DAQmx.models.NI_PXIe_6535 import NI_PXIe_6535
from labscript_devices.NI_DAQmx.models.NI_PXIe_6361 import NI_PXIe_6361
from labscript_devices.NI_DAQmx.models.NI_PXIe_2790 import NI_PXIe_2790
from user_devices.NICounter.labscript_devices import NICounter
from user_devices.HamamatsuCamera.labscript_devices import HamamatsuCamera
from labscript_devices.SpinnakerCamera.labscript_devices import SpinnakerCamera
from user_devices.GH3910.labscript_devices import GH3910
from user_devices.PicoScope2405A.labscript_devices import PicoScope2405A

def ConnectionTable():
   
    
    PulseBlasterUSB(
        name='pulseblaster_0',
        board_number=0, 
        )

    lab.ClockLine(
            name='ni_pxie_6738_1_clock',
            pseudoclock=pulseblaster_0.pseudoclock,
            connection='flag 0',
    )

    NI_PXIe_6738(
        name='ni_pxie_6738_1',
        parent_device=ni_pxie_6738_1_clock,
        clock_terminal='/PXI1Slot3/PFI0',
        MAX_name='PXI1Slot3',
        max_AO_sample_rate=100e3,
    )

    lab.ClockLine(
            name='ni_pxie_6738_2_clock',
            pseudoclock=pulseblaster_0.pseudoclock,
            connection='flag 6',
    ) 

    NI_PXIe_6738(
        name='ni_pxie_6738_2',
        parent_device=ni_pxie_6738_2_clock,
        clock_terminal='/PXI1Slot4/PFI0',
        MAX_name='PXI1Slot4',
        max_AO_sample_rate=100e3,
    )

    lab.ClockLine(
            name='ni_pxie_6535_clock',
            pseudoclock=pulseblaster_0.pseudoclock,
            connection='flag 1',
        )
    
    NI_PXIe_6535(
        name = 'ni_pxie_6535',
        parent_device =  ni_pxie_6535_clock,
        clock_terminal='/PXI1Slot6/PFI4',
        MAX_name= 'PXI1Slot6',
    )

    lab.ClockLine(
        name = 'ni_pxie_6361_clock',
        pseudoclock = pulseblaster_0.pseudoclock,
        connection = 'flag 3',
    )

    NI_PXIe_6361(
        name = 'ni_pxie_6361',
        parent_device = ni_pxie_6361_clock,
        clock_terminal = '/PXI1Slot9/PFI0',
        MAX_name = 'PXI1Slot9',
        acquisition_rate=62500,
    )

    DigitalOut(
        name='ni_pxie_6361_acquisition_trigger',
        parent_device=ni_pxie_6361,
        connection='port0/line0',
        default_value=0,
        )

    NICounter(
        name='ni_pxi_6602_counter0',
        parent_device=pulseblaster_0.direct_outputs,
        connection='flag 2',
        MAX_name='PXI1Slot5',
        counter_channel='PXI1Slot5/Ctr0',
        input_channel='/PXI1Slot5/PFI39',  # choose actual source terminal
        gate_channel='/PXI1Slot5/PFI38',   # choose actual gate terminal
    )

    NICounter(
        name='ni_pxi_6602_counter1',
        parent_device=pulseblaster_0.direct_outputs,
        connection='flag 7',
        MAX_name='PXI1Slot5',
        counter_channel='PXI1Slot5/Ctr1',
        input_channel='/PXI1Slot5/PFI35',
        gate_channel='/PXI1Slot5/PFI34',
    )

    GH3910(
        name='test_gh3910_aom_driver',
        serial_number=14523, 
    )

    # Spinnaker camera exposure time
    # Spinnaker ExposureTime is specified in microseconds.
    SPINNAKER_CAM1_EXPOSURE_US = 1000.0  # example: 1000 us = 1 ms
    SPINNAKER_CAM2_EXPOSURE_US = 1000.0  # example: 1000 us = 1 ms

    spinnaker_camera_attributes_cam1 = {
        # Exposure
        'AcquisitionControl::ExposureAuto': 'Off',
        'AcquisitionControl::ExposureMode': 'Timed',
        'AcquisitionControl::ExposureTime': SPINNAKER_CAM1_EXPOSURE_US,

        # Fixed analog gain in dB.
        'AnalogControl::GainAuto': 'Off',
        'AnalogControl::Gain': 8.0,

        # Central ~1/9 of full 2048 x 1536 sensor
        'ImageFormatControl::Width': 680,
        'ImageFormatControl::Height': 512,
        'ImageFormatControl::OffsetX': 884,
        'ImageFormatControl::OffsetY': 512,

        'AcquisitionControl::TriggerSelector': 'FrameStart',
        'AcquisitionControl::TriggerSource': 'Line3',
        'AcquisitionControl::TriggerActivation': 'RisingEdge',
        # Enable triggering after the trigger selector/source are configured.
        'AcquisitionControl::TriggerMode': 'On',
    }

    spinnaker_camera_attributes_cam2 = {
        # Exposure
        'AcquisitionControl::ExposureAuto': 'Off',
        'AcquisitionControl::ExposureMode': 'Timed',
        'AcquisitionControl::ExposureTime': SPINNAKER_CAM2_EXPOSURE_US,

        # Fixed analog gain in dB.
        'AnalogControl::GainAuto': 'Off',
        'AnalogControl::Gain': 8.0,

        # Central ~1/9 of full 2048 x 1536 sensor
        'ImageFormatControl::Width': 480,
        'ImageFormatControl::Height': 412,
        'ImageFormatControl::OffsetX': 884,
        'ImageFormatControl::OffsetY': 612,

        'AcquisitionControl::TriggerSelector': 'FrameStart',
        'AcquisitionControl::TriggerSource': 'Line3',
        'AcquisitionControl::TriggerActivation': 'RisingEdge',
        # Enable triggering after the trigger selector/source are configured.
        'AcquisitionControl::TriggerMode': 'On',
    }

    # BLACS manual/live-view acquisition must not wait for external TTL triggers.
    # Buffered shots still use the TriggerMode='On' settings above.
    spinnaker_manual_mode_camera_attributes = {
        'AcquisitionControl::TriggerMode': 'Off',
    }

    SpinnakerCamera(
        name="imaq_cam1",
        parent_device=pulseblaster_0.direct_outputs,
        connection='flag 8',
        serial_number=23397205,
        trigger_edge_type='rising',
        camera_attributes={**spinnaker_camera_attributes_cam1},
        manual_mode_camera_attributes={**spinnaker_manual_mode_camera_attributes},
    )    

    SpinnakerCamera(
        name="imaq_cam2",
        parent_device=pulseblaster_0.direct_outputs,
        connection='flag 9',
        serial_number=23397206,
        trigger_edge_type='rising',
        camera_attributes={**spinnaker_camera_attributes_cam2},
        manual_mode_camera_attributes={**spinnaker_manual_mode_camera_attributes},
    )

    DigitalOut(
        name='demo_do',
        connection='flag 17',
        default_value=0,
        parent_device=pulseblaster_0.direct_outputs,
    )


    
   #Hamamatsu Orca Quest 2 attributes and device 

    # HAMAMATSU_EXPOSURE = 5e-3
    # hamamatsu_camera_attributes={
    #     'exposure': HAMAMATSU_EXPOSURE,
    #     'triggerMode':2,#'binning':1,
    #     'TriggerGlobalExposure':5,
    #     'pixelType':2,
    #     'bufferpixelType':2,
    #     'triggerPolarity':2,
    #     'readoutMode':2,
    #     'subarrayMode':2,
    #     'subarrayHsize': 1024,
    #     'subarrayVsize': 1024,
    #     'subarrayHpos': 1600,
    #     'subarrayVpos': 4,
    #     'OutputTriggerKind':4,
    #     'OutputTriggerActive':1,
    #     'OutputTriggerPolarity':2
    # }

    # hamamatsu_manual_mode_camera_attributes={
    #     'exposure':1e-4,
    #     'triggerMode':1,
    #     'pixelType':2,
    #     'bufferpixelType':2,
    #     'subarrayMode':2,
    #     'readoutMode':2,
    # }

    # HamamatsuCamera(name='hamamatsu',
    #     parent_device= pulseblaster_0.direct_outputs,
    #     serial_number=241,
    #     connection='flag 4',
    #     camera_attributes=hamamatsu_camera_attributes,
    #     manual_mode_camera_attributes=hamamatsu_manual_mode_camera_attributes
    # )



    #Picoscope 2405A trigger and device


    PicoScope2405A(
        name="picoscope_2405a",
        parent_device=pulseblaster_0.direct_outputs,
        connection="flag 5",
        BLACS_connection="KX875/0014",
        default_trigger_channel="D",
        default_trigger_threshold_V=1.0,
    )

    #NI PXIe-6738 Card 1 AO Channels
    AnalogOut(
        name='c1_AO0',
        parent_device=ni_pxie_6738_1,
        connection='ao0',
        default_value=0.0,
    )

    AnalogOut(
        name='c1_AO1',
        parent_device=ni_pxie_6738_1,
        connection='ao1',
        default_value=0.0,
    )

    AnalogOut(
        name='c1_AO2',
        parent_device=ni_pxie_6738_1,
        connection='ao2',
        default_value=0.0,
    )

    AnalogOut(
        name='c1_AO3',
        parent_device=ni_pxie_6738_1,
        connection='ao3',
        default_value=0.0,
    )

    #NI PXIe-6738 Card 2 AO Channels
    AnalogOut(
        name='c2_AO0',
        parent_device=ni_pxie_6738_2,
        connection='ao0',
        default_value=0.0,
    )

    AnalogOut(
        name='c2_AO1',
        parent_device=ni_pxie_6738_2,
        connection='ao1',
        default_value=0.0,
    )

    AnalogOut(
        name='c2_AO2',
        parent_device=ni_pxie_6738_2,
        connection='ao2',
        default_value=0.0,
    )

    AnalogOut(
        name='c2_AO3',
        parent_device=ni_pxie_6738_2,
        connection='ao3',
        default_value=0.0,

    )

    AnalogOut(
        name='c2_AO11',
        parent_device=ni_pxie_6738_2,
        connection='ao11',
        default_value=0.0,
    )

    AnalogOut(
        name='c2_O13',
        parent_device=ni_pxie_6738_2,
        connection='ao13',
        default_value=0.0,
    )
    #Analog Outputs wired to LCOM1 and 2

    AnalogOut(
        name='repumper_aom_analog',
        parent_device=ni_pxie_6738_1,
        connection='ao16',
        default_value=0.7,
    )

    AnalogOut(
        name='mot_aom_analog',
        parent_device=ni_pxie_6738_1,
        connection='ao18',
        default_value=0.0,
    )

    AnalogOut(
        name="mot_gradient_analog",
        parent_device=ni_pxie_6738_1,
        connection='ao20',
        default_value=2.15,
        limits=(0, 2.3),
    )

    AnalogOut(
        name="c1_AO22",
        parent_device=ni_pxie_6738_1,
        connection='ao22',
        default_value=0.0,
    )

    AnalogOut(
        name="c1_AO24",
        parent_device=ni_pxie_6738_1,
        connection='ao24',
        default_value=0.0,
    )

    AnalogOut(
        name="c1_AO26",
        parent_device=ni_pxie_6738_1,
        connection='ao26',
        default_value=0.0,
    )

    AnalogOut(
        name="c1_AO28",
        parent_device=ni_pxie_6738_1,
        connection='ao28',
        default_value=0.0,
    )



    AnalogOut(
        name="c1_AO30",
        parent_device=ni_pxie_6738_1,
        connection='ao30',
        default_value=0.0,
    )

    # MOT coil analog control (card 2, PXI1Slot4/ao10).
    AnalogOut(
            name="c2_AO10",
            parent_device=ni_pxie_6738_2,
            connection='ao10',
            default_value=0,
        )

    # MOT repumper analog control (card 2, PXI1Slot4/ao12).
    AnalogOut(
        name="c2_AO12",
        parent_device=ni_pxie_6738_2,
        connection='ao12',
        limits=(-1.0, 1.0),
        default_value=0,
    )

    # MOT laser analog control (card 2, PXI1Slot4/ao14).
    AnalogOut(
        name="c2_AO14",
        parent_device=ni_pxie_6738_2,
        connection='ao14',
        limits=(0.0, 1.0),
        default_value=0,
    )

    # Dummy channel keeps card 2's analog output count even, as required by DAQmx.
    AnalogOut(
        name='c2_AO_dummy',
        parent_device=ni_pxie_6738_2,
        connection='ao15',
        default_value=0.0,
    )



    AnalogOut(
        name="c2_AO16",
        parent_device=ni_pxie_6738_2,
        connection='ao16',
        default_value=0.0,
    )

    AnalogOut(
        name="c2_AO18",
        parent_device=ni_pxie_6738_2,
        connection='ao18',
        default_value=0.0,
    )

    AnalogOut(
        name="c2_AO20",
        parent_device=ni_pxie_6738_2,
        connection='ao20',
        default_value=0.0,
    )

    AnalogOut(
        name="c2_AO22",
        parent_device=ni_pxie_6738_2,
        connection='ao22',
        default_value=0.0,
    )

    AnalogOut(
        name="c2_AO24",
        parent_device=ni_pxie_6738_2,
        connection='ao24',
        default_value=0.0,
    )

    AnalogOut(
        name="c2_AO26",
        parent_device=ni_pxie_6738_2,
        connection='ao26',
        default_value=0.0,
    )

    AnalogOut(
        name="c2_AO28",
        parent_device=ni_pxie_6738_2,
        connection='ao28',
        default_value=0.0,
    )

    AnalogOut(
        name="c2_AO30",
        parent_device=ni_pxie_6738_2,
        connection='ao30',
        default_value=0.0,
    )
    #NI PXIe-6535 Card DO Channels
   
    DigitalOut(
        name='do0',
        parent_device=ni_pxie_6535,
        connection='port0/line0',
        default_value=0,
    )

    DigitalOut(
        name='do8',
        parent_device=ni_pxie_6535,
        connection="port1/line0",  #DIO8
        default_value=0,
    )   
    DigitalOut(
        name='do9',
        parent_device=ni_pxie_6535,
        connection="port1/line1",  #DIO9
        default_value=0,
    ) 

    #Digital Outputs wired to LCOM1
    DigitalOut(
        name='do1',
        parent_device=ni_pxie_6535,
        connection="port0/line1",
        default_value=0,
    )

    DigitalOut(
        name='do2',
        parent_device=ni_pxie_6535,
        connection="port0/line2",
        default_value=0,
    )

    DigitalOut(
        name='do3',
        parent_device=ni_pxie_6535,
        connection="port0/line3",
        default_value=0,
    )

    DigitalOut(
        name='do4',
        parent_device=ni_pxie_6535,
        connection="port0/line4",
        default_value=0,
    )

    DigitalOut(
        name='do5',
        parent_device=ni_pxie_6535,
        connection="port0/line5",
        default_value=0,
    )

    DigitalOut(
        name='do6',
        parent_device=ni_pxie_6535,
        connection="port0/line6",
        default_value=0,
    )

    DigitalOut(
        name='do7',
        parent_device=ni_pxie_6535,
        connection="port0/line7",
        default_value=0,
    )

    DigitalOut(
        name='do16',
        parent_device=ni_pxie_6535,
        connection="port2/line0",
        default_value=0,
    )

    DigitalOut(
        name='do17',
        parent_device=ni_pxie_6535,
        connection="port2/line1",
        default_value=0,
    )

    DigitalOut(
        name='mot_aom_do',
        parent_device=ni_pxie_6535,
        connection="port2/line2",
        default_value=0,
    )

    DigitalOut(
        name='repumper_aom_do',
        parent_device=ni_pxie_6535,
        connection="port2/line3",
        default_value=0,
    )

    DigitalOut(
        name='do20',
        parent_device=ni_pxie_6535,
        connection="port2/line4",
        default_value=0,
    )

    DigitalOut(
        name='do21',
        parent_device=ni_pxie_6535,
        connection="port2/line5",
        default_value=0,
    )

    DigitalOut(
        name='mot_shutter_do',
        parent_device=ni_pxie_6535,
        connection="port2/line6",
        default_value=1,
    )

    DigitalOut(
        name='repumper_shutter_do',
        parent_device=ni_pxie_6535,
        connection="port2/line7",
        default_value=1,
    )

    # DigitalOut(
    #     name='mot_laser_do',
    #     parent_device=ni_pxie_6535,
    #     connection='port3/line0',  # DIO24
    #     default_value=0,
    # )

    # DigitalOut(
    #     name='mot_repumper_do',
    #     parent_device=ni_pxie_6535,
    #     connection='port3/line19',  # DIO25
    #     default_value=0,
    # )


    #NI PXIe-6361 Card AI Channels
    AnalogIn(
        name= 'ai0',
        parent_device=ni_pxie_6361,
        connection='ai0',
    )

    AnalogIn(
        name= 'ai1',
        parent_device=ni_pxie_6361,
        connection='ai1',
    )


    #Just so there are even number of DOs.
    scope_clock_dummy_2 = DigitalOut(
        name='scope_clock_dummy_2',
        parent_device=ni_pxie_6361,
        connection='port0/line1',
        default_value=0,
    )




if __name__ == '__main__':
    ConnectionTable()
    # Begin issuing labscript primitives
    # start() elicits the commencement of the shot
    start()

    # Stop the experiment shot with stop()
    stop(1.0)










# #Manual pulseblaster test button (toggle and read DO)
# pb_debug = lab.DigitalOut(
#     name='pb_debug',
#     parent_device=pulseblaster_0.direct_outputs,
#     connection='flag 1',
#     inverted=False,
#     default_value=0,
# )


#PrawnBlaster definition
    #PrawnBlaster(
    #    name='prawnblaster',
    #    com_port='COM10',
    #    num_pseudoclocks=2,
    #    pico_board='pico1'
    #)

    #     PrawnDo Definition
    #    PrawnDO(
    #         name='prawn_do',
    #         com_port='COM11',
    #         clock_line=prawnblaster.clocklines[1],
    #         pico_board='pico1'
    #     )

    #   DigitalOut('do0', prawn_do.outputs, 'do0')
    #     DigitalOut('do1', prawn_do.outputs, 'do1')
    #     DigitalOut('do10', prawn_do.outputs, 'do10')
    #     DigitalOut('do11', prawn_do.outputs, 'do11')
