"""A library of helper functions and the like used for making sequences.

This module is intended to store code that helps define sequences, but isn't
quite a subsequence on its own. Shared code that makes subsequences should be
stored in standard_subsequences.py.

For example, the code to load the MOT is placed in standard subsequences.py. On
the other hand, the helper function open_shuttered_beam() is placed here. That
function doesn't define a subsequence, rather it's just a helper function that
automatically turns off a beam's AOM, opens its shutter, then turns on the AOM at
the desired time. Since that isn't a full subsequence unto itself, it is
included here.

A general rule of thumb may be that functions which take an output channel as an
argument (so that it could be used on different outputs) belong here, though
there may be good expections to that rule.
"""
# Adjust pylint to ignore undefined variables since it can't distinguish
# them from globals set up by labscript or defined in the connectiontable
# pylint: disable=undefined-variable

import builtins
import re

import numpy as np

import labscript_utils.h5_lock
import h5py

_previous_values = {}

def _validate_beam_timing(time, headroom, shutter_delay, aom_guard_time):
    """Reject invalid timing values before adding output instructions."""
    for name, value in (
            ("time", time), ("headroom", headroom),
            ("shutter_delay", shutter_delay),
            ("aom_guard_time", aom_guard_time)):
        if not np.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative.")


def open_shuttered_beam(
        time, aom_power_value, shutter_object,
        aom_power_object, aom_digital_object=None,
        headroom=1e-3, aom_power_off_value=0.,
        *, shutter_open_delay=4e-3, aom_guard_time=20e-6,
        **kwargs):
    """Open an IMAQ beam using its digital shutter and analog AOM.

    Pass mot_shutter_do/mot_aom_analog or
    repumper_shutter_do/repumper_aom_analog, created by ConnectionTable().
    The shutter command is held HIGH to open and LOW to close. The AOM
    analog output uses 0 V for OFF and 0.7 V for fully ON; aom_power_value
    specifies the desired ON voltage. An optional digital AOM gate is also
    supported, but is not required by the current setup.

    All times are in seconds. Before the requested time, set the AOM OFF,
    wait aom_guard_time (default 20 us), then command the shutter
    OPEN. Allow shutter_open_delay (approximately 4 ms) plus headroom
    before commanding the AOM ON at time. The existing default headroom
    is an additional 1 ms margin; it can be overridden after calibration.
    The 20 us AOM guard accommodates the NI analog card clock timing;
    it is longer than the approximately 1 us physical AOM response.

    time is the analog command time, not a precisely compensated optical
    edge: the beam responds approximately 1 us later. Set the initial
    shutter/AOM states separately, and leave enough time at the beginning
    of the shot for these preparation commands. This helper returns None.
    Extra keyword arguments, such as units, go to AnalogOut.constant().
    """
    _validate_beam_timing(
        time, headroom, shutter_open_delay, aom_guard_time)
    shutter_open_time = time - shutter_open_delay - headroom
    aom_off_time = shutter_open_time - aom_guard_time
    if aom_off_time < 0:
        raise ValueError(
            "Beam opening preparation would occur before t=0. "
            "Increase time or reduce the calibrated delays/headroom.")

    aom_power_object.constant(aom_off_time, aom_power_off_value, **kwargs)
    if aom_digital_object is not None:
        aom_digital_object.disable(aom_off_time)

    shutter_object.go_high(shutter_open_time)

    aom_power_object.constant(time, aom_power_value, **kwargs)
    if aom_digital_object is not None:
        aom_digital_object.enable(time)


def close_shuttered_beam(
        time, aom_power_warm_value, shutter_object,
        aom_power_object, aom_digital_object=None,
        headroom=1e-3, aom_power_off_value=0.,
        *, shutter_close_delay=4e-3, aom_guard_time=20e-6,
        **kwargs):
    """Close an IMAQ beam, then restore its AOM behind the closed shutter.

    shutter_object is a DigitalOut such as mot_shutter_do or
    repumper_shutter_do. aom_power_object is the corresponding AnalogOut.
    LOW commands the shutter CLOSED. Set the AOM analog output to 0 V at
    time, then wait aom_guard_time (default 20 us) before commanding
    the shutter CLOSED. After shutter_close_delay (approximately 4 ms)
    plus headroom, restore aom_power_warm_value. Use 0.7 V for fully ON
    behind the closed shutter, or 0 V to leave the AOM OFF.

    All times are in seconds. time is the analog OFF command time; the
    physical beam responds approximately 1 us later. headroom is an extra
    margin, defaulting to 1 ms. The 20 us guard accommodates NI analog
    clock timing despite the approximately 1 us physical AOM response.
    Extra keyword arguments go to constant().

    Return the absolute time of the final analog command, not a duration.
    Keep the shot running through this time and avoid overlapping a new
    opening preparation with this closing/warm-up operation.
    """
    _validate_beam_timing(
        time, headroom, shutter_close_delay, aom_guard_time)
    shutter_close_time = time + aom_guard_time
    aom_on_time = shutter_close_time + shutter_close_delay + headroom

    aom_power_object.constant(time, aom_power_off_value, **kwargs)
    if aom_digital_object is not None:
        aom_digital_object.disable(time)

    shutter_object.go_low(shutter_close_time)

    aom_power_object.constant(aom_on_time, aom_power_warm_value, **kwargs)
    if aom_digital_object is not None:
        aom_digital_object.enable(aom_on_time)

    return aom_on_time


def set_previous_value(output, value):
    """Record the last output value of a channel.

    Use this method to update the record of what value was last output on a
    channel. This is necessary in order to be able to use the
    ramp_from_previous_value() function, as it has to know what value was last
    output. Labscript doesn't have built-in functionality for that as of this
    writing, so we must keep track of the last output manually. This can be used
    for any kind of output, but is primarily helpful for analog outputs.

    It is not necessary to call this function directly when using
    ramp_from_previous_value(), jump_from_previous_value() or other similar
    functions defined in this module because those functions call this function
    automatically. However, if the output is changed without using one of those
    functions, then make sure to call this method in order to keep track of the
    output.

    Note that the way that this keeping track of previous values works assumes
    that the outputs ser set in the labscript in the actual order that they will
    be output. In other words ensure that the code specifying a ramp at t=1 is
    defined in the labscript before a ramp that occurs at t=2 to ensure that
    the previous value actually corresponds to the previous ramp.

    Args:
        output (labscript.AnalogOut or similar): The object representing the
            output channel. This should be something from the connection table.
        value (any, usually float): The value that the channel was last set to.
    """
    # Labscript creates new instances of the output classes each time a shot is
    # compiled, but _previous_values still contains references to old instances
    # from past shot compilations. Because they are in the dictionary, they
    # won't be garbage collected, which leads to a memory leak because the old
    # output class instances (and anything they reference, which is a lot) never
    # get deleted. To work around that, this function makes sure to delete old
    # output class instances whenver a new one for the same physical output is
    # used. The names of the outputs are unique, so if a new output instance has
    # the same name attribute as one already in the dictionary, then the one in
    # the dictionary is old and should be deleted. Note that just keying by
    # output.name rather than by output itself isn't ideal because then if
    # get_previous_value() were called before set_previous_value() it would then
    # just return the last entry in _previous_values from the previous shot,
    # which probably isn't what we want.
    if output not in _previous_values:
        # This output instance isn't in the _previous_values dict yet; see if
        # there's an old output instance for the same output (which should have
        # the same .name attribute) and if so delete it. Use .copy() to avoid
        # editing the original dictionary while looping over it.
        for existing_output in _previous_values.copy().keys():
            if existing_output.name == output.name:
                # Found a match. Delete the entry for the old instance.
                del _previous_values[existing_output]

    # Finally actually store the value.
    _previous_values[output] = value

def jump_from_previous_value(output, time, value):
    """Change an output to a new value without ramping.

    This function is like ramp_from_previous_value(), except it suddenly jumps
    outputs to a new value instead of ramping them. It simply calls the output's
    constant() method and then calls set_previous_value() to ensure that we keep
    track of the output's last value.

    It is only necessay to use this function when using outputs for which
    ramp_from_previous_value() is used at other points in the sequence. For
    channels that don't use that function, it is fine to simply call the
    output's constant() method directly.

    Args:
        output (labscript.AnalogOut or similar): The object representing the
            output channel. This should be something from the connection table.
        time (float): (seconds) Time in the sequence at which to change the
            output.
        value (any, usually float): The value to change the output to.
    """
    # Set the output to the instructed value.
    output.constant(time, value)

    # Update previous value.
    set_previous_value(output, value)

def indexed_globals_values(global_name):
    """Get a list of values of globals with the same name appended by an index.

    This method looks through the globals for ones the start with global_name
    and end with an underscore followed by an index. For example, if global_name
    is set to 'cmot_master_freq' and there are globals named
    'cmot_master_freq_0' and 'cmot_master_freq_1', then their values will be
    included in the returned list. The returned list will be sorted such that
    the values of the globals with the lowest indices appear first. So in this
    example, the value of 'cmot_master_freq_0' would be first in the list,
    followed by the value of 'cmot_master_freq_1'. Note that the values (not the
    names of the globals) are returned.

    The global variable names must start with global_name followed immediately
    by an underscore then an index, which consists of one or more of the
    characters 0 through 9. If they do not follow this format, then this method
    will not return their values.

    Note: As far as I (Zak) can tell, there is no way to distinguish the globals
    injected by runmanager apart from the other globals, such as the ones built
    into python (run "import builtins; dir(builtins)" for a list). In practice
    this shouldn't be an issue though as the other globals presumably won't
    follow the strict format required for this function to include their values
    in the output.

    This function is particuarly helpful when using the M-LOOP Lyse integration.
    It lets you create a bunch of globals to be optimized in runmanager, then
    automatically bring them all into one list in the sequence's labscript.

    Args:
        global_name (str): The name of the globals (without the underscored or
            index at the end) whose values should be included

    Returns:
        values_list (list): The values of all of the globals that matched
            global_name, ordered by their index.
    """
    # Unfortunately the below also grabs a lot of actual built-in python things,
    # not just the runmanager globals. I haven't found a good way to just get
    # the list of globals that were injected by runmanager.
    global_names = dir(builtins)

    # We'll use the regular expression "match" function, which ensures that the
    # pattern is matched at the beginning of the string (so no "^" is
    # necessary).
    # The \d+ matches one or more digits (characters 0 to 9). Putting that
    # inside of (?P<index>\d+) puts them together into a group called "index".
    # The (?P<>) part is special python syntax for naming the group.
    # The "$" means the match must end at the end of the string.
    regex = re.compile(global_name + r'_(?P<index>\d+)$')

    # Find the globals that match the regular expression.
    match_list = []
    for name in global_names:
        match = regex.match(name)
        if match:
            index = int(match.group('index'))
            match_list.append((index, name))

    # Ensure that the globals are ordered by their index
    match_list.sort()

    # Get a list of the values of the globals
    values_list = [getattr(builtins, entry[1]) for entry in match_list]
    return values_list
