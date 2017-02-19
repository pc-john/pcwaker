# listening port of pcwakerd (buildbot uses 9989)
pcwakerListeningPort=9988

# server ip:port address of pcwakerd
pcwakerServerAddress=('192.168.1.17',pcwakerListeningPort)

# computers
class pcCore2:
   name='Core2'
   names=[name]
   pinPowerButton=17
   pinPowerSense=4
   pinConnectionOkLED=18

class pcP4:
   name='P4'
   names=[name]
   pinPowerButton=22
   pinPowerSense=23
   pinConnectionOkLED=27

computerList=[pcP4,pcCore2]

