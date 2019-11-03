# listening port of pcwakerd (buildbot uses 9989)
pcwakerListeningPort=9988

# server ip:port address of pcwakerd
pcwakerServerAddress=('cadwork-pi.fit.vutbr.cz',pcwakerListeningPort)

# operating system record
class OperatingSystem:
	name=''
	names=[]
	partition=''
	cmdBootToThisOne=[]
	cmdBootToBootManager=[]
	def __init__(self,name,altNames,partition,cmdBootToThisOne,cmdBootToBootManager):
		self.name=name
		self.names=[name]+altNames
		self.partition=partition
		self.cmdBootToThisOne=cmdBootToThisOne
		self.cmdBootToBootManager=cmdBootToBootManager

# computers
class pcCoffeeLake:
	name='cadwork-i9'
	names=[name,'i9','CoffeeLake']
	powerBitMask=0x0
	bootManagerOS='boot'
	operatingSystems=[
		OperatingSystem('win'  ,['win','win10','windows','win32'],'EE10A1B6'      ,['/home/papoadmin/reboot_to_windows.sh'],[]),
		OperatingSystem('linux',['linux','ubuntu','kubuntu']     ,'/dev/nvme0n1p5',['/home/papoadmin/reboot_to_linux.sh'  ],['/usr/bin/sudo','efibootmgr','--bootnext','0003']),
		OperatingSystem('boot' ,['boot','rescue']                ,'/dev/nvme0n1p7',[],[]),
	]

class pcZen1:
	name='cadwork-a1'
	names=[name,'a1']
	powerBitMask=0x20
	bootManagerOS='boot'
	operatingSystems=[
		OperatingSystem('win'  ,['win','win10','windows','win32'],'EE10A1B6'      ,['/home/papoadmin/reboot_to_windows.sh'],[]),
		OperatingSystem('linux',['linux','ubuntu','kubuntu']     ,'/dev/nvme0n1p5',['/home/papoadmin/reboot_to_linux.sh'  ],['/usr/bin/sudo','efibootmgr','--bootnext','0003']),
		OperatingSystem('boot' ,['boot','rescue']                ,'/dev/nvme0n1p7',[],[]),
	]

class pcXeon5:
	name='cadwork-x5'
	names=[name,'x5','Xeon5']
	powerBitMask=0
	bootManagerOS='boot'
	operatingSystems=[
		OperatingSystem('win'  ,['win','win10','windows','win32'],'EE10A1B6'      ,['/home/papoadmin/reboot_to_windows.sh'],[]),
		OperatingSystem('linux',['linux','ubuntu','kubuntu']     ,'/dev/nvme0n1p5',['/home/papoadmin/reboot_to_linux.sh'  ],['/usr/bin/sudo','efibootmgr','--bootnext','0003']),
		OperatingSystem('boot' ,['boot','rescue']                ,'/dev/nvme0n1p7',[],[]),
	]

class pcHaswell:
	name='cadwork-i4'
	names=[name,'i4','Haswell']
	powerBitMask=0x04
	bootManagerOS='boot'
	operatingSystems=[
		OperatingSystem('win'  ,['win','win10','windows','win32'],'EE10A1B6' ,['/home/papoadmin/reboot_to_windows.sh'],[]),
		OperatingSystem('linux',['linux','ubuntu','kubuntu']     ,'/dev/sda5',['/home/papoadmin/reboot_to_linux.sh'  ],['/usr/bin/sudo','efibootmgr','--bootnext','0003']),
		OperatingSystem('boot' ,['boot']                         ,'/dev/sda7',[],[]),
	]

class pcIvyBridge:
	name='cadwork-i3'
	names=[name,'i3','IvyBridge']
	powerBitMask=0x01
	bootManagerOS='boot'
	operatingSystems=[
		OperatingSystem('win'  ,['win','win10','windows','win32'],'EE10A1B6' ,['/home/papoadmin/reboot_to_windows.sh'],[]),
		OperatingSystem('linux',['linux','ubuntu','kubuntu']     ,'/dev/sda5',['/home/papoadmin/reboot_to_linux.sh'  ],['/usr/bin/sudo','efibootmgr','--bootnext','0003']),
		OperatingSystem('boot' ,['boot','rescue']                ,'/dev/sda7',[],[]),
	]

class pcSandyBridge:
	name='cadwork-i2'
	names=[name,'i2','SandyBridge']
	powerBitMask=0x10
	bootManagerOS='boot'
	operatingSystems=[
		OperatingSystem('win'  ,['win','win10','windows','win32'],'EE10A1B6' ,['/home/papoadmin/reboot_to_windows.sh'],[]),
		OperatingSystem('linux',['linux','ubuntu','kubuntu']     ,'/dev/sda5',['/home/papoadmin/reboot_to_linux.sh'  ],['/usr/bin/sudo','efibootmgr','--bootnext','0003']),
		OperatingSystem('boot' ,['boot','rescue']                ,'/dev/sda7',[],[]),
	]

class pcWestmere:
	name='cadwork-i1'
	names=[name,'i1','Westmere']
	powerBitMask=0x08
	bootManagerOS='boot'
	operatingSystems=[
		OperatingSystem('win'  ,['win','win10','windows','win32'],'EE10A1B6' ,['/home/papoadmin/reboot_to_windows.sh'],[]),
		OperatingSystem('linux',['linux','ubuntu','kubuntu']     ,'/dev/sda5',['/home/papoadmin/reboot_to_linux.sh'  ],['/usr/bin/sudo','efibootmgr','--bootnext','0003']),
		OperatingSystem('boot' ,['boot','rescue']                ,'/dev/sda7',[],[]),
	]

class pcCore2:
	name='cadwork-c2'
	names=[name,'c2','Core2']
	powerBitMask=0x02

class pcP4:
	name='cadwork-p4'
	names=[name,'p4','P4']
	powerBitMask=0x0 # not connected now

computerList=[pcCoffeeLake,pcZen1,pcXeon5,pcHaswell,pcIvyBridge,pcSandyBridge,pcWestmere,pcCore2,pcP4]
