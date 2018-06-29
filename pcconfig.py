# listening port of pcwakerd (buildbot uses 9989)
pcwakerListeningPort=9988

# server ip:port address of pcwakerd
pcwakerServerAddress=('cadwork-pi.fit.vutbr.cz',pcwakerListeningPort)

# computers
class pcP4:
	name='P4'
	names=[name]
	powerBitMask=0x01

class pcCore2:
	name='Core2'
	names=[name]
	powerBitMask=0x02

computerList=[pcP4,pcCore2]

