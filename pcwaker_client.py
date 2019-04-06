#!/usr/bin/env python3

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
MSG_PING_SCHEDULE=4  # message used for connection ping
MSG_PING_REQUEST=5   # message used for connection ping
MSG_PING_ANSWER=6    # message used for connection ping


terminatingSignalHandled=False
reader=None
timeOfLastPingRequest=0
timeOfLastPingAnswer=0


@asyncio.coroutine
def connectionHandler():

	# repeat connection attempts whenever connection gets broken
	exitRequested=False
	global reader
	global timeOfLastPingRequest
	global timeOfLastPingAnswer
	lastReconnectTime=time.monotonic()-20
	while not exitRequested:

		# open connection
		print('Connecting to the server '+pcwakerServerAddress[0]+':'+str(pcwakerServerAddress[1])+'...')
		try:
			reader,writer=yield from asyncio.open_connection(pcwakerServerAddress[0],port=pcwakerServerAddress[1],loop=loop)
		except (ConnectionRefusedError,OSError) as e:
			print('Can not connect to '+pcwakerServerAddress[0]+':'+str(pcwakerServerAddress[1])+
			      '. Will try again in 30 seconds...')
			for i in range(60):  # wait 30 seconds and allow interrupts (such as Ctrl-C) to be handled each 500ms
				yield time.sleep(0.5)
			continue

		try:
			try:
				# send parameters to daemon
				hostName=socket.gethostname()
				print('Sending \"Got alive\" message (this computer name: '+hostName+').')
				stream_write_message(writer,MSG_COMPUTER,pickle.dumps(['Got alive',hostName],protocol=2))

				# send the first ping request
				timeOfLastPingRequest=time.monotonic()
				timeOfLastPingAnswer=0
				stream_write_message(writer,MSG_PING_REQUEST,timeOfLastPingRequest)

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

					# pingHandler scheduled sending of ping
					elif msgType==MSG_PING_SCHEDULE:
						if timeOfLastPingRequest!=timeOfLastPingAnswer:
							print('Connection lost (ping timeout).')
							break # close connection
						timeOfLastPingRequest=message
						stream_write_message(writer,MSG_PING_REQUEST,message)
						continue

					# peer sent ping request
					elif msgType==MSG_PING_REQUEST:
						stream_write_message(writer,MSG_PING_ANSWER,message)
						continue

					# peer sent ping answer
					elif msgType==MSG_PING_ANSWER:
						timeOfLastPingAnswer=message
						continue

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
							elif sys.platform.startswith('linux'):
								subprocess.call(['/usr/bin/sudo','shutdown','--poweroff','+1','pcwaker scheduled shutdown in one minute. Use \"shutdown -c\" to cancel.'])
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
										print('Command '+str(params[1:])+' succeeded',end='')
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
						print('Server info: '+str(message))
						continue

					else:
						print('Unknown message type')
						continue

			finally:
				# close connection
				writer.close()
				reader=None
				timeOfLastPingRequest=0
				timeOfLastPingAnswer=0

		except ConnectionResetError as e:
			# log connection reset
			print('Connection reset. Trying to reconnect...')

		except (SystemExit,Exception) as e:
			# exit called or Exception raised
			print('Connection closed.')
			raise e

		else:
			# connection closed -> try to reconnect
			print('Connection closed. Trying to reconnect...')

		# avoid too quick reconnects
		if not exitRequested:
			if time.monotonic()-lastReconnectTime<10:
				print('Reconnecting in 30s...')
				for i in range(60):  # wait 30 seconds and allow interrupts (such as Ctrl-C) to be handled each 500ms
					yield time.sleep(0.5)
			lastReconnectTime=time.monotonic()


@asyncio.coroutine
def pingHandler():

	try:
		while True:

			# sleep 10s
			yield from asyncio.sleep(10)

			# do not do anything if no connection yet
			if reader==None:
				continue

			# prepare data to send
			data3=pickle.dumps(time.monotonic(),protocol=2)
			data1=struct.pack('!I',MSG_PING_SCHEDULE)
			data2=struct.pack('!I',len(data3))
			data=data1+data2+data3

			# feed data to readers
			reader.feed_data(data)

	except asyncio.CancelledError:
		pass


# taken from pcwaker_common.py:
def stream_write_message(writer,msgType,message):
	data=pickle.dumps(message,protocol=2)
	writer.write(struct.pack('!I',msgType))
	writer.write(struct.pack('!I',len(data)))
	writer.write(data)


def signalCallback(text):
	# print message and cancel connectionHandler task
	print(text)
	connectionTask.cancel()
	pingTask.cancel()


def signalHandler(signum,stackframe):

	# translate signum to text
	if os.name=='nt':
		sig2text={signal.SIGTERM:'TERM',signal.SIGINT:'INT',signal.CTRL_C_EVENT:'Ctrl-C'}  # Windows signals
	else:
		sig2text={signal.SIGHUP:'HUP',signal.SIGTERM:'TERM',signal.SIGINT:'Ctrl-C'}  # Linux signals
	if signum in sig2text:
		sigName=sig2text[signum]
	else:
		sigName=str(signum)

	# test for multiple signals
	global terminatingSignalHandled
	if not terminatingSignalHandled:
		terminatingSignalHandled=True

		# schedule signalCallback for execution
		loop.call_soon_threadsafe(signalCallback,sigName+' signal received. Terminating...')

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

		# schedule signalCallback for execution
		loop.call_soon_threadsafe(signalCallback,sigName+' received. Terminating...')

	else:

		# log message and exit without any clean up
		print('Another terminating signal ('+sigName+') received. Terminating immediately.')
		os._exit(1)


# initialization
loop=asyncio.get_event_loop()
connectionTask=loop.create_task(connectionHandler())
pingTask=loop.create_task(pingHandler())
try:
	# set line buffering for stdout
	# (otherwise text is buffered for long time and appears only after flush)
	sys.stdout=os.fdopen(sys.stdout.fileno(),'w',1)

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
	print('Starting pcwaker client daemon. Use Ctrl-C to stop the daemon.')
	loop.run_until_complete(connectionTask)

except asyncio.CancelledError:
	pass # just catch and ignore the exception
finally:
	print("Cleaning up...")
	pingTask.cancel()
	loop.run_until_complete(pingTask)
	loop.close()

print('Terminating pcwaker client daemon successfully.')
