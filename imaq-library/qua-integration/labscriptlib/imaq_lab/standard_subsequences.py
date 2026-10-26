"""A library of parts of sequences that are common to many sequences.

This module is intended to be used to store functions that generate parts of
sequences. In particular, this module is intended to store common subsequences
that will be used in many sequences, such as those for loading the MOT or doing
absorption imaging. More unique/specific subsequences should be stored
elsewhere, possibly in the same file as the sequence that uses it. Additionally,
helper functions and the like that control outputs but that don't quite qualify
as making subsequences are stored in sequence_utils.py. For example, the
function open_shuttered_beam() which turns off a beam's AOM, opens its shutter,
then turns on the AOM at the desired time is stored in sequence_utils.py. On the
other hand, the function load_mot() has all of the code that sets all of the
outputs to load the MOT, so it is stored here. Note that some functions from
sequence_utils.py are imported directly into the namespace of this module with
the "from bar import foo" style syntax (e.g.open_shuttered_beam()), which means
that they are actually accessible by importing this module just as if they were
defined in this module.
"""
# Adjust pylint and pyright to ignore undefined variables since they can't
# distinguish them from globals set up by labscript or objects defined in the
# connectiontable.
# pylint: disable=undefined-variable
# pyright: reportUndefinedVariable=false

import warnings

import numpy as np

import labscript as lab
from labscriptlib.imaq_lab.sequence_utils import (
    open_shuttered_beam,
    close_shuttered_beam,
    jump_from_previous_value,
    set_previous_value)


def set_static_parameters():
    """Configure things that do not change during the sequence.

    This function is intended to have all the sequence-specific code that does
    things to configure the machine before running the sequence.
    """
    # Set the region of interest of the camera. This is the only region of the
    # image that we actually save to disk.
    camera_attributes = camera.camera_attributes
    camera_ROI = {
        'offsetX': camera_roi_offsetX,
        'offsetY': camera_roi_offsetY,
        'width': camera_roi_width,
        'height': camera_roi_height,
    }
    camera_attributes['ROI'] = camera_ROI
    camera.set_property(
        'camera_attributes',
        camera_attributes,
        location="device_properties",
        overwrite=True,
    )




def set_scope_trigger(sequence_duration=None):
    """Add a 1 ms long pulse to trigger oscilloscopes.

    We have an output that we call scope_trigger that we typically use to
    trigger oscilloscopes to take traces in sync with the sequence. The time of
    the rising edge of the scope trigger is set by the scope_trigger_time
    global. That time sets when the rising edge on that channel occurs. That
    output then stays high for 1 ms, then returns low (assuming no other code
    changes the behavior of that channel). So to trigger a scope at the time
    set by the global, connect the scope_trigger output to the oscilloscope, and
    set oscilloscope to trigger on a rising edge.

    If the set scope_trigger_time values is at or  before zero, a warning will
    be printed and the scope will be triggered 1 ms after the start of the
    sequence instead. Similarly, if sequence_duration is provided and the value
    of scope_trigger_time is after the end of the sequence, or too close to it,
    then the scope trigger will occur 2 ms before the end of the sequence and a
    warning will be printed. This code assumes that the sequence is over 2 ms
    long, but that probably won't be an issue in practice.

    Args:
        sequence_duration (float, optional): (Default=None) (seconds) If
            sequence_duration is provided, this function will perform a check to
            make sure that the scope trigger isn't set to happen after the end
            of the sequence (or too close to it). If it is not provided, then
            that check will not be performed, which may lead runmanager to throw
            an error when attempting to compile the sequence.

    Returns:
        scope_trigger_time_actual (float): (seconds) The time of the scope
            trigger's rising edge. This can different than the value of the
            scope_trigger_time global, namely if that global specifies a time
            that is too early or too late for the sequence.
    """
    # Set the scope trigger channel to go high at the set time, or right before
    # the end of the sequence if it's set time is after the sequence finishes.

    scope_trigger_time_actual = scope_trigger_time

    # Make sure scope trigger time isn't before t=0.
    if scope_trigger_time <= 0:
        warning_message = ("scope_trigger_time is before the start of the "
                           "sequence, setting it to 1 ms after start of "
                           "sequence.")
        warnings.warn(warning_message)
        scope_trigger_time_actual = 1e-3

    # If sequence_duration is provided, make sure scope trigger edges aren't
    # after the end of the sequence.
    if sequence_duration:
        if scope_trigger_time + 1e-3 >= sequence_duration:
            warning_message = ("scope_trigger_time is after end of sequence or "
                               "too close to the end of the sequence, setting "
                               "it to 2 ms before end of sequence.")
            warnings.warn(warning_message)
            scope_trigger_time_actual = sequence_duration - 2e-3

    # Actually output the pulse at the correct time.
    scope_trigger.go_high(scope_trigger_time_actual)
    scope_trigger.go_low(scope_trigger_time_actual + 1e-3)

    return scope_trigger_time_actual


def _fix_clock_error_pulseblaster():
    """Subsequence for fixing occasional clocking error with the digital card.

    This version of the clock error correction sequence is designed to work with
    the PulseBlaster instead of the PineBlaster.

    In order for this to work, the clock error correction circuit must be
    connected appropriately. In particular, the clock_error_pb_line() from the
    PulseBlaster must be connected to the PulseBlaster input of the circuit.

    Returns:
        duration (float): (seconds) Time needed to do this subsequence. After
            this amount of time it is ok to start the rest of the subsequences
            that you'd like to run.
    """
    t = 0
    # Place time marker for runviewer.
    lab.add_time_marker(t, "Clock Correction")
    # Set initial output states.
    clock_error_pci_line.go_high(t)
    clock_error_pb_line.go_low(t)
    t += 2e-6

    # Set edge that may be missed.
    clock_error_pci_line.go_low(t)
    t += 2e-6

    # Set edge that causes the additional clock pulse if the previous one was
    # missed.
    clock_error_pb_line.go_high(t)
    t += 2e-6

    # Set pulseblaster channel low so it's ready for the next shot.
    clock_error_pb_line.go_low(t)
    t += 2e-6

    # Return how long this subsequence took.
    duration = t
    return duration


def fix_clock_error():
    """Subsequence for fixing occasional clocking error with the digital card.

    This subsequence is designed to be run in every sequence before anything
    else happens. So call it and do not do anything else until it has
    completed.

    This subsequence is designed to fix a bug with clocking our PCI-DIO-32HS
    digital output card. In order for it to work, the "Rb Lab Digital PCI Card
    Clock Error Corrector" circuit must be installed. See that circuit's wiki
    page and/or our Labscript wiki page for more information.

    Furthermore, some signal lines must be run appropriately for the circuit to
    work. See the docstring for _fix_clock_error_pulseblaster() or
    _fix_clock_error_pineblaster(), depending on whether the machine is set up
    to use a PulseBlaster or a PineBlaster as the master pseudoclock.

    When switching between using a PulseBlaster and using a PineBlaster, edit
    this function to call the appropriate private method for the device.

    Returns:
        duration (float): (seconds) Time needed to do this subsequence. After
            this amount of time it is ok to start the rest of the subsequences
            that you'd like to run.
    """
    # Call the appropriate error correction subsequence depending on whether the
    # machine is set up with a PulseBlaster or with a PineBlaster.
    duration = _fix_clock_error_pulseblaster()
    # duration = _fix_clock_error_pineblaster() # see older files to find this function

    return duration


def load_MOT(start_time, duration, MOT_slave_shutter_delay, enable_mot=True, reset = False, marker_name="MOT"):
    """Configure outputs to turn on the MOT.

    The shutters are configured to be open at start_time, so they would
    nominally be triggered to open before start_time if they have a delay
    specified for them in the connectiontable. Labscript will internally adjust
    the opening trigger to be no earlier than t=0, at the cost that the shutter
    opening may be slightly delayed.

    Args:
        start_time (float): (seconds) Time in the sequence at which to start
            loading the MOT.
        duration (float): (seconds) How long to wait before moving on to the next thing.
        MOT_slave_shutter_delay (floart): (seconds) Compensates for shutter delay 
        enable_mot (bool): (Default=True) Set whether or not atoms are actually
            loaded into the MOT. If set to False, the MOT slave shutters will
            be closed to prevent loading atoms. This can be useful for turning
            the MOT off between shots so that the MOT loading time is purely
            hardware controlled with the sequence, rather than including the
            random amount of time between shots. All of the magnetic fields,
            laser frequencies, AOM settings, etc. will be set to run the MOT, so
            it can be quickly started simply by opening the shutters, likely by
            calling this function again but with enable_mot=True.
        marker_name (str): (Default="MOT") The name of the marker used in
            runviewer for this subsequence.
            
    Returns:
        duration (float): (seconds) How long to wait before going on to the next stage of the sequence.
    """
    # Place time marker for runviewer.
    lab.add_time_marker(start_time, marker_name)

    # Set mangetic fields.
    x_coil.constant(start_time, mot_x_coil)
    y_coil.constant(start_time, mot_y_coil)
    z_coil.constant(start_time, mot_z_coil)
    mot_coil_digital.enable(start_time)
    # If resetting the outputs to their MOT values, let reset_mot() take care of
    # the MOT coil analog control.
    if not reset:
        mot_coil.constant(start_time, mot_mot_coil)

    # Configure MOT and Repumper Beams.
    mot_master_frequency.constant(start_time, mot_mot_master_freq)
    mot_xyz_power.constant(start_time, mot_mot_xyz_power)
    repumper_frequency.constant(start_time, mot_repumper_frequency)
    repumper_power.constant(start_time, mot_repumper_power)

    # Only open shutters if MOT is enabled.
    if enable_mot:
        mot_x_shutter.open(start_time-MOT_slave_shutter_delay)
        mot_yz_shutter.open(start_time-MOT_slave_shutter_delay)
        repumper_shutter.open(start_time)
    else:
        mot_x_shutter.close(start_time-MOT_slave_shutter_delay)
        mot_yz_shutter.close(start_time-MOT_slave_shutter_delay)
        repumper_shutter.close(start_time)


    # # Make sure other beams are off. Keep AOMs warm, instead use shutters to
    # # block the light.
    # # Absorption imaging beam.
    # absorption_beam_power.constant(start_time, absorption_beam_warm_value)
    # absorption_beam_shutter.close(start_time)
    return duration

# def compress_mot(start_time):
#     """Zak's Compress then extinguish the MOT.

#     This section of the sequence includes many variables, which were optimized
#     using M-LOOP. We tried a few different subsequences and then settled on this
#     one, which was originally developed in LatticeLoadingOptimization.py and
#     then was move here.

#     There are a few edges that occur slightly after the nominal duration of this
#     subsequence is over. In particular the repumper and mot_xyz aoms are
#     turned back on to keep them warm once their shutters are closed.

#     Args:
#         start_time (float): (seconds) Time in the sequence at which to start
#             ramping from the MOT to the cMOT.

#     Returns:
#         duration (float): (seconds) Time needed to do the ramp.
#     """
#     # Place time marker for runviewer
#     lab.add_time_marker(start_time, "cMOT")

#     # Collect globals related to the MOT master frequency.
#     cmot_master_freq_list = indexed_globals_values('cmot_master_freq')
#     cmot_master_freq_duration_frac_list = indexed_globals_values(
#         'cmot_master_freq_duration_frac'
#     )

#     # Collect globals related to the repumper frequency.
#     cmot_repump_freq_list = indexed_globals_values('cmot_repump_freq')
#     cmot_repump_freq_duration_frac_list = indexed_globals_values(
#         'cmot_repump_freq_duration_frac'
#     )

#     # Collect globals related to the repumper power.
#     cmot_repump_power_list = indexed_globals_values('cmot_repump_power')
#     cmot_repump_power_duration_frac_list = indexed_globals_values(
#         'cmot_repump_power_duration_frac'
#     )

#     # Collect globals related to the MOT xyz power.
#     cmot_xyz_power_list = indexed_globals_values('cmot_xyz_power')
#     cmot_xyz_power_duration_frac_list = indexed_globals_values(
#         'cmot_xyz_power_duration_frac'
#     )

#     # Figure out at what time the cMOT should be turned off
#     cmot_off_time = start_time + cmot_total_duration

#     # Make waveform for MOT master's frequency.
#     # Calculate durations of MOT master frequency steps.
#     cmot_master_freq_duration_list = duration_fractions_to_durations(
#         cmot_master_freq_duration_frac_list,
#         cmot_total_duration,
#     )
#     # Set outputs for MOT master frequency.
#     piecewise_linear_ramp(
#         mot_master_frequency,
#         start_time,
#         cmot_master_freq_duration_list,
#         cmot_master_freq_list,
#     )
#     # Set the MOT master frequency far off resonance when done.
#     mot_master_frequency.constant(cmot_off_time, -5.4)

#     # Make waveform for repumper's frequency.
#     # Calculate durations of repumper frequency steps.
#     cmot_repump_freq_duration_list = duration_fractions_to_durations(
#         cmot_repump_freq_duration_frac_list,
#         cmot_total_duration,
#     )
#     # Set outputs for repumper frequency.
#     piecewise_linear_ramp(
#         repumper_frequency,
#         start_time,
#         cmot_repump_freq_duration_list,
#         cmot_repump_freq_list,
#     )
#     # Set the repumper frequency far off resonance when done.
#     repumper_frequency.constant(cmot_off_time, 10.)

#     # Make waveform for repumper's power.
#     # Calculate durations of repumper power steps.
#     cmot_repump_power_duration_list = duration_fractions_to_durations(
#         cmot_repump_power_duration_frac_list,
#         cmot_total_duration,
#     )
#     # Set outputs for repumper power.
#     piecewise_linear_ramp(
#         repumper_power,
#         start_time,
#         cmot_repump_power_duration_list,
#         cmot_repump_power_list,
#     )
#     # Turn off the repumper when done.
#     close_shuttered_beam(
#         cmot_off_time,
#         repumper_warm_value,
#         repumper_shutter,
#         repumper_power,
#     )

#     # Make waveform for MOT xyz' power.
#     # Calculate durations of MOT xyz power steps.
#     cmot_xyz_power_duration_list = duration_fractions_to_durations(
#         cmot_xyz_power_duration_frac_list,
#         cmot_total_duration,
#     )
#     # Set outputs for MOT xyz power.
#     piecewise_linear_ramp(
#         mot_xyz_power,
#         start_time,
#         cmot_xyz_power_duration_list,
#         cmot_xyz_power_list,
#     )
#     # Turn off the MOT xyz when done.
#     close_shuttered_beam(
#         cmot_off_time,
#         mot_xyz_warm_value,
#         mot_xyz_shutter,
#         mot_xyz_power,
#     )

#     # Set up coil ramps.
#     coil_ramp_duration = cmot_coil_ramp_duration
#     ramp_from_previous_value(
#         mot_coil,
#         start_time,
#         coil_ramp_duration,
#         cmot_mot_coil,
#     )
#     ramp_from_previous_value(
#         x_coil,
#         start_time,
#         coil_ramp_duration,
#         cmot_x_coil,
#     )
#     ramp_from_previous_value(
#         y_coil,
#         start_time,
#         coil_ramp_duration,
#         cmot_y_coil,
#     )
#     ramp_from_previous_value(
#         z_coil,
#         start_time,
#         coil_ramp_duration,
#         cmot_z_coil,
#     )

#     # Figure out how long we need for all of those outputs
#     duration = max(cmot_total_duration, coil_ramp_duration)
#     return duration

def compress_mot(start_time):
    """ Compress the MOT.

    There are a few edges that occur slightly after the nominal duration of this
    subsequence is over. In particular the repumper and mot_xyz aoms are
    turned back on to keep them warm once their shutters are closed.

    Args:
        start_time (float): (seconds) Time in the sequence at which to start
            ramping from the MOT to the cMOT.

    Returns:
        duration (float): (seconds) Time needed to do the ramp.
    """
    # Place time marker for runviewer
    lab.add_time_marker(start_time, "cMOT")

    # Set mangetic fields.
    x_coil.constant(start_time, cmot_x_coil)
    y_coil.constant(start_time, cmot_y_coil)
    z_coil.constant(start_time, cmot_z_coil)
    mot_coil.constant(start_time, cmot_mot_coil)


    # Figure out how long we need for all of those outputs
    duration = max(cmot_total_duration, coil_ramp_duration)
    return duration

def reset_mot(start_time, marker_name="Reset MOT"):
    """Set the outputs to their MOT values to prepare for the next shot.

    This subsequence should be run at the end of a shot, right after
    `aborption_image()`. It sets the outputs of all of the channels to their MOT
    values so that everything is ready for the next shot.

    If the global `enable_mot_between_shots` is `True` then this will turn on
    the MOT and start loading atoms. If it is `False` then all of the outputs
    will go to their MOT values, but the MOT and repumper shutters will remain
    closed to avoid loading atoms until the next shot starts (which will open
    those shutters). Having the MOT on between shots can increase the loaded
    atom number at the cost of making it vary more due to the varied time
    between shots, particularly when the machine sits idle before a shot.

    Getting the MOT coil to turn back on in a reasonable amount of time (<<1
    second) and in a reliable/repeatable way takes some trickery. See the wiki
    page for the MOT coil digital switching circuit for detailed information.
    The trick used in this subsequence is to set the MOT coil current control to
    its cMOT value for a while to get it to turn on faster, then set it the
    actual desired normal MOT value. To get this done sooner, it starts turning
    the coil on just after the beam image is taken during absorption imaging.
    Note that the timinngs for this are calculated assuming that this
    subsequence is run right after `absorption_image()`, hence the note
    instructing users to call this subsequence right after that one.

    Args:
        start_time (float): (seconds) Time in the sequence at which to start
            resetting the MOT outputs. Note that the MOT coil will actually be
            instructed to start turning on sooner than this though; see the
            notes above.
        marker_name (str): (Default="Reset MOT") The name of the marker to use
            in runviewer for this subsequence.

    Returns:
        duration (float): (seconds) Time needed to reset the outputs to their
            MOT values.
    """
    # Set some durations.
    # How long to have the coil at its high value.
    COIL_HIGH_DURATION = 150e-3  # 150 ms.
    # How long to wait after the beam image before turning on the MOT coil.
    post_image_delay = 1e-3  # 1 ms.

    # Determine some timings. It is assumed here that this subsequence is called
    # right after absorption_image().
    beam_image_time = start_time - 0.2
    first_jump_time = beam_image_time + post_image_delay
    second_jump_time = first_jump_time + COIL_HIGH_DURATION
    reset_mot_duration = second_jump_time - start_time
    # Ensure a positive value for reset_mot_duration.
    reset_mot_duration = max(reset_mot_duration, 1e-3)

    # Jump to MOT coil to cMOT value for a while.
    mot_coil_digital.enable(first_jump_time)
    jump_from_previous_value(
        mot_coil,
        first_jump_time,
        cmot_mot_coil,
    )
    # Now set the MOT coil to the its normal MOT value.
    jump_from_previous_value(
        mot_coil,
        second_jump_time,
        mot_mot_coil,
    )

    # Call load_mot() with the appropriate arguments, which takes care of the
    # other outputs.
    duration = load_MOT(
        start_time,
        reset_mot_duration,
        MOT_xyz_shutter_delay,
        enable_mot=enable_mot_between_shots,
        reset=True,
        marker_name=marker_name,
    )

    # Ensure that the last edge isn't cut off by the end of the sequence by
    # adding one more millisecond.
    duration = duration + 1e-3

    return duration







def hold(start_time, duration, marker_name="Hold"):
    """Do nothing for the specified amount of time.

    This subsequence simply places a marker for runviewer and doesn't change any
    outputs on any channels. Note that it does not perform any checks to ensure
    that code elsewhere hasn't added any instructions during this hold period.

    Args:
        start_time (float): (seconds) The time at which to start holding.
        duration (float): (seconds) The duration of time for which to hold.
        marker_name (str): (Default="Hold") The name of the marker used in
            runviewer for this subsequence.

    Returns:
        duration (float): (seconds) The duration of the hold period.
    """
    # Place time marker for runviewer.
    lab.add_time_marker(start_time, marker_name)
    return duration




def return_to_default_values(start_time, duration = 1e-3, marker_name="Return to default values"):
    """sets all analog output channels to 0, and sets all digital output channels to 0.
    
    Args:
        start_time (float): (seconds) The time at which to turn off all values.
        duration (float): (seconds) How long to wait before going on to the next thing. 
        marker_name (str): (Default="Return to default values") The name of the marker used in
            runviewer for this subsequence.
    """
    time = start_time + duration/2.0
    # Place time marker for runviewer.
    lab.add_time_marker(start_time, marker_name)
    
    x_coil.constant(time, mot_x_coil)
    y_coil.constant(time, mot_y_coil)
    z_coil.constant(time, mot_z_coil)
    mot_coil_digital.enable(time)
    mot_coil.constant(time, mot_mot_coil)

    # Configure MOT and Repumper Beams.
    mot_master_frequency.constant(start_time, mot_mot_master_freq)
    mot_xyz_power.constant(start_time, mot_mot_xyz_power)
    repumper_frequency.constant(start_time, mot_repumper_frequency)
    repumper_power.constant(start_time, mot_repumper_power)

    mot_xyz_shutter.open(time)
    repumper_shutter.open(time)
    
    # # Turn off all analog output values
    # mot_coil.constant(time, mot_mot_coil)
    # x_coil.constant(time, mot_x_coil)
    # y_coil.constant(time, mot_y_coil)
    # z_coil.constant(time, mot_z_coil)
    # mot_master_frequency.constant(time, mot_)
    # mot_xyz_power.constant(time, 3.0)
    # repumper_frequency.constant(time, -4.4)
    # repumper_power.constant(time, 3.05)
    # absorption_beam_power.constant(time, 3.05)
    # dummy_dev6.constant(time, 0)
    # dummy_dev2_ao2.constant(time, 1)
    # dummy_dev2_ao7.constant(time, 0)  
    
    # # Close off all shutters
    # mot_xyz_shutter.close(time)
    # repumper_shutter.close(time)
    
    
    return duration







def single_image(image_time, label):
    """Function that takes a single image.

    If you want to take an absorption image, call absorption_image() instead.

    Args:
        image_time (float): (seconds) The absolute time in the sequence at which
            the image is taken. This corresponds to the center of the absorption
            imaging pulse, which has a nonzero duration.
        frame_type (str): The name to assign to this image to distinguish its
            purpose.
        
    Returns:
        duration (float): (seconds) Time needed to take the image. This is
            counted from image_time to the final edge. Note that many of the
            edges in here occur before image_time, but we'll consider them as
            pretriggers to make keeping track of time easier.
    """
    
    # Figure out pulse timings
    image_start_time = image_time - 0.5 * imaging_pulse_duration
    image_end_time = image_start_time + imaging_pulse_duration
    camera_trigger_time = image_start_time - 30e-6

    # Trigger camera whether or not light is turned on
    # TODO: Control exposure duration with digital output rather than
    # setting it with DelayExposureTime in connectiontable?
    camera.expose(camera_trigger_time, label, "frame")

    # Calculate duration
    # TODO: Make sure duration is calculated correctly if we shorten the trigger
    # pulse used for the camera.
    camera_falling_edge_time = camera_trigger_time + camera.trigger_duration
    duration = camera_falling_edge_time - image_time
    return duration



def _single_absorption_image(image_time, frame_type, image_with_light=True):
    """Helper function that takes a single absorption image.

    Do NOT call this directly. Call absorption_image() instead.

    Args:
        image_time (float): (seconds) The absolute time in the sequence at which
            the image is taken. This corresponds to the center of the absorption
            imaging pulse, which has a nonzero duration.
        frame_type (str): The name to assign to this image to distinguish its
            purpose.
        image_with_light (bool, optional): (Default=True) Whether or not to turn
            on the absorption and repumper beams during imaging. Set to False to
            take a no-light backgroung image. Note that the repumper will only
            be turned on if the global imaging_repumper_enabled is True as well.

    Returns:
        duration (float): (seconds) Time needed to take the image. This is
            counted from image_time to the final edge. Note that many of the
            edges in here occur before image_time, but we'll consider them as
            pretriggers to make keeping track of time easier.
    """
    #possible durations, will be calculated later
    duration1 = 0
    duration2 = 0
    duration3 = 0
    
    
    if image_with_light:
        # Tune beams to resonance for imaging
        mot_master_frequency.constant(
            image_time - 0.2e-3,
            imaging_mot_master_frequency
        )
        
        if imaging_repumper_enabled:
            repumper_frequency.constant(
                image_time - 1.1e-3,
                imaging_repumper_frequency
            )

    # Figure out pulse timings
    absorption_start_time = image_time - 0.5 * imaging_pulse_duration
    absorption_end_time = absorption_start_time + imaging_pulse_duration
    pre_image_repump_duration = 30e-6  # How long to repump before absorption
    repump_start_time = absorption_start_time - pre_image_repump_duration
    camera_trigger_time = absorption_start_time - 30e-6

    # Trigger camera whether or not light is turned on
    # TODO: Control exposure duration with digital output rather than
    # setting it with DelayExposureTime in connectiontable?
    camera.expose(camera_trigger_time, "absorption", frame_type)

    if image_with_light:
        # Fire absorption beam.
        open_shuttered_beam(
            absorption_start_time,
            imaging_mot_master_power,
            absorption_beam_shutter,
            absorption_beam_power
        )
        AOM_on_time = close_shuttered_beam(
            absorption_end_time,
            absorption_beam_warm_value,
            absorption_beam_shutter,
            absorption_beam_power
        )
        duration2 = AOM_on_time-image_time

        # Fire repumper if instructed to do so.
        if imaging_repumper_enabled:
            open_shuttered_beam(
                repump_start_time,
                imaging_repumper_power,
                repumper_shutter,
                repumper_power
            )
            AOM_on_time = close_shuttered_beam(
                absorption_end_time,
                repumper_warm_value,
                repumper_shutter,
                repumper_power
            )
            duration3 = AOM_on_time-image_time

        # Tune beams away from resonance between images.
        mot_master_frequency.constant(
            absorption_end_time + 0.12e-3,
            -5.4
        )
        if imaging_repumper_enabled:
            repumper_frequency.constant(
                absorption_end_time + 1e-3,
                10.
            )
    
    # Calculate duration
    # TODO: Make sure duration is calculated correctly if we shorten the trigger
    # pulse used for the camera.
    camera_falling_edge_time = camera_trigger_time + camera.trigger_duration
    duration1 = camera_falling_edge_time - image_time
    duration = max(duration1,duration2,duration3)
    return duration



def absorption_image(start_time, minimum_initial_hold=1e-3):
    """Take a series of images to do absorption imaging.

    The time of flight is set by the global time_of_flight. This can be
    overriden if the global in_situ_image is set to True, in which case the
    atoms are imaged right after releasing the trap.

    The time of flight is defined as from the moment of release to the center of
    the 150 us imaging pulse.

    Atoms are held in the trap for at least minimum_initial_hold, then are
    released and imaged time_of_flight later. The initial holding time will be
    longer than minimum_initial_hold if necessary to allow time for the magnetic
    field to rotate for imaging. The time needed to do this is set as the
    variable b_field_settle_period in this function, which is set to 1 ms as of
    this writing. Although this probably doesn't matter, we set
    minimum_initial_hold to 1 ms by default so that the hold time does not
    change if the time_of_flight is varied over small values.

    Args:
        start_time (float): (seconds) Time in the sequence at which to start the
            absorption imaging process. The actual image taking occurs slightly
            after this time.
        minimum_initial_hold (float, optional): (Default=1e-3) (seconds) Minimum
            amount of time to hold the atoms in the trap before releasing for
            time of flight.

    Returns:
        duration (float): (seconds) The time needed to perform the imaging.
    """
    # Place time marker for runviewer.
    lab.add_time_marker(start_time, "Imaging")

    # Set constants.
    b_field_settle_period = 1e-3

    # Set local_time_of_flight to account for global in_situ_image setting.
    if in_situ_image:
        local_time_of_flight = 0.5 * imaging_pulse_duration
    else:
        local_time_of_flight = time_of_flight

    # Make sure we have enough time to rotate B-field and do time of flight.
    # Calculate minimum delay from start_time required for each of those, then
    # take the largest.
    min_b_field_settle_delay = b_field_settle_period - minimum_initial_hold
    min_time_of_flight_delay = minimum_initial_hold + local_time_of_flight
    if imaging_adiabatic_release:
        min_time_of_flight_delay += imaging_adiabatic_ramp_duration
    min_image_delay = max(min_b_field_settle_delay, min_time_of_flight_delay)
    first_image_time = start_time + min_image_delay
    

    # Release for time of flight.
    release_time = first_image_time - local_time_of_flight
    
    # Rotate magnetic field for imaging. Call jump_from_previous_value() which
    # uses constant() to make the coils jump to their new values as fast as they
    # can.
    b_field_rotation_start_time = start_time  # Start rotation ASAP.
    x_coil.constant(b_field_rotation_start_time, imaging_x_coil)
    y_coil.constant(b_field_rotation_start_time, imaging_y_coil)
    z_coil.constant(b_field_rotation_start_time, imaging_z_coil)

    # Take first absorption image, this one with atoms.
    print("First image time is", first_image_time)
    _single_absorption_image(first_image_time, 'atoms')

    # Take a second identical image after the atoms have fallen away.
    second_image_time = first_image_time + imaging_inter_image_delay
    print("Second image time is", second_image_time)
    _single_absorption_image(second_image_time, 'beam')
    

    # Take a third image with no light.
    third_image_time = second_image_time + imaging_inter_image_delay
    print("Third image time is", third_image_time)
    image_duration = _single_absorption_image(
        third_image_time, 'background', image_with_light=False)
    
    # TODO: Make sure duration here is still calculated correctly.
    last_edge_time = third_image_time + image_duration
    duration = last_edge_time - start_time
    return duration




def MOT_STAGE(start_time, duration, marker_name="MOT"):
    """Configure outputs for MOT. Designed to be handed off to MOLASSES_STAGE()

    The shutters are too slow, so we won't rely on them in this sequence.

    Args:
        start_time (float): (seconds) Time in the sequence at which to start
            loading the MOT.
        duration (float): (seconds) How long to wait before moving on to the next thing. 
        marker_name (str): (Default="MOT") The name of the marker used in
            runviewer for this subsequence.
            
    Returns:
        duration (float): (seconds) How long to wait before going on to the next stage of the sequence.
    """
    # Place time marker for runviewer.
    lab.add_time_marker(start_time, marker_name)

    # Set magnetic fields.
    x_coil.constant(start_time, mot_x_coil)
    y_coil.constant(start_time, mot_y_coil)
    z_coil.constant(start_time, mot_z_coil)
    mot_coil_digital.enable(start_time)
    mot_coil.constant(start_time, mot_mot_coil)

    # Configure MOT and Repumper Beams.
    mot_master_frequency.constant(start_time, mot_mot_master_freq)
    mot_xyz_power.constant(start_time, mot_mot_xyz_power)
    repumper_frequency.constant(start_time, mot_repumper_frequency)
    repumper_power.constant(start_time, mot_repumper_power)
       
    return duration


def MOLASSES_STAGE(start_time, duration, marker_name="MOLASSES"):
    """Configure outputs for MOLASSES. Designed to be preceeded by MOT_STAGE() and
    to hand off to MEASURE_STAGE().

    The shutters are too slow, so we won't rely on them in this sequence.

    Args:
        start_time (float): (seconds) Time in the sequence at which to start
            loading the MOT.
        duration (float): (seconds) How long to wait before moving on to the next thing. 
        marker_name (str): (Default="MOLASSES") The name of the marker used in
            runviewer for this subsequence.
            
    Returns:
        duration (float): (seconds) How long to wait before going on to the next stage of the sequence.
    """
    # Place time marker for runviewer.
    lab.add_time_marker(start_time, marker_name)

    # Set magnetic fields.
    x_coil.constant(start_time, mot_x_coil)
    y_coil.constant(start_time, mot_y_coil)
    z_coil.constant(start_time, mot_z_coil)
    mot_coil.ramp(start_time, duration/2.0, mot_mot_coil, 0, default_ramp_samplerate)
    mot_coil_digital.disable(start_time+duration/2.0)

    # Configure MOT and Repumper Beams for molasses (could involve more ramps).
    mot_master_frequency.constant(start_time, imaging_mot_master_frequency)
    mot_xyz_power.ramp(start_time,  duration/2.0, mot_mot_xyz_power, 0, default_ramp_samplerate)
    repumper_frequency.constant(start_time, mot_repumper_frequency)
    repumper_power.constant(start_time, mot_repumper_power)
    
    # Turn off MOT and Repumper beams after molasses is done. 
    mot_xyz_power.constant(start_time+duration - 10e-6,0)
    repumper_power.constant(start_time+duration - 10e-6, 0)
        
    return duration


def MEASURE_STAGE(start_time, duration, marker_name="MEASURE"):
    """Configure outputs for MEASUREMENTS. Designed to be preceeded by MOT_STAGE() and
    MOLASSES_STAGE(). Meant to be used in a loop where it hands off to MOT_STAGE() again 
    starting a new cycle.

    The shutters are too slow, so we won't rely on them in this sequence.

    Args:
        start_time (float): (seconds) Time in the sequence at which to start
            the measurement.
        marker_name (str): (Default="MEASURE") The name of the marker used in
            runviewer for this subsequence.
            
    Returns:
        duration (float): (seconds) How long to wait before going on to the next stage of the sequence.
    """
    # Place time marker for runviewer.
    lab.add_time_marker(start_time, marker_name)

    # Set magnetic fields.
    x_coil.constant(start_time, mot_x_coil)
    y_coil.constant(start_time, mot_y_coil)
    z_coil.constant(start_time, mot_z_coil)
    
    dummy_dev2_ao2.constant(start_time, 0)
    dummy_dev2_ao2.constant(start_time+duration/2.0, 1)
    dummy_dev2_ao2.constant(start_time+duration, 0)

        
    return duration