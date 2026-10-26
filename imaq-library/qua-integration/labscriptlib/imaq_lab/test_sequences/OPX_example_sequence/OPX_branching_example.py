import labscript as lab
from labscriptlib.imaq_lab.connection_table import ConnectionTable


# Load your hardware definitions
ConnectionTable()

lab.start()

#all sequences take 66.4ms, (this includes the shared beginning and end)

branch_num = 0  #can be 0, 1, 2 (specifies branch, fixed before sequence)

t = 0.0
dt = 0.2e-3

t += 1e-3


c1_AO0.constant(t, 0.0)
do9.go_low(t)


t += 1e-3

do9.go_high(t)
for i in range(10):
    c1_AO0.constant(t,0.1*i +1)
    t += 0.5e-3


c1_AO0.constant(t,0.0)
do9.go_low(t)



if (branch_num == 0):

    t += dt

    c1_AO0.constant(t, 2.6)
    
    t += dt
    do9.go_high(t)
    for i in range(109):
        c1_AO0.constant(t, 2.5 - 0.01*i)
        t += dt

    c1_AO0.constant(t, 0.0)
    do9.go_low(t)

    t+=(1e-3 +dt)
elif(branch_num == 1):
    t += dt

    c1_AO0.constant(t, 2.0)

    t += dt
    do9.go_high(t)
    for i in range(10):
        c1_AO0.constant(t, 0)
        t += dt*(i+1)
        c1_AO0.constant(t, 2.0)
        t += dt*(i+1)

    do9.go_low(t)
    c1_AO0.constant(t, 0.0)
    t += 1e-3
elif(branch_num == 2):
    t += dt

    c1_AO0.constant(t, 2.0)
    
    t += dt
    do9.go_high(t)
    for i in range(10):
        c1_AO0.constant(t, 0)
        t += dt*(10-i)
        c1_AO0.constant(t, 2.0)
        t += dt*(10-i)

    do9.go_low(t)
    c1_AO0.constant(t, 0)
    t += 1e-3


t += 1e-3
do9.go_high(t)
for i in range (30):
    c1_AO0.constant(t, 0.1*i)
    t += dt
    c1_AO0.constant(t, 0)
    t += dt

do9.go_low(t)
c1_AO0.constant(t, 0.0)
t += 1e-3

lab.stop(t)





