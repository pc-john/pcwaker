import select
import struct


# file paths of server process
listeningPortFilePath=''
logFilePath='/buildbot-master/pcwakerd.log'

# message ids used for stream message content identification
MSG_EOF=0
MSG_LOG=1
MSG_WAKER=2
MSG_COMPUTER=3



class Stream:

   MSG_EOF=0

   def __init__(self,socket):
      self.socket=socket
      self.recvShutdown=False
      self.sendShutdown=False
      self.sendBuffer=b''
      self.recvBuffer=b''
      self.msgType=-1
      self.msgSize=0
      self.msgHeaderPos=0
      self.data=b''

   def close(self):
      if len(self.sendBuffer)>0:
         self.socket.sendall(self.sendBuffer)
         self.sendBuffer=b''
      self.socket.close()

   def send(self,msgType,data):
      if self.sendShutdown:
         return
      self.sendBuffer+=(b''+struct.pack('!I',msgType)+  # message type
                            struct.pack('!I',len(data))+  # length (in bytes) of text buffer
                            data)  # data to send
      self.doSend()

   def doSend(self):
      if self.sendShutdown:
         return False
      if len(self.sendBuffer)==0:
         return True
      try:
         bytesSent=self.socket.send(self.sendBuffer)
      except (BrokenPipeError,ConnectionResetError):
         self.sendShutdown=True
         self.sendBuffer=b''
         return False
      if bytesSent>0:
         self.sendBuffer=self.sendBuffer[bytesSent:]
      return True

   def recv(self,timeout=None):

      # handle unsend data
      if len(self.sendBuffer)>0:
         _,wlist,_=select.select([],[self.socket],[],0.)
         if len(wlist)>0:
            doSend()

      # select
      if timeout==None:
         rlist,wlist,xlist=select.select([self.socket],
                                         [self.socket] if len(self.sendBuffer)>0 else [],
                                         [self.socket])
      else:
         rlist,wlist,xlist=select.select([self.socket],
                                         [self.socket] if len(self.sendBuffer)>0 else [],
                                         [self.socket],timeout)

      # handle unsend data
      if len(wlist)>0:
         doSend()

      # read data
      if len(rlist)>0:

         try:

            # read message header
            if self.msgHeaderPos<8:
               l1=len(self.data)
               self.data+=self.socket.recv(8-self.msgHeaderPos)
               l2=len(self.data)
               if l2==8:
                  # header received
                  self.msgType,=struct.unpack_from('!I',self.data,0)
                  self.msgSize,=struct.unpack_from('!I',self.data,4)
                  self.msgHeaderPos=8
                  self.data=b''
               else:
                  if l2!=l1:
                     self.msgHeaderPos+=l2-l1
                  else:
                     # EOF received (e.g. socket closed: zero bytes received while select indicated some data)
                     self.recvShutdown=True
                     return Stream.MSG_EOF,None

            # read message body
            if self.msgHeaderPos==8:
               l1=len(self.data)
               self.data+=self.socket.recv(self.msgSize-len(self.data))
               l2=len(self.data)
               if l2==self.msgSize:
                  # all message data was received
                  r=(self.msgType,self.data)
                  self.msgHeaderPos=0
                  self.data=b''
                  return r
               if l2!=l1:
                  # some more data was received
                  pass
               else:
                  # EOF received (e.g. socket closed: zero bytes received while select indicated some data)
                  self.recvShutdown=True
                  return Stream.MSG_EOF,None

         except ConnectionResetError:
            recvShutdown=True
            recvBuffer=''
            return Stream.MSG_EOF,None

      # exception on the socket
      if len(xlist)==1:
         return Stream.MSG_EOF,None

      # timeout expired
      return None,None
