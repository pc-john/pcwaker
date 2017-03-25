#!/usr/bin/env python3.4

#
# pcwakerd.py [without parameters]
#
#    Starts the process as the normal application.
#
# pcwakerd.py --init-gpio
#
#    Initializes GPIO pins to their default state and exits
#    (This is performed on any pcwakerd.py start anyway. But
#    sometimes we do not want to start pcwakerd.py on system boot,
#    but we might want to initialize GPIO pins.)
#

#
# pcwaker.py daemon [start|restart|stop|init-gpio]
#
#    Controls pcwakerd.py daemon.
#
# pcwaker.py status [--machine-readable] [computer-names]
#
#    Prints the status of specified computer and OS booted as
#    some computers have more OS installed. Status can be:
#    OFF, ON, OCCUPIED, BOOTING-UP, SHUTTING-DOWN.
#    If no computer names are given, all configured computers
#    are printed.
#
# pcwaker.py list
#
#    Prints all configured computers that this utility is expected to control
#    and all OS installed on them configured to be used with this utility.
#    NOT IMPLEMENTED YET.
#
# pcwaker.py start [computer-name] [os-to-boot]
#
#    Powers on the computer. Does nothing if the computer is already running.
#    The powering-on procedure is applied only if the computer is in OFF state.
#    Nothing is done in ON, ON-AND-BUSY and BOOTING states.
#    Failure is returned if the computer state is SHUTTING-DOWN.
#
# pcwaker.py stop [computer-name]
#
#    Switches the computer off.
#
# pcwaker.py kill [computer-name]
#
#    Forcefully powers off the computer. The operation is equal to
#    pressing power button for five seconds. Use this on frozen computers.
#
# pcwaker.py command [computer-name] [command-to-run] [command-parameters]
#
#    Executes the command on the computer.
#



# LED:
# green - power on
# blue - missing network communication
# red - power switch rele on

import argparse
import logging
import logging.handlers
import os
import pickle
import signal
import socket
import subprocess
import sys
import threading
import time
import RPi.GPIO as GPIO
from pcwaker_common import *
from pcconfig import *


StatusOff=1
StatusBooting=2
StatusOn=3
StatusLostConnection=4
StatusShuttingDown=5

stopFlag=False
restartFlag=False
shutdownLog=None
terminatingSignalHandled=False
threadList=[]


# log handler that sends log messages over command connection back to the client
class ConnectionLogHandler(logging.Handler):

   def __init__(self,stream):
      logging.Handler.__init__(self)
      self.stream=stream

   def emit(self,record):
      # multithreaded lock is in handle() method,
      # thus only single thread may enter this method
      try:
         text=self.format(record)
         if len(text)>0:
            data=(text+'\n').encode(errors='replace')
            self.stream.send(MSG_LOG,data) # if not all data are sent, they are sent with another read or write request
      except Exception:
         self.handleError(record)


def getComputer(name):
   global computerList
   pcList=[x for x in computerList if name in x.names]
   if len(pcList)==0:
      return None
   else:
      return pcList[0]


def getComputerStatus(pc):
   if GPIO.input(pc.pinPowerSense)==0:
      return StatusOff
   else:
      if pc.shutdownRequested:
         return StatusShuttingDown
      else:
         if pc.booting:
            return StatusBooting
         if pc.stream is None:
            return StatusLostConnection
         else:
            return StatusOn


def statusToString(status):
   m={
      StatusOff:     "OFF",
      StatusBooting: "Booting",
      StatusOn:      "ON",
      StatusLostConnection: "Lost connection",
      StatusShuttingDown:   "Shutting down"
   }
   return m.get(status,"unknown")


class WorkerThread(threading.Thread):

   def __init__(self,socket):
      socket.setblocking(False)
      self.stream=Stream(socket)
      self._terminateRequest=False
      self.associatedComputer=None
      threading.Thread.__init__(self,target=self.doWork)

   def terminate(self):
      self._terminateRequest=True

   def doWork(self):

      # initialize log
      # log messages are sent to two targets: logged in main thread log
      # and sent over command connection back to the client
      wlog=logging.Logger('WorkerThreadLogger',rootLog.level)
      wlog.parent=rootLog
      wlogHandler=ConnectionLogHandler(self.stream)
      wlog.addHandler(wlogHandler)
      wlog.debug('Worker thread started.')

      ## main loop of worker thread
      while True:

         msgType,data=self.stream.recv(timeout=1.0)

         # process messages from pcwaker.py
         if msgType==MSG_WAKER:

            # decode data
            params=pickle.loads(data)
            wlog.debug('Message received from pcwaker: '+str(params))

            # ignore empty messages
            if len(params)==0:
               continue

            # daemon restart/stop
            if params[0]=='daemon':

               if len(params)==1:
                  wlog.error('Error: Not enough arguments for daemon parameter.')
                  break

               if params[1]=='stop' or params[1]=='restart':
                  global stopFlag
                  global restartFlag
                  global shutdownLog
                  shutdownLog=wlog
                  if params[1]=='restart':
                     restartFlag=True
                  stopFlag=True # this must be the last flag set
                  tmpSocket=socket.socket()
                  try:
                     tmpSocket.connect(('127.0.0.1',listeningPort))
                     tmpData=tmpSocket.recv(1) # we never receive anything, just when other side closes, we will get unblocked
                  except ConnectionRefusedError:
                     pass
                  tmpSocket.close()
                  wlog.debug('Worker thread scheduled mainloop exit.')

               else:
                  wlog.error('Unknown parameter 1: '+params[1])

               break

            # status of computer(s)
            elif params[0]=='status':

               # parse --machine-readable if present
               p=params[1:]
               machineReadable=len(p)>0 and p[0]=='--machine-readable'
               if machineReadable:
                  p=p[1:]

               # get computer list
               if len(p)==0:
                  list=computerList
               else:
                  list=[]
                  for name in p:
                     pc=getComputer(name)
                     if pc==None:
                        wlog.critical(name+' is not a configured computer.')
                     else:
                        list.append(pc)

               # print result
               if machineReadable:
                  for pc in list:
                     self.stream.send(MSG_WAKER,pickle.dumps(statusToString(getComputerStatus(pc)),protocol=2))
               else:
                  for pc in list:
                     wlog.critical('Computer '+pc.name+':')
                     wlog.critical('   Status: '+statusToString(getComputerStatus(pc)))
               break

            # start computer
            elif params[0]=='start':
               if len(params)==1:
                  wlog.error('Error: No computer(s) specified.')
               else:
                  list=[]
                  ok=True
                  for name in params[1:]:
                     pc=getComputer(name)
                     if pc==None:
                        wlog.critical(name+' is not a configured computer.')
                        ok=False
                     else:
                        list.append(pc)
                  if not ok:
                     break
                  for pc in list:
                     status=getComputerStatus(pc)
                     if status==StatusOff:
                        # if off, start it
                        wlog.info('Starting computer '+pc.name+'...')
                        GPIO.output(pc.pinPowerButton,1)
                        time.sleep(0.5)
                        GPIO.output(pc.pinPowerButton,0)
                        time.sleep(0.1)
                        if GPIO.input(pc.pinPowerSense)==0:
                           wlog.critical('Failed to start computer '+pc.name+'.')
                           pc.booting=False
                        else:
                           wlog.critical('Computer '+pc.name+' successfully started.')
                           pc.booting=True
                        pc.shutdownRequested=False
                     else:
                        if status==StatusOn:
                           # if on, do nothing
                           wlog.critical('Computer '+pc.name+' is already running (status: ON).')
                        else:
                           # if booting or shutting down, print error
                           wlog.critical('Can not start computer '+pc.name+'. It is not in OFF state (currently: '+statusToString(status)+').')
               break

            # stop computer
            elif params[0]=='stop':
               if len(params)==1:
                  wlog.error('Error: No computer(s) specified.')
               else:
                  list=[]
                  ok=True
                  for name in params[1:]:
                     pc=getComputer(name)
                     if pc==None:
                        wlog.critical(name+' is not a configured computer.')
                        ok=False
                     else:
                        list.append(pc)
                  if not ok:
                     break
                  for pc in list:
                     status=getComputerStatus(pc)
                     if status==StatusOn:
                        # if on, stop it
                        wlog.info('Stopping computer '+pc.name+'...')
                        pc.stream.send(MSG_COMPUTER,pickle.dumps(['shutdown'],protocol=2))
                        pc.shutdownRequested=True
                     else:
                        if status==StatusOff:
                           # if off, do nothing
                           pass
                        else:
                           # if booting or shutting down, print error
                           wlog.critical('Can not stop computer '+pc.name+'. It is not in ON state (currently '+statusToString(status)+').')
               break

            # kill computer
            elif params[0]=='kill':
               if len(params)==1:
                  wlog.error('Error: No computer(s) specified.')
               else:
                  list=[]
                  ok=True
                  for name in params[1:]:
                     pc=getComputer(name)
                     if pc==None:
                        wlog.critical(name+' is not a configured computer.')
                        ok=False
                     else:
                        list.append(pc)
                  if not ok:
                     break
                  for pc in list:
                     status=getComputerStatus(pc)
                     if status==StatusOff:
                        wlog.info('Computer '+pc.name+' is already in OFF state.')
                     else:
                        wlog.info('Stopping computer '+pc.name+'...')

                        # press power button and test each 0.5s if computer switched off
                        GPIO.output(pc.pinPowerButton,1)
                        for i in range(15): # wait max 7.5s
                           time.sleep(0.5)
                           if GPIO.input(pc.pinPowerSense)==0:
                              break;

                        # release power button
                        GPIO.output(pc.pinPowerButton,0)
                        time.sleep(0.5)

                        # evaluate final state
                        if GPIO.input(pc.pinPowerSense)==0:
                           wlog.info('Computer '+pc.name+' switched off.')
                           pc.booting=False
                           pc.shutdownRequested=False
                        else:
                           wlog.critical('Failed to kill computer '+pc.name+'.')
               break

            # execute command on computer
            elif params[0]=='command':
               if len(params)==1:
                  wlog.error('Error: No computer specified.')
               else:
                  if len(params)==2:
                     wlog.error('Error: No computer or command specified. Use \"command computer-name command-and-parameters\".')
                  else:
                     pc=getComputer(params[1])
                     if pc==None:
                        wlog.critical(params[1]+' is not a configured computer.')
                     else:
                        if pc.stream is None:
                           wlog.error('Error: Can not send command to the computer that is not in ON state (computer:'+pc.name+').')
                        else:
                           wlog.info('Sending command to '+params[1]+' to be executed (command: '+str(params[2:])+').')
                           pc.stream.send(MSG_COMPUTER,pickle.dumps(['command']+params[2:],protocol=2))
               break

            # unknown command
            else:
               wlog.error('Unknown command: '+params[0])
               break

         # process messages from client processes on monitored computers
         if msgType==MSG_COMPUTER:

            # decode data
            params=pickle.loads(data)
            wlog.debug('Message received from computer: '+str(params))

            # ignore empty messages
            if len(params)==0:
               continue

            # Got alive message
            if params[0]=='Got alive':
               if len(params)>=2: computerName=params[1]
               else: computerName=None
               pc=getComputer(computerName)
               if pc!=None:
                  pc.stream=self.stream
                  pc.booting=False
                  self.associatedComputer=pc
                  log.critical('Computer '+pc.name+' got alive')
               else:
                  log.critical('Computer '+params[1]+' attempt to announce it is alive, but it is not a registered computer.')
                  break

            # unknown message
            else:
               wlog.error('Unknown computer message data: '+str(data))

         # EOF - connection closed
         if msgType==MSG_EOF:
            wlog.debug('Worker thread connection closed.')

            # close associated computer stream if exists
            if self.associatedComputer:
               wlog.info('Computer '+self.associatedComputer.name+' connection was closed by peer. Closing socket...')
               wlog.removeHandler(wlogHandler)
               self.associatedComputer.stream.close()
               self.associatedComputer.stream=None
               self.stream=None

            break

         # termination request - comes from main thread loop
         if self._terminateRequest:
            wlog.debug('Worker thread termination request.')
            break

      wlog.debug('Worker thread cleaning up...')

      # remove link to associated computer if exists
      if self.associatedComputer:
         if self.associatedComputer.stream:
            wlog.info('Closing connection to the computer '+self.associatedComputer.name+'.')
            wlog.removeHandler(wlogHandler)
            self.associatedComputer.stream.close()
            self.associatedComputer.stream=None
            self.stream=None
         self.associatedComputer=None

      # close connection
      # (close of connection terminating pcwakerd.py is postponed, it will be closed by main thread)
      if wlog!=shutdownLog:
         if self.stream:
            wlog.removeHandler(wlogHandler)
            self.stream.close()

      wlog.debug('Worker thread done.')


def cleanUp():
   GPIO.cleanup()
   if listeningPortFilePath:
      listeningPortFile.close()
      os.remove(listeningPortFilePath)
   if 'commandListeningSocket' in globals():
      global commandListeningSocket
      commandListeningSocket.close()


def signalHandler(signum,stackframe):

   # translate signum to text
   sig2text={1:'HUP',15:'TERM'}
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
         log.critical('Ctrl-C signal received. Terminating...')
      else:
         log.critical(sigName+' signal received. Terminating...')

      # clean up and exit
      cleanUp()
      log.info('Done.')
      sys.exit(1)

   else:

      # log message and exit
      log.critical('Another terminating signal ('+sigName+') received. Terminating immediately.')
      sys.exit(1)


# init argument parser
argParser=argparse.ArgumentParser(description='PCWaker daemon for switching on computers, '
                                  'monitoring them and safely shutting them down.')
argParser.add_argument('--debug',help='Sets debug level to "debug". '
                                      'Much of internal information will be printed.',
                       action='store_true')
argParser.add_argument('--debug-level',type=str,help='Sets debug level. '
                       'Valid values are debug, info, warning, error, critical.',
                       action='store')
argParser.add_argument('--init-gpio',help='Initializes GPIO pins and exits.',
                       action='store_true')
argParser.add_argument('--init-print-log',
                       action='store_true')
args=argParser.parse_args()

# signal handlers
signal.signal(signal.SIGINT,signalHandler) # Ctrl-C handler
signal.signal(signal.SIGHUP,signalHandler) # hang-up or death of controlling process
signal.signal(signal.SIGTERM,signalHandler) # terminate request

# initialize logger
rootLog=logging.getLogger()
logFileHandler=logging.handlers.RotatingFileHandler(logFilePath,maxBytes=100*1024,backupCount=1)
logFileHandler.setFormatter(logging.Formatter('%(asctime)-15s %(message)s'))
rootLog.addHandler(logFileHandler)
logFileHandler.doRollover()
rootLog.setLevel(logging.INFO)
if args.debug:
   rootLog.setLevel(logging.DEBUG)
else:
   if args.debug_level:
      rootLog.setLevel(args.debug_level.upper())
if os.isatty(sys.stdout.fileno()) or args.init_print_log:
   # for more info to detect daemonized status see:
   # http://stackoverflow.com/questions/24861351/how-to-detect-if-python-script-is-being-run-as-a-background-process
   # http://stackoverflow.com/questions/14894261/programmatically-check-if-a-process-is-being-run-in-the-background
   logStdOutHandler=logging.StreamHandler(stream=sys.stdout)
   rootLog.addHandler(logStdOutHandler)
   rootLog.debug('Log brought up and output to stdout was added.')
log=logging.getLogger('main')
log.setLevel(rootLog.level)
log.critical('pcwakerd.py started with arguments: '+str(sys.argv[1:])+
             ' and debug level '+logging.getLevelName(log.level)+'.')

# create listeningPortFile
if listeningPortFilePath:
   try:
      listeningPortFile=open(listeningPortFilePath,mode='x')
   except FileNotFoundError:
      log.critical('Error: Can not create file '+listeningPortFilePath+'.\n'
                   '   Make sure parent directories exist and proper access rights are set.')
      exit(1)
   except FileExistsError:
      log.critical('Error: Another instance is already running.\n'
                   '   If it is not the case, delete file \"'+listeningPortFilePath+'\".')
      exit(1)
   except OSError as e:
      log.critical('Error: Unknown error when creating file \"'+listeningPortFilePath+'\".\n'
                   '   Error string: '+e.strerror+'.')
      exit(1)

# initialize GPIO
GPIO.setmode(GPIO.BCM)
log.info('Initializing computers:')
for pc in computerList:
   log.info('   '+pc.name)
   GPIO.setup(pc.pinPowerButton,GPIO.OUT,initial=0)
   GPIO.setup(pc.pinPowerSense,GPIO.IN,pull_up_down=GPIO.PUD_DOWN)
   GPIO.setup(pc.pinConnectionOkLED,GPIO.OUT,initial=1)
   if not args.init_gpio:
      time.sleep(0.15)
   GPIO.output(pc.pinConnectionOkLED,0)

# exit if --init-gpio
if args.init_gpio:
   cleanUp()
   log.info('Done.')
   exit(0)

# init listening socket
log.info('Initializing network:')
commandListeningSocket=socket.socket()
commandListeningSocket.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
try:
   if pcwakerListeningPort!=0:
      commandListeningSocket.bind(('',pcwakerListeningPort)) # FIXME: this may fail if somebody is already listening on the port
   else:
      commandListeningSocket.bind(('127.0.0.1',0)) # FIXME: this may fail if somebody is already listening on the port
   commandListeningSocket.listen(5)
except OSError as msg:
   commandListeningSocket.close()
   log.critical('Network error. Terminating.')
   cleanUp()
   log.info('Done.')
   sys.exit(1)
addr,listeningPort=commandListeningSocket.getsockname()
if listeningPortFilePath:
   listeningPortFile.write(str(listeningPort))
   listeningPortFile.flush()
log.info('   Commands are expected on the port '+str(listeningPort)+'.')

# stop logging to stdout for --init-print-log here
log.info('Running...')
if args.init_print_log:
   rootLog.removeHandler(logStdOutHandler)
   sys.stdout.flush()
   os.close(sys.stdout.fileno())

# initialize computers
for pc in computerList:
   pc.stream=None
   pc.booting=True
   pc.shutdownRequested=False

# main loop
while True:

   # accept new connection
   connection,addr=commandListeningSocket.accept()

   # delete finished threads
   newList=[]
   for t in threadList:
      if t.is_alive():
         newList.append(t)
      else:
         t.join()
   threadList=newList

   # leave main loop
   if stopFlag:
      connection.close()
      if shutdownLog:
         log.parent=shutdownLog
      log.info('Stopping...')
      break

   # start new thread
   t=WorkerThread(connection)
   threadList.append(t)
   t.start()
   if not t.is_alive(): # we need the flag set to true immediately
      log.critical('Error: thread did not came to life immediately.\n'
                   '   Redesign algorithms around thread starting.')
      sys.exit(1)

# stop listening socket
commandListeningSocket.close()

# stop remaining threads
# (there is timeout of 1.5 second for them to finish)
if len(threadList)!=0:
   log.info('Waiting for '+str(len(threadList))+' thread(s)...')
   for t in threadList:
      t.terminate()
   for i in range(15): # wait 1.5 second max
      time.sleep(0.1)
      newList=[]
      for t in threadList:
         if t.is_alive():
            newList.append(t)
         else:
            t.join()
      threadList=newList
      if len(threadList)==0:
         break
   if len(threadList)!=0:
      log.error('Error: Pending '+str(len(threadList))+' WorkerThread(s).')

# finalize application
log.info('Terminating...')
cleanUp()
if restartFlag:

   # restart the process
   log.info('Restarting process...')
   p=subprocess.Popen(["./pcwakerd.py","--init-print-log"],stdout=subprocess.PIPE)

   # write new process output to log
   # (but first remove termintating '\n')
   s=p.stdout.read().decode(errors='replace')
   if len(s)>0 and s[-1]=='\n':
      s=s[:-1]
   log.info(s)

else:
   log.info('Done.')

# close connection to the client that initiated daemon shut down
# (we used the connection to forward all log messages)
if shutdownLog:
   shutdownLog.handlers[0].stream.close()
