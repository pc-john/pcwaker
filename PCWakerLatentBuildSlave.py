import pickle
import socket
from buildbot.buildslave.base import AbstractLatentBuildSlave
from pcwaker_common import *
from pcconfig import pcwakerListeningPort


class PCWakerLatentBuildSlave(AbstractLatentBuildSlave):

   def pcwaker_send_single_command(self,args):

      # make connection to the daemon process
      s=socket.socket()
      s.connect(('127.0.0.1',pcwakerListeningPort))
      stream=Stream(s)

      # send command to daemon
      data=pickle.dumps(args)
      stream.send(MSG_WAKER,data)

      # receive and print response
      while True:
         msgType,data=stream.recv()
         if msgType==MSG_EOF:
            break;
         if msgType==MSG_LOG:
            pass #print(data.decode(errors='replace'),end='')

      # finalize application
      stream.close()

      return True;


   def start_instance(self,build):

      args=['start',self.slavename]
      self.pcwaker_send_single_command(args)


   def stop_instance(self,fast=False):

      args=['stop',self.slavename]
      self.pcwaker_send_single_command(args)
