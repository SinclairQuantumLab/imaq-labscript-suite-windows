from dcam import *

attribute_encoding = {
    'exposure': {'value':10**-3,'id':DCAM_IDPROP.EXPOSURETIME,'description':'Exposure time in seconds'},
    'triggerMode': {'value':1,'id':DCAM_IDPROP.TRIGGERSOURCE,'description':'Trigger source; 1 : internal, 2 : external, 3 : software, 4 : masterpulse'},
    'triggerPolarity': {'value':2,'id':DCAM_IDPROP.TRIGGERPOLARITY,'description':'Trigger polarity; 1 : negative, 2 : positive'}, 
    'pixelType': {'value':1,'id':DCAM_IDPROP.IMAGE_PIXELTYPE,'description':'pixel type: 1: Mono 8 2: Mono 16'}, 
    'bufferpixelType': {'value':1,'id':DCAM_IDPROP.BUFFER_PIXELTYPE,'description':'pixel type: 1: Mono 8 2: Mono 16'},
    'readoutMode': {'value':2,'id':DCAM_IDPROP.READOUTSPEED,'description': '1: ultra quiet scan, 2: standard scan'},  
    'binning':{'value':1,'id' : DCAM_IDPROP.BINNING,'description': ' valid binnings: 1, 2, 4'},
    'subarrayMode':{'value':1,'id' : DCAM_IDPROP.SUBARRAYMODE,'description': 'subarray mode 1:off, 2:on'},
    'subarrayHsize':{'value':0,'id' : DCAM_IDPROP.SUBARRAYHSIZE,'description': 'subarray hor. size. (start is top (V) left (H))'},
    'subarrayVsize':{'value':0,'id' : DCAM_IDPROP.SUBARRAYVSIZE,'description': 'subarray vert. size. (start is top (V) left (H))'},
    'subarrayHpos':{'value':0,'id' : DCAM_IDPROP.SUBARRAYHPOS,'description': 'subarray hor. pos. (start is top (V) left (H))'},
    'subarrayVpos':{'value':0,'id' : DCAM_IDPROP.SUBARRAYVPOS,'description': 'subarray vert. pos. (start is top (V) left (H))'},
    'exposure': {'value':10**-3,'id':DCAM_IDPROP.EXPOSURETIME,'description':'Exposure time in seconds'},
    'FrameBundEn': {'value':2,'id': DCAM_IDPROP.FRAMEBUNDLE_MODE,'description':'Enable framebundle 1:off, 2:on'},
    'FrameBundFrames': {'value':4,'id': DCAM_IDPROP.FRAMEBUNDLE_NUMBER,'description':'Number of bundled frames'},
    'OutputTriggerKind': {'value':4,'id': DCAM_IDPROP.OUTPUTTRIGGER_KIND,'description':'Output trigger kind: 4: TRIGGERREADY,6: ANYROWEXPOSURE'},
    'OutputTriggerActive': {'value':1,'id': DCAM_IDPROP.OUTPUTTRIGGER_ACTIVE,'description':'Output trigger active: 1: Edge, 2: Level'},
    'OutputTriggerPolarity': {'value':2,'id': DCAM_IDPROP.OUTPUTTRIGGER_POLARITY,'description':' 1: negative , 2: positive'},
    'TriggerGlobalExposure': {'value':5, 'id': DCAM_IDPROP.TRIGGER_GLOBALEXPOSURE, 'description': ' 1: None, 2: Always, 3: Delayed, 4: Emulate, 5: Global Reset'},
    ####### April 16, 2024
    # to set variable exposure durations, set level 2
	'TriggerType':{'value':1, 'id': DCAM_IDPROP.TRIGGERACTIVE,  'description':'EDGE = 1, LEVEL = 2, SYNCREADOUT = 3, POINT = 4'},
    
    #'triggerMode': {'value':1,'id':DCAM_IDPROP.TRIGGERSOURCE,'description':'Trigger source; 1 : internal, 2 : external, 3 : software, 4 : masterpulse'},  
    }

default_attributes={'exposure':0.001,'triggerMode':1}


