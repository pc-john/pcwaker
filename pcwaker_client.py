#!/usr/bin/env python3.4

# we might consider to run this file as a windows service on the target computer:
# http://stackoverflow.com/questions/32404/is-it-possible-to-run-a-python-script-as-a-service-in-windows-if-possible-how
# http://stackoverflow.com/questions/34328/how-do-i-make-windows-aware-of-a-service-i-have-written-in-python
# http://code.activestate.com/recipes/551780/

import asyncio
import os
import pickle
import signal
import socket
import struct
import subprocess
import sys
import time
from pcconfig import *

# taken from pcwaker_common.py:
# message ids used for stream message content identification
MSG_EOF=0          # opposite side closed the stream and will only receive until we sent EOF as well
MSG_LOG=1          # log messages that could be printed on the screen for the user or ignored
MSG_USER=2         # messages exchanged between pcwaker.py (user interacting utility) and pcwakerd.py (daemon)
MSG_COMPUTER=3     # messages exchanged bettwen pcwaker_client.py (client computer) and pcwakerd.py (daemon)


terminatingSignalHandled=False


def connectionHandler():

	# repeat connection attempts whenever connection gets broken
	exitRequested=False
	while not exitRequested:

		# open connection
		print('Connecting to the server '+pcwakerServerAddress[0]+':'+str(pcwakerServerAddress[1])+'...')
		try:
			reader,writer=yield from asyncio.open_connection(pcwakerServerAddress[0],port=pcwakerServerAddress[1],loop=loop)
		except (ConnectionRefusedError,OSError) as e:
			print('Can not connect to '+pcwakerServerAddress[0]+':'+str(pcwakerServerAddress[1])+
			      '. Will try again in 30 seconds...')
			time.sleep(30)
			continue

		try:
			try:
				# send parameters to daemon
				hostName=socket.gethostname()
				print('Sending \"Got alive\" message (this computer name: '+hostName+').')
				stream_write_message(writer,MSG_COMPUTER,pickle.dumps(['Got alive',hostName],protocol=2))

				# message loop
				while True:

					# read msgType
					data=yield from reader.read(4)
					if len(data)!=4:
						if len(data)==0 and reader.at_eof(): break
						raise OSError(84,'Illegal byte sequence.')
					msgType,=struct.unpack_from('!I',data,0)

					# read msgSize
					data=yield from reader.read(4)
					if len(data)!=4: raise OSError(84,'Illegal byte sequence.')
					msgSize,=struct.unpack_from('!I',data,0)

					# read message
					data=yield from reader.read(msgSize)
					if len(data)!=msgSize: OSError(84,'Illegal byte sequence.')
					message=pickle.loads(data)

					# EOF - connection closed
					if msgType==MSG_EOF:
						print('Server closed the connection.')
						break

					elif msgType==MSG_COMPUTER:

						# decode data
						params=pickle.loads(message)

						# ignore empty messages
						if len(params)==0:
							continue

						# shutdown message
						if params[0]=='shutdown':
							print('Scheduling shutdown in 1 minute...')
							if sys.platform.startswith('cygwin'):
								subprocess.call(['shutdown','--shutdown','60'])
							elif sys.platform.startswith('win32'):
								subprocess.call(['shutdown','-s','-t','60'])
							else:
								print('Error: No shutdown code for this operating system.')
							print('Done.')
							exitRequested=True
							break

						# execute command on this computer
						elif params[0]=='command':
							if len(params)==1:
								print('Error: No command specified.')
							else:
								try:

									# run command
									print('Executing command: '+str(params[1:])+'.')
									p=subprocess.Popen(params[1:],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
									t,_=p.communicate()

									# print return code
									if p.returncode==0:
										print('Command '+str(params[1:])+' succeed',end='')
									else:
										print('Command '+str(params[1:])+' returned error code '+str(p.returncode),end='')

									# print output
									if(len(t)==0):
										print('.')
									else:

										# decode string
										t=t.decode("utf-8")

										# remove ending new line
										l=len(t)-1
										if(t[l]=='\n'):
											t=t[:l]

										# print output
										print(' with output:\n'+t)

								except OSError:
									print('Error: Failed to run command: '+str(params[1:])+'.')
							continue

						# unknown param
						else:
							print('Unknown command '+str(params))
							continue

					# print info messages
					elif msgType==MSG_LOG:
						print('Server info: '+str(message),end='')
						continue

					else:
						print('Unknown message type')
						continue

			finally:
				# close connection
				writer.drain()
				writer.close()

		except (SystemExit,Exception) as e:
			# exit called or Exception raised
			print('Connection closed.')
			raise e
		else:
			# connection lost or closed -> try to reconnect
			print('Connection closed. Trying to reconnect...')


# taken from pcwaker_common.py:
def stream_write_message(writer,msgType,message):
	data=pickle.dumps(message,protocol=2)
	writer.write(struct.pack('!I',msgType))
	writer.write(struct.pack('!I',len(data)))
	writer.write(data)


def signalHandler(signum,stackframe):

	# translate signum to text
	sig2text={signal.SIGHUP:'HUP',signal.SIGTERM:'TERM',signal.SIGINT:'Ctrl-C'}
	if signum in sig2text:
		sigName=sig2text[signum]
	else:
		sigName=str(signum)

	# test for multiple signals
	global terminatingSignalHandled
	if not terminatingSignalHandled:
		terminatingSignalHandled=True

		# log message
		print(sigName+' signal received. Terminating...')

		# exit (clean up is performed in finally clauses)
		sys.exit(0)

	else:

		# log message and exit without any clean up
		print('Another terminating signal ('+sigName+') received. Terminating immediately.')
		os._exit(1)


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

		# exit (clean up is performed in finally clauses)
		sys.exit(0)

	else:

		# log message and exit without any clean up
		print('Another terminating signal ('+sigName+') received. Terminating immediately.')
		os._exit(1)


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

# main loop
# handles reconnects if connection is broken
print('Starting pcwaker client daemon. Use Ctrl-C to stop the daemon.')
loop=asyncio.get_event_loop()
try:
	loop.run_until_complete(connectionHandler())
finally:
	loop.close()

print('Terminating pcwaker client daemon successfully.')
