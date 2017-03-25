#!/usr/bin/env python3.4

import os
import pickle
import socket
import struct
import subprocess
import sys
from pcwaker_common import *
from pcconfig import pcwakerListeningPort #,pcwakerServerAddress


# -h and --help or no arguments
if len(sys.argv)<=1 or '-h' in sys.argv or '--help' in sys.argv:
   print('\n'
         'pcwaker - utility for starting and stopping computers using GPIO\n'
         '\n'
         'Usage:\n'
         '   -h, --help, no arguments\n'
         '      Print usage.\n'
         '   daemon start|stop|restart|init-gpio [--debug]\n'
         '      Starts, stops or restarts daemon process (pcwakerd).\n'
         '      init-gpio initializes gpio pins (pull-up and pull-down status\n'
         '      otherwise some LEDs might shine a little, etc.). This is done\n'
         '      automatically on the daemon start. So, init-gpio is useful just\n'
         '      in the case the daemon is not to be started.\n'
         '      Optional --debug parameter causes debug messages to be printed.\n'
         '   status [computer-names]\n'
         '      Prints status of all computers. If computer name(s) are given,\n'
         '      it prints only status of these computers.\n'
         '   start [computer-name]\n'
         '      Starts computer given by computer-name.\n'
         '   stop [computer-name]\n'
         '      Stops computer given by computer-name.\n'
         '   kill [computer-name]\n'
         '      Forcefully powers off the computer. The operation is equal to\n'
         '      pressing power button for five seconds. Use this on frozen computers.\n'
         '   command [computer-name] [command] [command-parameters]\n'
         '      Executes the command on the computer. Command-parameters might\n'
         '      by empty or contain multiple parameters.\n'
         '\n')
   exit(99)

# parse arguments that does not connect to the daemon
if len(sys.argv)>=2 and sys.argv[1]=='daemon':
   daemonFileName=os.path.dirname(os.path.abspath(__file__))+'/pcwakerd'
   if len(sys.argv)<3:
      print('Error: Not enough arguments for daemon parameter.')
      exit(1)
   if sys.argv[2]=='start':
      p=subprocess.Popen([daemonFileName,"--init-print-log"]+sys.argv[3:])
      exit(0)
   if sys.argv[2]=='restart':
      thisFileName=os.path.abspath(__file__)
      p1=subprocess.Popen([thisFileName,"daemon","stop"]+sys.argv[3:])
      r1=p1.wait()
      p2=subprocess.Popen([thisFileName,"daemon","start"]+sys.argv[3:])
      r2=p2.wait()
      if r1==0 and r2==0:
         exit(0)
      else:
         exit(1)
   if sys.argv[2]=='init-gpio':
      subprocess.Popen([daemonFileName,"--init-gpio"]+sys.argv[3:])
      exit(0)

# parse --machine-readable if present
machineReadable=len(sys.argv)>=3 and sys.argv[1]=='status' and sys.argv[2]=='--machine-readable'

# open listeningPortFile
if listeningPortFilePath:
   try:
      listeningPortFile=open(listeningPortFilePath,mode='r')
   except FileNotFoundError:
      print('Error: Can not connect to pcwakerd process. It might be not running\n'
            '   or can not access file \"',listeningPortFilePath,'\".',sep='')
      exit(1)
   except OSError as e:
      print('Error: Unknown error when opening file \"',listeningPortFilePath,'\".\n'
            '   Error string: ',e.strerror,'.',sep='')
      exit(1)

# read listening port
if listeningPortFilePath:
   portString=listeningPortFile.read()
   port=int(portString)
   listeningPortFile.close()
else:
   port=pcwakerListeningPort

# make connection to the daemon process
s=socket.socket()
r=s.connect_ex(('127.0.0.1',port)) # use local connections only, support for
                                   # remote connections seems questionable

# handle errors
if r!=0:
   if r==socket.errno.ECONNREFUSED:
      if len(sys.argv)>=3 and sys.argv[1]=='daemon' and sys.argv[2]=='stop':
         print('Daemon process already stopped.')
         exit(0)
      else:
         print('Daemon process not running or can not connect to it.')
         exit(1)
   print('Error: can not connect to the daemon process (error: '+str(r)+').')
   exit(1)

# send parameters to daemon
stream=Stream(s)
a=sys.argv[1:]
data=pickle.dumps(a,protocol=2)
stream.send(MSG_WAKER,data)

# receive and print response
while True:
   msgType,data=stream.recv()
   if msgType==MSG_EOF:
      break
   if msgType==MSG_WAKER:
      print(pickle.loads(data),end='')
   if msgType==MSG_LOG and not machineReadable:
      print(data.decode(errors='replace'),end='')

# finalize application
stream.close()
