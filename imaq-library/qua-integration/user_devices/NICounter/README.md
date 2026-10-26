# NI Counting Card for NI PCI 6602

This code is intended to count the number of rising edges the 6602 counting card sees for a given trigger duration.

In contrast to other outputs/inputs of cards, its parent_device is a trigger, and not the PCI_6602. It is directly instantiated in the connection table. This should not interfere with the ability to use the PCI_6602 object native to labscript This count should work for counting cards other than the 6602, but it has not been tested

The output data from the sequence is stored in an array, the values of which tell you the # of counts between successive triggers