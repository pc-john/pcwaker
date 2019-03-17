# listening port of pcwakerd (buildbot uses 9989)
pcwakerListeningPort=9988

# server ip:port address of pcwakerd
pcwakerServerAddress=('cadwork-pi.fit.vutbr.cz',pcwakerListeningPort)

# computers
class pcHaswell:
	name='cadwork-i4'
	names=[name,'i4','Haswell']
	powerBitMask=0x08

class pcIvyBridge:
	name='cadwork-i3'
	names=[name,'i3','IvyBridge']
	powerBitMask=0x04

class pcSandyBridge:
	name='cadwork-i2'
	names=[name,'i2','SandyBridge']
	powerBitMask=0x10

class pcCore2:
	name='cadwork-c2'
	names=[name,'c2','Core2']
	powerBitMask=0x02

class pcP4:
	name='cadwork-p4'
	names=[name,'p4','P4']
	powerBitMask=0x01

computerList=[pcHaswell,pcIvyBridge,pcSandyBridge,pcCore2,pcP4]
