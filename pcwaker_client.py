#!/usr/bin/env python3.4

# we might consider to run this file as a windows service on the target computer:
# http://stackoverflow.com/questions/32404/is-it-possible-to-run-a-python-script-as-a-service-in-windows-if-possible-how
# http://stackoverflow.com/questions/34328/how-do-i-make-windows-aware-of-a-service-i-have-written-in-python
# http://code.activestate.com/recipes/551780/

import os
import pickle
import signal
import socket
import subprocess
import sys
import time
from pcwaker_common import *
from pcconfig import *


terminatingSignalHandled=False


def signalHandler(signum,stackframe):

   # translate signum to text
   sig2text={1:'HUP',2:'INT',15:'TERM'}
   if signum in sig2text:
      sigName=sig2text[signum]
   else:
      sigName=str(signum)

   # test for multiple signals
   global terminatingSignalHandled
   if not terminatingSignalHandled:
      terminatingSignalHandled=True

      # log message
      if signum==signal.SIGINT:
         print('Ctrl-C signal received. Terminating...')
      else:
         print(sigName+' signal received. Terminating...')

      # clean up and exit
      if 'stream' in globals():
         global stream
         stream.close()
      print('Done.')
      sys.exit(0)

   else:

      # log message and exit
      print('Another terminating signal ('+sigName+') received. Terminating immediately.')
      sys.exit(1)


def consoleCtrlHandler(signum,func=None):

   # translate signum to text
   sig2text={0:'CTRL_C_EVENT',1:'CTRL_BREAK_EVENT',2:'CTRL_CLOSE_EVENT',
             5:'CTRL_LOGOFF_EVENT',6:'CTRL_SHUTDOWN_EVENT'}
   if signum in sig2text:
      sigName=sig2text[signum]
   else:
      sigName=str(signum)

   # test for multiple signals
   global terminatingSignalHandled
   if not terminatingSignalHandled:
      terminatingSignalHandled=True

      # log message
      print(sigName+' received. Terminating...')

      # clean up and exit
      if 'stream' in globals():
         global stream
         stream.close()
      print('Done.')
      os._exit(0) # must use _exit to avoid traceback as process is hanging in recv

   else:

      # log message and exit
      print('Another terminating signal received ('+sigName+'). Terminating immediately.')
      sys._exit(0) # must use _exit to avoid traceback as process is hanging in recv


# signal handlers
signal.signal(signal.SIGINT,signalHandler) # Ctrl-C handler
signal.signal(signal.SIGTERM,signalHandler) # termination request
if os.name=='posix':
   signal.signal(signal.SIGHUP,signalHandler) # hang-up or death of controlling process
if os.name=='nt':
   try:
      import win32api
      win32api.SetConsoleCtrlHandler(consoleCtrlHandler,True)
   except ImportError:
      version='.'.join(map(str,sys.version_info))
      print('Error: pywin32 not installed for Python '+version+'.')

# outer main loop
# handling reconnects if connection is broken
print('Starting pcwaker client daemon. Use Ctrl-C to stop the daemon.\n'
      'Connecting to the server '+pcwakerServerAddress[0]+':'+str(pcwakerServerAddress[1])+'...')
exitRequested=False
while not exitRequested:

   # make connection to the daemon process
   s=socket.socket()
   try:
      s.connect(pcwakerServerAddress)
   except ConnectionRefusedError:
      print('Can not connect to '+pcwakerServerAddress[0]+':'+str(pcwakerServerAddress[1])+'. Will try again in 30 seconds...')
      s.close()
      time.sleep(30)
      continue
   stream=Stream(s)

   # send parameters to daemon
   hostName=socket.gethostname()
   print('Sending \"Got alive\" message (this computer name: '+hostName+').')
   stream.send(MSG_COMPUTER,pickle.dumps(['Got alive',hostName],protocol=2))

   # inner main loop
   while True:

      # receive message
      msgType,data=stream.recv()

      if msgType==MSG_COMPUTER:

         # decode data
         params=pickle.loads(data)

         # ignore empty messages
         if len(params)==0:
            continue

         # shutdown message
         if params[0]=='shutdown':
            print('Shutting down...')
            subprocess.call(["shutdown","-s","-t","60"])
            print('Done.')
            exitRequested=True
            break

         # execute command on this computer
         elif params[0]=='command':
            if len(params)==1:
               wlog.error('Error: No command specified.')
            else:
               try:
                  print('Command execution request: '+params[1:]+'.')
                  p=subprocess.Popen(params[1:],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                  t=p.stdout.read()
                  t.wait()
                  if t.returncode==0:
                     print('Command '+params[1:]+' succeed.')
                  else:
                     print('Command '+params[1:]+' returned error code '+t.returncode+'.')
               except OSError:
                  print('Error: Failed to run command: '+params[1:]+'.')

         # unknown param
         else:
            print('Unknown command '+str(params))

      # print info messages
      elif msgType==MSG_LOG:
         print('Server info: '+data.decode(errors='replace'),end='')

      # EOF - connection closed
      elif msgType==MSG_EOF:
         print('Connection closed. Trying to reconnect...')
         break

      else:
         print('Unknown message type')

   # close connection
   stream.close()

# finalize application
print('Daemon successfully terminated.')
