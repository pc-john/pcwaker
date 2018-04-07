#!/usr/bin/env python3.5

import asyncio
import os
import pickle
import subprocess
import signal
import sys
from pcwaker_common import *
from pcconfig import pcwakerListeningPort


async def clientConnectionHandler(message):

	# open connection
	print('Connecting to port '+str(port)+'...')
	try:
		reader,writer=await asyncio.open_connection('127.0.0.1',port,loop=loop)
	except ConnectionRefusedError as e:
		if len(sys.argv)>=3 and sys.argv[1]=='daemon' and sys.argv[2]=='stop':
			print('Daemon process already stopped.')
			exit(0)
		else:
			print('Daemon process not running or can not connect to it.')
			exit(1)
	except OSError as e:
		print('Error: Can not connect to the daemon process.\n'
		      '   ('+type(e).__name__+': '+e.strerror+')')
		exit(1)

	# send message
	print('Sending message '+str(message)+'.')
	stream_write_message(writer,MSG_WAKER,message)
	writer.write_eof()

	# receive messages
	while not reader.at_eof():
		msgType,message=await stream_read_message(reader)
		if msgType==MSG_EOF:
			break
		print(str(message))

	print('Closing the connection.')
	writer.close()


# -h and --help or no arguments
if len(sys.argv)<=1 or '-h' in sys.argv or '--help' in sys.argv:
   print('\n'
         'pcwaker - utility for starting and stopping computers using GPIO\n'
         '\n'
         'Usage:\n'
         '   -h, --help, no arguments\n'
         '      Print usage.\n'
         '   daemon start|stop|restart [--debug]\n'
         '      Starts, stops or restarts daemon process (pcwakerd).\n'
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

   # daemon start
   if sys.argv[2]=='start':

      # register SIGHUP that will be sent by daemon when it is fully up
      def signalHandler(signum,stackframe):
         exit(0)
      signal.signal(signal.SIGHUP,signalHandler)

      # start daemon
      print('Starting daemon process...')
      try:
         p=subprocess.Popen([daemonFileName,"--init-print-log","--signal-start-to-parent"]+sys.argv[3:])
      except OSError as e:
         print('Failed to start daemon process ('+daemonFileName+').\n'
               '   Error: '+ e.strerror)
         exit(1)

      # wait for daemon to start (SIGHUP will be received)
      try:
         p.wait(5)
      except subprocess.TimeoutExpired:
         print('Do not waiting for the daemon to fully start.')
      exit(0)

   # daemon restart
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

# send cmd-line parameters to daemon
message=sys.argv[1:]

# run main loop
loop = asyncio.get_event_loop()
loop.run_until_complete(clientConnectionHandler(message))
loop.close()


sys.exit(0)


# receive and print response
while True:
   msgType,data=stream.recv()
   if msgType==MSG_EOF:
      break
   if msgType==MSG_WAKER:
      print(pickle.loads(data),end='')
   if msgType==MSG_LOG and not machineReadable:
      print(data.decode(errors='replace'),end='')
