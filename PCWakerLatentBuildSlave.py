import pickle
import socket
import time
from buildbot.buildslave.base import AbstractLatentBuildSlave
from twisted.internet import threads
from pcwaker_common import *
from pcconfig import pcwakerListeningPort

from twisted.python import log


class PCWakerLatentBuildSlave(AbstractLatentBuildSlave):

   def pcwaker_send_single_command(self,args):

      # make connection to the daemon process
      s=socket.socket()
      s.connect(('127.0.0.1',pcwakerListeningPort))
      stream=Stream(s)

      # send command to daemon
      data=pickle.dumps(args,protocol=2)
      stream.send(MSG_WAKER,data)

      # receive and print response
      recvData=b''
      while True:
         msgType,data=stream.recv()
         if msgType==MSG_EOF:
            break
         if msgType==MSG_WAKER:
            recvData+=pickle.loads(data)
         if msgType==MSG_LOG:
            pass

      # finalize application
      stream.close()

      return True,recvData;


   def start_instance(self,build):

      # return deferred
      log.msg('Starting computer '+self.slavename+'.')
      return threads.deferToThread(self._start_instance)

   def _start_instance(self):

      # test for already ON
      command=['status','--machine-readable',self.slavename]
      r,data=self.pcwaker_send_single_command(command)
      if data=='ON':
         return True

      # send start command
      command=['start',self.slavename]
      r,data=self.pcwaker_send_single_command(command)

      # wait for power up (timeout 5s)
      powered=False
      for i in range(0,2*5):
         command=['status','--machine-readable',self.slavename]
         r,data=self.pcwaker_send_single_command(command)
         if data=='Booting':
            powered=True
            break
         time.sleep(0.5)
      if not powered:
         log.msg('Computer '+self.slavename+' failed to power up.')
         return False

      # wait for the machine to boot (timeout 180s)
      for i in range(0,2*180):
         command=['status','--machine-readable',self.slavename]
         r,data=self.pcwaker_send_single_command(command)
         if data=='ON':

            # print success
            log.msg('Computer '+self.slavename+' started.')

            # start buildslave
            command=['command',self.slavename,'buildslave','start','/cygdrive/c/buildbot-slave']
            self.pcwaker_send_single_command(command)

            # return success
            return True

         time.sleep(0.5)

      # machine did not came on-line in time
      log.msg('Computer '+self.slavename+' powered up but failed to boot or connect to the buildbot machine.')
      return False

   def stop_instance(self,fast=False):

      # return deferred
      log.msg('Stopping computer '+self.slavename+'.')
      return threads.deferToThread(self._stop_instance,fast)

   def _stop_instance(self,fast):

      command=['command',self.slavename,'/usr/bin/buildslave','stop']
      self.pcwaker_send_single_command(command)
      command=['stop',self.slavename]
      self.pcwaker_send_single_command(command)
      log.msg('Stopped computer '+self.slavename+'.')
      return True
