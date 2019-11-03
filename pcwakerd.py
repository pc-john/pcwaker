#!/usr/bin/env python3.5

#
# pcwakerd [without parameters]
#
#    Starts the process as the normal application.
#
#
# pcwaker daemon [start|stop|restart]
#
#    Controls pcwakerd daemon.
#
# pcwaker status [--machine-readable] [computer-names]
#
#    Prints the status of specified computer and OS booted as
#    some computers have more OS installed. Status can be:
#    OFF, ON, STARTING, STOPPING, FROZEN, START_AFTER_STOPPED, STOP_AFTER_STARTED.
#    If no computer names are given, all configured computers
#    are printed.
#
# pcwaker list
#
#    Prints all configured computers that this utility is expected to control
#    and all OS installed on them configured to be used with this utility.
#    NOT IMPLEMENTED YET.
#
# pcwaker start [computer-name]
#
#    Powers on the computer. Does nothing if the computer is already running.
#    The powering-on procedure is applied only if the computer is in OFF state.
#    Nothing is done in ON, ON-AND-BUSY and BOOTING states.
#    Failure is returned if the computer state is SHUTTING-DOWN.
#
# pcwaker stop [computer-name]
#
#    Switches the computer off.
#
# pcwaker kill [computer-name]
#
#    Forcefully powers off the computer. The operation is equal to
#    pressing power button for five seconds. Use this on frozen computers.
#
# pcwaker command [computer-name] [command-to-run] [command-parameters]
#
#    Executes the command on the computer.
#

#
# Computer states and transitions:
# OFF - no power, no connection
#     - start - send 0.5s power signal and test for power sense,
#               on success move to STARTING state, on failure keep OFF state
#     - stop - ignored
#     - kill - ignored
#     - command - print error, if connection exists, print warning but execute the command
#     - power detected ->STARTING
#     - connection detected -> check power and move to ON on power or keep OFF if no power
#     - connection lost -> keep OFF
#     - no timeout
# STARTING - power, no connection
#          - start - ignored
#          - stop ->STOP_WHEN_CONNECTED
#          - kill - send 4 second signal, check for power down,
#                   on success ->OFF, on failure ->FROZEN
#          - command - prints error
#          - power lost ->OFF
#          - connection appeared ->ON
#          - connection lost ->FROZEN
#          - timeout -> FROZEN
# ON - power, connection
#    - start - ignored
#    - stop - perform shutdown procedure that might be potentially stopped by the client
#             on success ->STOPPING, on failure -> keep ON
#    - kill - send 4 second signal, check for power down,
#             on success ->OFF, on failure -> keep ON
#    - command - ok
#    - power lost ->OFF
#    - connection appeared -> keep ON
#    - connection lost ->FROZEN
#    - no timeout
# STOPPING - power, unsure connection
#          - start ->START_AFTER_STOPPED
#          - stop - ignored
#          - kill - send 4 second signal, check for power down,
#                   on success ->OFF, on failure ->FROZEN
#          - command - print error, except internal commands before connection is closed
#          - power lost ->OFF
#          - connection appeared ->ON
#          - connection lost -> ok
#          - timeout ->FROZEN
# FROZEN - power, undefined connection
#        - power lost ->OFF
#        - start - ignored
#        - stop - ignored
#        - kill - send 4 second signal, check for power down,
#                 on success ->OFF, on failure -> keep FROZEN
#        - connection appeared ->ON
#        - connection lost -> keep FROZEN
#        - no timeout
# START_AFTER_STOPPED - shortly without power, no connection
#                     - must install periodical power checker
#                     - start - ignored
#                     - stop ->STOPPING, stop periodical power checker
#                     - kill - kill procedure, on success ->OFF, on failure ->FROZEN, stop periodical power checker
#                     - command - print error
#                     - power lost -> wait a second, send power signal, stop periodical power checker and ->STARTING
#                     - connection appeared ->ON
#                     - connection lost ->FROZEN
#                     - timeout ->FROZEN
# STOP_AFTER_STARTED - power, shortly connection
#                    - start ->STARTING
#                    - stop - ignored
#                    - kill - usual procedure, on success ->OFF, on failure ->FROZEN
#                    - command - print error
#                    - power lost ->OFF
#                    - connection appeared - send command and ->STOPPING
#                    - connection lost ->FROZEN
#                    - timeout ->FROZEN
#

import argparse
import asyncio
import logging
import logging.handlers
import os
import pickle
import signal
import socket
import sys
import time
import traceback
from pcwaker_common import *
from pcconfig import *


# global variables
terminatingSignalHandled=False
restartFlag=False
shutdownLog=None
pingTask=None


# variables requiring atomic access
# (this includes all access to USB-4761 device,
# all access to mutable computer data in computerList
# and getComputerStatus() function;
# be careful when using await or yield
# to leave data for others in consistent state)
powerInputBits=None
powerOutputBits=0
activeComputerList=[]

# constants
class Status:

	OFF=1
	STARTING=2
	ON=3
	STOPPING=4
	FROZEN=5
	START_AFTER_STOPPED=6
	STOP_AFTER_STARTED=7

	def str(status):
		return _status2string.get(status,"unknown")

_status2string={
	Status.OFF:      "OFF",
	Status.STARTING: "STARTING",
	Status.ON:       "ON",
	Status.STOPPING: "STOPPING",
	Status.FROZEN:   "FROZEN",
	Status.START_AFTER_STOPPED: "START_AFTER_STOPPED",
	Status.STOP_AFTER_STARTED:  "STOP_AFTER_STARTED",
}

class NoRequestedOS:
	name="None"

noRequestedOS=NoRequestedOS



def getComputerStatus(pc,powerInputBits):

	# handle power up and power lost (except OFF and START_AFTER_STOPPED states)
	if pc.status==Status.OFF:
		# OFF: on power ->STARTING
		if powerInputBits&pc.powerBitMask!=0:
			pc.status=Status.STARTING
	elif pc.status==Status.START_AFTER_STOPPED:
		pass # not implemented yet
	else:
		# all remaining states: on power lost ->OFF
		# but ignore computers that have powerBitMask set to zero (no wires to the computer)
		if powerInputBits&pc.powerBitMask==0 and pc.powerBitMask!=0:
			pc.status=Status.OFF
			pc.requestedOS=noRequestedOS

	# status OFF
	if pc.status==Status.OFF:
		pass

	# status STARTING
	elif pc.status==Status.STARTING:
		pass

	# status ON
	elif pc.status==Status.ON:
		if pc.writer==None:
			pc.status=Status.FROZEN

	# status STOPPING
	elif pc.status==Status.STOPPING:
		pass

	# status FROZEN
	elif pc.status==Status.FROZEN:
		pass

	# status START_AFTER_STOPPED
	elif pc.status==Status.START_AFTER_STOPPED:
		pass

	# status STOP_AFTER_STARTED
	elif pc.status==Status.STOP_AFTER_STARTED:
		pass

	return pc.status


async def serverConnectionHandler(reader,writer):

	global powerOutputBits
	wlog=None
	associatedComputer=None
	try:

		# initialize log
		# log messages are sent to two targets: logged in main thread log
		# and sent over command connection back to the client
		wlog=logging.Logger('ConnectionLogger',rootLog.level)
		wlog.parent=rootLog
		wlogHandler=ConnectionLogHandler(writer)
		wlog.addHandler(wlogHandler)
		wlog.debug('Connection handler started.')

		# set keep-alive on socket
		s=writer.get_extra_info('socket')
		if s is None:
			wlog.error('Can not get socket out of writer. Socket TCP keep-alive parameters will not be set.')
		else:
			s.setsockopt(socket.SOL_SOCKET,socket.SO_KEEPALIVE,1)
			s.setsockopt(socket.IPPROTO_TCP,socket.TCP_KEEPIDLE,6)   # six second before keepalive probes
			s.setsockopt(socket.IPPROTO_TCP,socket.TCP_KEEPINTVL,1)  # keepalive probes are sent in 1 second interval
			s.setsockopt(socket.IPPROTO_TCP,socket.TCP_KEEPCNT,4)    # four keepalive probes from 6th to 9th second

		# main loop of the connection
		while not reader.at_eof():

			# receive the messageq
			msgType,message=await stream_read_message(reader)

			# handle closed connection
			if msgType==MSG_EOF:
				if associatedComputer:

					# atomically change computer status
					# (do not put any await and yield calls in this block!)
					# (do not close writer, this will be made on the function exit)
					pc=associatedComputer
					associatedComputer.writer=None
					associatedComputer.reader=None
					associatedComputer=None
					activeComputerList.remove(pc)
					r=dataInput.Read(0,powerInputBits)
					if r!=0: raise OSError(r,'USB-4761 device error (error code: '+hex(r)+').')
					getComputerStatus(pc,powerInputBits.value())

					wlog.info('Computer '+pc.name+' disconnected.')
				break

			# pingHandler scheduled sending of ping
			if msgType==MSG_PING_SCHEDULE:

				# check if previous ping was correctly processed,
				# if not, move to FROZEN state and check power (to move to OFF state)
				if pc.timeOfLastPingAnswer!=pc.timeOfLastPingRequest:

					# close the connection and put computer to FROZEN state
					# (do not put any await and yield calls in this block!)
					pc.status=Status.FROZEN
					pc.writer.close()
					pc.reader.feed_eof()
					r=dataInput.Read(0,powerInputBits)
					if r!=0: raise OSError(r,'USB-4761 device error (error code: '+hex(r)+').')
					getComputerStatus(pc,powerInputBits.value())

					# log connection lost
					log.error(pc.name+': connection lost (ping timeout).')
					break

				# send ping request message
				pc.timeOfLastPingRequest=message
				stream_write_message(writer,MSG_PING_REQUEST,message)

			# peer sent ping request
			elif msgType==MSG_PING_REQUEST:
				stream_write_message(writer,MSG_PING_ANSWER,message)
				continue

			# peer sent ping answer
			elif msgType==MSG_PING_ANSWER:
				associatedComputer.timeOfLastPingAnswer=message
				continue

			# process messages from pcwaker.py
			elif msgType==MSG_USER:

				# decode data
				params=message
				wlog.debug('Message received from pcwaker: '+str(params))

				# ignore empty messages
				if len(params)==0:
					continue

				# daemon stop and restart
				if params[0]=='daemon':

					if len(params)==1:
						wlog.error('Error: Not enough arguments for daemon parameter.')
						continue

					if params[1]=='stop' or params[1]=='restart':
						global restartFlag
						global shutdownLog
						shutdownLog=wlog
						if params[1]=='restart':
							restartFlag=True
							wlog.debug('Scheduled server restart.')
						else:
							wlog.debug('Scheduled server stop.')
						loop.stop()
						continue

					wlog.error('Unknown parameter 1: '+params[1])
					continue

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

					# atomically read computer state and print result
					# (do not put any await and yield calls in this block!)
					r=dataInput.Read(0,powerInputBits)
					if r!=0: raise OSError(r,'USB-4761 device error (error code: '+hex(r)+').')
					if machineReadable:
						for pc in list:
							s=Status.str(getComputerStatus(pc,powerInputBits.value()))
							stream_write_message(writer,MSG_USER,pickle.dumps(s,protocol=2))
					else:
						for pc in list:
							status=getComputerStatus(pc,powerInputBits.value())
							s=Status.str(status)
							wlog.critical('Computer '+pc.name+':')
							wlog.critical('   Status: '+s)
							if status==Status.ON:
								wlog.critical('   OS:     '+pc.currentOS.name)

					continue

				# start computer
				elif params[0]=='start' or params[0]=='restart':
					if len(params)==1:
						wlog.error('Error: No computer specified.')
					else:

						# get computer
						pc=getComputer(params[1])
						if pc==None:
							wlog.critical(params[1]+' is not a configured computer.')
							continue

						# requested OS
						if len(params)>=3:
							pc.requestedOS=getComputerOperatingSystemByName(pc,params[2])
							if pc.requestedOS==None and params[2]!=None and params!='':
								wlog.critical(params[2]+' is not valid operating system for computer '+pc.name)
							if pc.requestedOS==None:
								pc.requestedOS=noRequestedOS
						else:
							pc.requestedOS=noRequestedOS

						# atomically process computer state update
						# (do not put any await or yield calls the following blocks starting from
						# read computer state, through processing all states and finishing by unknown state)

						# read computer state
						r=dataInput.Read(0,powerInputBits)
						if r!=0: raise OSError(r,'USB-4761 device error (error code: '+hex(r)+').')
						status=getComputerStatus(pc,powerInputBits.value())

						# if OFF, activate power signal
						# (the rest will be performed bellow after 0.5s)
						if status==Status.OFF:
							wlog.info('Starting computer '+pc.name+'...')
							powerOutputBits|=pc.powerBitMask
							dataOutput.Write(0,powerOutputBits)

						# in STARTING, do noting,
						# operating system to boot is changed if it was specified
						elif status==Status.STARTING:
							if params[0]=='start':
								wlog.info('Computer '+pc.name+' is already starting.')
							elif params[0]=='restart':
								wlog.info('Computer '+pc.name+' is starting...')

						# in ON, do nothing
						elif status==Status.ON:
							if params[0]=='start':
								wlog.info('Computer '+pc.name+' is already running.')
							elif params[0]=='restart':
								if pc.requestedOS!=noRequestedOS:
									wlog.info('Computer '+pc.name+' restart requested to '+pc.requestedOS.name+' operating system.')
								else:
									wlog.info('Computer '+pc.name+' restart requested without specifying any operating system to boot.')
								if pc.currentOS.name!=pc.bootManagerOS:
									commandList=pc.currentOS.cmdBootToBootManager
									log.info(pc.name+': Running command \"'+' '.join(commandList)+'\" to reboot to bootManager OS.')
									stream_write_message(pc.writer,MSG_COMPUTER,pickle.dumps(['command']+commandList,protocol=2))
								stream_write_message(pc.writer,MSG_COMPUTER,pickle.dumps(['restart'],protocol=2))

						# in STOPPING, move to START_AFTER_STOPPED
						elif status==Status.STOPPING:
							wlog.info('Computer '+pc.name+' is shutting down. It will be started after shutdown.')
							pc.status=Status.START_AFTER_STOPPED
							# activate periodical state checker here

						# in START_AFTER_STOPPED, do nothing
						elif status==Status.START_AFTER_STOPPED:
							wlog.info('Computer '+pc.name+' is shutting down. It will be started after shutdown.')

						# in STOP_AFTER_STARTED, move to STARTING
						elif status==Status.STOP_AFTER_STARTED:
							wlog.info('Computer '+pc.name+' is scheduled to shutdown. Canceling shutdown.')
							pc.status=Status.STARTING
							# deactivate periodical state checker here

						# in FROZEN, do nothing
						elif status==Status.FROZEN:
							wlog.info('Computer '+pc.name+' is not answering and seems to be frozen.\n'
											'   You might try to power it down by kill command or wait some moments\n'
											'   (it might be busy installing updates during shutdown, power up, etc).')

						# unknown state
						else:
							wlog.critical('Computer '+pc.name+' is in unknown state.')

						# if status was originally OFF, deactivate power signal after 0.5 second and re-read computer state
						if status==Status.OFF:
							await asyncio.sleep(0.5)

							# atomically deactivate power signal and update computer state
							# (do not put any await or yield calls in following two code blocks!)

							# if OFF, deactivate power signal after 0.5 second
							powerOutputBits&=~pc.powerBitMask
							dataOutput.Write(0,powerOutputBits)

							# update computer state
							r=dataInput.Read(0,powerInputBits)
							if r!=0: raise OSError(r,'USB-4761 device error (error code: '+hex(r)+').')
							status=getComputerStatus(pc,powerInputBits.value())

							# if still did not came up, give it three times another 0.5 second
							for i in [1,2,3]:
								if status==Status.OFF:
									await asyncio.sleep(0.5)

									# test again if it came up
									r=dataInput.Read(0,powerInputBits)
									if r!=0: raise OSError(r,'USB-4761 device error (error code: '+hex(r)+').')
									status=getComputerStatus(pc,powerInputBits.value())

							# log
							if status==Status.OFF:
								wlog.critical('Failed to start computer '+pc.name+'.')
							elif status==Status.STARTING:
								wlog.critical('Computer '+pc.name+' successfully started.')
							else:
								wlog.critical('Computer '+pc.name+' successfully started (state: '+Status.str(status)+').')

					continue

				# stop computer
				elif params[0]=='stop':
					if len(params)==1:
						wlog.error('Error: No computer(s) specified.')
					else:

						# get computer
						pc=getComputer(params[1])
						if pc==None:
							wlog.critical(params[1]+' is not a configured computer.')
							continue

						# atomically update computer state
						# (do not put any wait and yield calls in following code blocks starting from
						# read computer state, through all state processing, finishing by unknown state)

						# read computer state
						r=dataInput.Read(0,powerInputBits)
						if r!=0: raise OSError(r,'USB-4761 device error (error code: '+hex(r)+').')
						status=getComputerStatus(pc,powerInputBits.value())

						# if OFF, do nothing
						if status==Status.OFF:
							wlog.info('Computer '+pc.name+' is already powered off.')

						# in STARTING, move to STOP_AFTER_STARTED
						elif status==Status.STARTING:
							wlog.info('Computer '+pc.name+' is starting. It will be stopped after booting up.')
							pc.status=Status.STOP_AFTER_STARTED
							pc.requestedOS=noRequestedOS

						# in ON, send shutdown message and move to STOPPING
						elif status==Status.ON:
							wlog.info('Stopping computer '+pc.name+'...')
							stream_write_message(pc.writer,MSG_COMPUTER,pickle.dumps(['shutdown'],protocol=2))
							pc.status=Status.STOPPING

						# in STOPPING, do noting
						elif status==Status.STOPPING:
							wlog.info('Computer '+pc.name+' is already shutting down.')

						# in START_AFTER_STOPPED, move to STOPPING
						elif status==Status.START_AFTER_STOPPED:
							wlog.info('Computer '+pc.name+' is scheduled to start after shutdown. Cancelling start.')
							pc.status=Status.STOPPING
							# deactivate periodical state checker here

						# in STOP_AFTER_STARTED, do noting
						elif status==Status.STOP_AFTER_STARTED:
							wlog.info('Computer '+pc.name+' is already scheduled to shutdown.')

						# in FROZEN, do nothing
						elif status==Status.FROZEN:
							wlog.info('Computer '+pc.name+' is not answering and seems to be frozen.\n'
											'   You might try to power it down by kill command or wait some moments\n'
											'   (it might be busy installing updates during shutdown, power up, etc).')

						# unknown state
						else:
							wlog.critical('Computer '+pc.name+' is in unknown state.')

					continue

				# kill computer - press power button for 4 seconds
				elif params[0]=='kill':
					if len(params)==1:
						wlog.error('Error: No computer specified.')
					else:

						# get computer
						pc=getComputer(params[1])
						if pc==None:
							wlog.critical(params[1]+' is not a configured computer.')
							continue

						# read computer state
						r=dataInput.Read(0,powerInputBits)
						if r!=0: raise OSError(r,'USB-4761 device error (error code: '+hex(r)+').')
						status=getComputerStatus(pc,powerInputBits.value())

						# if OFF, do nothing
						if status==Status.OFF:
							wlog.info('Computer '+pc.name+' is already switched off.')
							continue

						# activate power signal
						wlog.info('Forcefully shutting down computer '+pc.name+'...')
						powerOutputBits|=pc.powerBitMask
						dataOutput.Write(0,powerOutputBits)

						t=0
						while t<5.9: # max 6 seconds before we fail
							await asyncio.sleep(0.5)
							t+=0.5

							# update computer state
							r=dataInput.Read(0,powerInputBits)
							if r!=0: raise OSError(r,'USB-4761 device error (error code: '+hex(r)+').')
							status=getComputerStatus(pc,powerInputBits.value())
							if status==Status.OFF:
								break

						# deactivate power signal
						powerOutputBits&=~pc.powerBitMask
						dataOutput.Write(0,powerOutputBits)

						# update computer state
						r=dataInput.Read(0,powerInputBits)
						if r!=0: raise OSError(r,'USB-4761 device error (error code: '+hex(r)+').')
						status=getComputerStatus(pc,powerInputBits.value())

						# if OFF
						if status==Status.OFF:
							wlog.critical('Computer '+pc.name+' successfully powered off (in {:.1f} seconds).'.format(t))
						else:
							wlog.critical('Failed to forcefully power off computer '+pc.name+'.\n'
							              '   Computer left in the state: '+Status.str(status)+'.')

					continue

				# execute command on computer
				elif params[0]=='command':
					if len(params)==1:
						wlog.error('Error: No computer specified.')
					else:

						# get computer
						pc=getComputer(params[1])
						if pc==None:
							wlog.critical(params[1]+' is not a configured computer.')
							continue

						# read computer state
						r=dataInput.Read(0,powerInputBits)
						if r!=0: raise OSError(r,'USB-4761 device error (error code: '+hex(r)+').')
						status=getComputerStatus(pc,powerInputBits.value())

						# if not ON, print error
						if status!=Status.ON:
							wlog.info('Computer '+pc.name+' is not in ON state (current state: '+Status.str(status)+').')
							continue

						# send the command
						stream_write_message(pc.writer,MSG_COMPUTER,pickle.dumps(['command']+params[2:],protocol=2))

					continue

				# unknown command
				else:
					wlog.error('Unknown command: '+params[0])
				break

			# process messages from client processes on monitored computers
			elif msgType==MSG_COMPUTER:

				# decode data
				params=pickle.loads(message)
				wlog.debug('Message received from computer: '+str(params))

				# ignore empty messages
				if len(params)==0:
					continue

				# Got alive message
				if params[0]=='Got alive':
					if len(params)>=2: computerName=params[1]
					else: computerName=None
					if len(params)>=3: platform=params[2]
					else: platform=None
					if len(params)>=4: partition=params[3]
					else: partition=None
					pc=getComputer(computerName)
					if pc!=None:

						log.info('Computer '+pc.name+' got alive (system: '+platform+', partition: '+partition+').')

						if pc.status!=Status.STOP_AFTER_STARTED:

							# get current operating system
							pc.currentOS=getComputerOperatingSystemByPartition(pc,partition)
							if pc.currentOS==None:
								wlog.error(pc.name+': Unknown current operating system. Please, update pcconfig.py.')
								pc.currentOS=noRequestedOS  # provide some safe value to continue

							if pc.requestedOS!=noRequestedOS and pc.requestedOS.name!=pc.currentOS.name:

								# reboot to requested OS
								if pc.currentOS.name==pc.bootManagerOS:
									log.info(pc.name+': Requested operating system is '+pc.requestedOS.name+'.')
									commandList=pc.requestedOS.cmdBootToThisOne
									log.info(pc.name+': Running command \"'+' '.join(commandList)+'\" to reboot to requested OS.')
									stream_write_message(writer,MSG_COMPUTER,pickle.dumps(['command']+commandList,protocol=2))
									if platform=='win32': commandList=['shutdown','/r','/t','1']
									else: commandList=['/usr/bin/sudo','reboot']
									stream_write_message(writer,MSG_COMPUTER,pickle.dumps(['command']+commandList,protocol=2))

								# reboot to bootManager OS
								else:
									log.info(pc.name+': Requested operating system is '+pc.requestedOS.name+'.')
									commandList=pc.requestedOS.cmdBootToBootManager
									log.info(pc.name+': Running command \"'+' '.join(commandList)+'\" to reboot to bootManager OS.')
									stream_write_message(writer,MSG_COMPUTER,pickle.dumps(['command']+commandList,protocol=2))
									if platform=='win32': commandList=['shutdown','/r','/t','1']
									else: commandList=['/usr/bin/sudo','reboot']
									stream_write_message(writer,MSG_COMPUTER,pickle.dumps(['command']+commandList,protocol=2))

							else:

								# move to ON status
								# (atomically process the following code block, not doing any await or yield calls!)
								log.debug(pc.name+': Booted with the correct OS (current: '+pc.currentOS.name+', requested: '+pc.requestedOS.name+').')
								pc.status=Status.ON
								pc.requestedOS=noRequestedOS
								pc.reader=reader
								pc.writer=writer
								associatedComputer=pc
								activeComputerList.append(pc)
								pc.timeOfLastPingRequest=time.monotonic()
								pc.timeOfLastPingAnswer=pc.timeOfLastPingRequest
								r=dataInput.Read(0,powerInputBits)
								if r!=0: raise OSError(r,'USB-4761 device error (error code: '+hex(r)+').')
								if powerInputBits.value()&pc.powerBitMask==0:
									if pc.powerBitMask!=0:
										wlog.error('Error: Computer '+pc.name+' established connection\n'
										           '   while no power signal is detected. Check your wiring.')
									else:
										wlog.info('Computer '+pc.name+' is not connected by wires to detect its power on/off state.\n'
										          '   The functionality of pcwaker might be limited on this computer.')

						else:
							pass # send stop command here

					else:
						log.critical('Computer '+params[1]+' attempts to announce it is alive,\n'
						             '   but it is not a registered computer.')
						break

				# unknown message
				else:
					wlog.error('Unknown computer message data: '+str(data))

	except (ConnectionResetError,BrokenPipeError) as e:

		# remove sending log over network (connection was reset)
		if wlog:
			wlog.removeHandler(wlogHandler)
			wlogHandler=None

		# log connection reset
		if associatedComputer:
			if type(e)==ConnectionResetError:
				t='Computer '+associatedComputer.name+' connection reset.'
			elif type(e)==BrokenPipeError:
				t='Computer '+associatedComputer.name+' broken pipe.'
			else:
				t='Computer '+associatedComputer.name+' unhandled error.'
		else:
			if type(e)==ConnectionResetError: t='Connection reset.'
			elif type(e)==BrokenPipeError: t='Broken pipe.'
			else: t='Unhandled error.'
		wlog.info(t)

	# all remaining "standard" exceptions
	except Exception as e:
		wlog.critical('\nException raised: '+type(e).__name__+'\n'+
		              traceback.format_exc())

	finally:

		# remove connection from connection list
		# (no await and yield calls in this code block!)
		if reader in activeComputerList:
			activeComputerList.remove(reader)

		# close connection
		# (shutdownLog is not closed, neither its writer; they will be closed when main loop is left)
		wlog.debug('Connection handler cleaning up...')
		if wlog!=shutdownLog and wlog and wlogHandler!=None:
			wlog.removeHandler(wlogHandler)
		if wlog!=shutdownLog or wlog==None:
			writer.close()
		wlog.debug('Connection handler terminated.')


async def pingHandler():

	while True:

		# sleep 10s
		await asyncio.sleep(10)

		# prepare data to send
		data3=pickle.dumps(time.monotonic(),protocol=2)
		data1=struct.pack('!I',MSG_PING_SCHEDULE)
		data2=struct.pack('!I',len(data3))
		message=data1+data2+data3

		# pingHandler scheduled sending of ping
		# (do not use any await or yield calls in this code block!)
		for pc in activeComputerList:

			# only ON computers are processed
			if pc.status!=Status.ON:
				continue

			# feed data to the reader
			pc.reader.feed_data(message)
			continue


def getComputer(name):
	global computerList
	pcList=[x for x in computerList if name in x.names]
	if len(pcList)==0:
		return None
	else:
		return pcList[0]


def getComputerOperatingSystemByName(pc,osName):
	if osName==None:
		return None
	for os in pc.operatingSystems:
		for n in os.names:
			if n.casefold()==osName.casefold():
				return os
	return None


def getComputerOperatingSystemByPartition(pc,partition):
	if partition==None or partition=='':
		return None
	for os in pc.operatingSystems:
		if os.partition==partition:
			return os
	return None


# log handler that sends log messages over the stream back to the client
class ConnectionLogHandler(logging.Handler):

	def __init__(self,writer):
		logging.Handler.__init__(self)
		self.writer=writer

	def emit(self,record):
		# multithreaded lock is in handle() method,
		# thus only single thread may enter this method
		try:
			text=self.format(record)
			stream_write_message(self.writer,MSG_LOG,text)
		except Exception:
			self.handleError(record)


def cleanUp():

	# send log messages to shutdownLog as well
	# (they will be sent over network)
	global log
	global shutdownLog
	if shutdownLog:
		savedParent=log.parent
		log.parent=shutdownLog
		log.debug('Adding network handler to global log')

	# log start clean up
	if 'log' in globals():
		log.debug('Starting clean up...')

	# remove listening port file
	global listeningPortFilePath
	if listeningPortFilePath:
		listeningPortFile.close()
		os.remove(listeningPortFilePath)
		listeningPortFilePath=''

	# close server (and its listening socket)
	if 'server' in globals():
		global server
		server.close()
		log.info('Server stopped.');

		# wait on server closing
		log.debug('Terminating...')
		serverTmp=server
		del server
		loop.run_until_complete(serverTmp.wait_closed())
		del serverTmp

	# dispose USB-4761 IO module
	if 'dataInput' in globals() or 'dataOutput' in globals():
		log.info('Cleaning up USB-4761 IO module...')
	if 'dataInput' in globals():
		global dataInput
		dataInput.Dispose()
		del dataInput
	if 'dataOutput' in globals():
		global dataOutput
		dataOutput.Dispose()
		del dataOutput

	if restartFlag:

		# restart the process
		log.info('Restarting process...')
		p=subprocess.Popen(["./pcwakerd","--init-print-log"],stdout=subprocess.PIPE)

		# write new process output to log
		# (but first remove termintating '\n')
		s=p.stdout.read().decode(errors='replace')
		if len(s)>0 and s[-1]=='\n':
			s=s[:-1]
		log.info(s)

	else:
		if 'log' in globals():
			log.info('Done.')

	# close connection to the client that initiated daemon shut down
	# (we used the connection to forward all log messages)
	if shutdownLog:
		log.parent=savedParent
		for h in shutdownLog.handlers:
			h.writer.close()
			h.close()
		shutdownLog=None

	# perform clean up
	if 'loop' in globals():
		loop.close()
	if 'log' in globals():
		log.debug('Clean up complete.');


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
      log.critical(sigName+' signal received. Terminating...')

      # exit (clean up is performed in finally clauses)
      sys.exit(1)

   else:

      # log message and exit without any clean up
      log.critical('Another terminating signal ('+sigName+') received. Terminating immediately.')
      os._exit(2)


# init argument parser
argParser=argparse.ArgumentParser(description='pcwaker daemon for switching computers on, monitoring '
                                  'them, executing commands on them and safely shutting them down '
                                  'using Advantech USB-4761 device connected to motherboard '
                                  'power switch pins and power LED pins.')
argParser.add_argument('--debug',help='Sets debug level to "debug". '
                                      'Much of internal information will be printed.',
                       action='store_true')
argParser.add_argument('--debug-level',type=str,help='Sets debug level. '
                       'Valid values are debug, info, warning, error, critical.',
                       action='store')
argParser.add_argument('--init-print-log',action='store_true')
argParser.add_argument('--signal-start-to-parent',action='store_true')
args=argParser.parse_args()

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
log.critical('pcwakerd started with arguments: '+str(sys.argv[1:])+
             ' and debug level '+logging.getLevelName(log.level)+'.')

# signal handlers
signal.signal(signal.SIGINT,signalHandler) # Ctrl-C handler
signal.signal(signal.SIGHUP,signalHandler) # hang-up or death of controlling process
signal.signal(signal.SIGTERM,signalHandler) # terminate request

# initialize USB-4761 IO module
log.debug('Initializing USB-4761 IO module...')
try:
	import bdaqctrl
except ImportError as e:
	log.critical('Error: Can not load bdaqctrl module.\n'
	             '   Error string: '+e.msg+'.')
	exit(1)
deviceInformation=bdaqctrl.DeviceInformation('USB-4761,BID#0')
dataInput=bdaqctrl.AdxInstantDiCtrlCreate()
dataOutput=bdaqctrl.AdxInstantDoCtrlCreate()
r1=dataInput.setSelectedDevice(deviceInformation)
r2=dataOutput.setSelectedDevice(deviceInformation)
if(r1!=0 or r2!=0):
	log.critical('Error: Can not connect to USB-4761 device.')
	exit(1)
powerInputBits=bdaqctrl.uint8()
powerOutputBits=0
r1=dataInput.Read(0,powerInputBits)
r2=dataOutput.Write(0,0)
if(r1!=0 or r2!=0):
	log.critical('Error: Can not write to USB-4761 device.')
	exit(1)
log.info('USB-4761 IO module initialized successfully.')

# initialize computers
computerListText=''
runningComputers=''
for pc in computerList:
	pc.status=Status.OFF
	pc.reader=None
	pc.writer=None
	pc.requestedOS=noRequestedOS
	if computerListText=='': computerListText=pc.name
	else: computerListText+=', '+pc.name
	if getComputerStatus(pc,powerInputBits.value())!=Status.OFF:
		if runningComputers=='': runningComputers=pc.name
		else: runningComputers+=', '+pc.name
if computerListText=='': computerListText='none'
if runningComputers=='': runningComputers='none'
log.info('Initializing computers: '+computerListText)
log.info('Currently powered computers: '+runningComputers)
del computerListText
del runningComputers

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

# create listening socket
log.debug('Initializing network:')
loop=asyncio.get_event_loop()
if pcwakerListeningPort!=0:
	coro=asyncio.start_server(serverConnectionHandler,'',pcwakerListeningPort,loop=loop)
else:
	coro=asyncio.start_server(serverConnectionHandler,'127.0.0.1',0,loop=loop)
try:
	server=loop.run_until_complete(coro)
	if server.sockets==None:
		raise OSError(5,"Failed to create listening socket.")
except OSError as msg:
	log.critical('Network error ('+msg.strerror+'). Terminating.')
	cleanUp()
	log.info('Done.')
	sys.exit(1)

# get listening port number
listeningPort4=0
listeningPort6=0
for s in server.sockets:
	if s.family==socket.AF_INET: listeningPort4=s.getsockname()[1]
	if s.family==socket.AF_INET6: listeningPort6=s.getsockname()[1]
if listeningPort4!=listeningPort6 and listeningPort4!=0 and listeningPort6!=0:
	log.critical('Error: Listening on different ports. IPv4: '+str(listeningPort4)+
	             ', IPv6: '+str(listeningPort6)+'.')
listeningPort=0
ipFamilyString=''
if listeningPort4!=0:
	listeningPort=listeningPort4
	ipFamilyString='IPv4'
if listeningPort6!=0:
	if listeningPort==0:
		listeningPort=listeningPort6
	if ipFamilyString=='':
		ipFamilyString='IPv6'
	else:
		ipFamilyString+=' and IPv6'
if listeningPort4!=0 and listeningPort6!=0:
	ipFamilyString+=' ports '
else:
	ipFamilyString+=' port '
if listeningPortFilePath:
	listeningPortFile.write(str(listeningPort))
	listeningPortFile.flush()
log.info('Waiting connections on '+ipFamilyString+str(listeningPort)+'...');

# stop logging to stdout for --init-print-log here
log.info('Server up and running...')
if args.init_print_log:
	rootLog.removeHandler(logStdOutHandler)
	sys.stdout.flush()
	os.close(sys.stdout.fileno())
if args.signal_start_to_parent:
	os.kill(os.getppid(),signal.SIGHUP)

# create ping task
#pingTask=loop.create_task(pingHandler())

# run main loop
try:
	loop.run_forever()
finally:
	log.debug('Mainloop left, entering cleanUp().')
	cleanUp()

log.debug('Calling final exit().')
sys.exit(0)


import subprocess

threadList=[]


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

               ...
               break

            # status of computer(s)
            elif params[0]=='status':

               break

            # start computer
            elif params[0]=='start':
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
                           wlog.critical('Can not stop computer '+pc.name+'. It is not in ON state (currently '+Status.str(status)+').')
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

            ...

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
      # (close of connection terminating pcwakerd is postponed, it will be closed by main thread)
      if wlog!=shutdownLog:
         if self.stream:
            wlog.removeHandler(wlogHandler)
            self.stream.close()

      wlog.debug('Worker thread done.')


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
   p=subprocess.Popen(["./pcwakerd","--init-print-log"],stdout=subprocess.PIPE)

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
