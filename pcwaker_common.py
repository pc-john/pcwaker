import pickle
import select
import struct


# file paths of server process
listeningPortFilePath=''
logFilePath='/data/RaspberryPi/pcwaker/pcwakerd.log'

# message ids used for stream message content identification
MSG_EOF=0          # opposite side closed the stream and will only receive until we sent EOF as well
MSG_LOG=1          # log messages that could be printed on the screen for the user or ignored
MSG_USER=2         # messages exchanged between pcwaker.py (user interacting utility) and pcwakerd.py (daemon)
MSG_COMPUTER=3     # messages exchanged bettwen pcwaker_client.py (client computer) and pcwakerd.py (daemon)


def stream_write_message(writer,msgType,message):
	data=pickle.dumps(message,protocol=2)
	writer.write(struct.pack('!I',msgType))
	writer.write(struct.pack('!I',len(data)))
	writer.write(data)


async def stream_read_message(reader):

	# read msgType
	data=await reader.read(4)
	if len(data)!=4:
		if len(data)==0 and reader.at_eof(): return MSG_EOF,b''
		raise OSError(84,'Illegal byte sequence.')
	msgType,=struct.unpack_from('!I',data,0)

	# read msgSize
	data=await reader.read(4)
	if len(data)!=4: raise OSError(84,'Illegal byte sequence.')
	msgSize,=struct.unpack_from('!I',data,0)

	# read message
	data=await reader.read(msgSize)
	if len(data)!=msgSize: OSError(84,'Illegal byte sequence.')
	message=pickle.loads(data)
	return msgType,message
