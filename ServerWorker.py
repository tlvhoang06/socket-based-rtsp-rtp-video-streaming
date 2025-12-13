from random import randint
import sys, traceback, threading, socket, time

from VideoStream import VideoStream
from RtpPacket import RtpPacket

class ServerWorker:
	SETUP = 'SETUP'
	PLAY = 'PLAY'
	PAUSE = 'PAUSE'
	TEARDOWN = 'TEARDOWN'
	
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT

	OK_200 = 0
	FILE_NOT_FOUND_404 = 1
	CON_ERR_500 = 2
	
	clientInfo = {}
	
	def __init__(self, clientInfo):
		self.clientInfo = clientInfo
		# Extract client IP address from RTSP connection
		self.clientInfo['clientAddr'] = self.clientInfo['rtspSocket'][1][0]
		print(f"[INFO] Client connected from {self.clientInfo['clientAddr']}")
		
	def run(self):
		threading.Thread(target=self.recvRtspRequest).start()
	
	def recvRtspRequest(self):
		"""Receive RTSP request from the client."""
		connSocket = self.clientInfo['rtspSocket'][0]
		while True:            
			data = connSocket.recv(256)
			if data:
				print("Data received:\n" + data.decode("utf-8"))
				self.processRtspRequest(data.decode("utf-8"))
	
	def processRtspRequest(self, data):
		"""Process RTSP request sent from the client."""
		# Get the request type
		request = data.split('\n')
		line1 = request[0].split(' ')
		requestType = line1[0]
		
		# Get the media file name
		filename = line1[1]
		
		# Get the RTSP sequence number 
		seq = request[1].split(' ')
		
		# Process SETUP request
		if requestType == self.SETUP:
			if self.state == self.INIT:
				# Update state
				print("processing SETUP\n")
				
				try:
					self.clientInfo['videoStream'] = VideoStream(filename)
					self.state = self.READY
				except IOError:
					self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
				
				# Generate a randomized RTSP session ID
				self.clientInfo['session'] = randint(100000, 999999)
				
				# Send RTSP reply
				self.replyRtsp(self.OK_200, seq[1])
				
				# Get the RTP/UDP port from the last line
				self.clientInfo['rtpPort'] = request[2].split('=')[1]
		
		# Process PLAY request 		
		elif requestType == self.PLAY:
			print("processing PLAY\n")

			self.state = self.PLAYING

			self.clientInfo['event'] = threading.Event()   #Reset event
			self.clientInfo['event'].clear()

			if "rtpSocket" not in self.clientInfo:
				self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #Create a new socket for RTP/UDP

			self.replyRtsp(self.OK_200, seq[1])

			self.clientInfo['worker'] = threading.Thread(
				target=self.sendRtp,
				daemon=True
			)
			self.clientInfo['worker'].start()
		
		# Process PAUSE request
		elif requestType == self.PAUSE:
			if self.state == self.PLAYING:
				print("processing PAUSE\n")
				self.state = self.READY
				
				self.clientInfo['event'].set()
			
				self.replyRtsp(self.OK_200, seq[1])
		
		# Process TEARDOWN request
		elif requestType == self.TEARDOWN:
			print("processing TEARDOWN\n")

			self.clientInfo['event'].set()
			
			self.replyRtsp(self.OK_200, seq[1])
			
			# Close the RTP socket
			self.clientInfo['rtpSocket'].close()
			
	def sendRtp(self):
		"""Send RTP packets over UDP."""
		print("[RTP] sendRtp thread started")
		seq_number = 0  # RTP sequence number (increments for each packet)
		while True:
			
			# Stop sending if request is PAUSE or TEARDOWN
			if self.clientInfo['event'].isSet():
				print("[RTP] sendRtp stopped")
				break 
				
			data = self.clientInfo['videoStream'].nextFrame()
			if data: 
				try:
					address = self.clientInfo['clientAddr']
					port = int(self.clientInfo['rtpPort'])
					
					# UDP datagram limit: typically 65535 bytes max, but practical limit is around 1472 bytes
					# Fragment large frames into multiple RTP packets
					PAYLOAD_SIZE = 1400  # Leave room for RTP header (12 bytes) and IP/UDP headers
					
					# Send frame in chunks
					num_chunks = (len(data) + PAYLOAD_SIZE - 1) // PAYLOAD_SIZE
					for chunk_idx in range(num_chunks):
						start = chunk_idx * PAYLOAD_SIZE
						end = min(start + PAYLOAD_SIZE, len(data))
						chunk = data[start:end]
						# Set marker bit (1) on the last packet of the frame
						is_last_chunk = (chunk_idx == num_chunks - 1)
						packet = self.makeRtp(chunk, seq_number, is_last_chunk)
						self.clientInfo['rtpSocket'].sendto(packet, (address, port))
						seq_number = (seq_number + 1) % 65536  # Wrap around 16-bit counter
						
				except Exception as e:
					print(f"Connection Error: {e}")
					#print('-'*60)
					#traceback.print_exc(file=sys.stdout)
					#print('-'*60)
			time.sleep(0.05)

	def makeRtp(self, payload, seqnum, is_marker=False):
		"""RTP-packetize the video data."""
		version = 2
		padding = 0
		extension = 0
		cc = 0
		marker = 1 if is_marker else 0  # Set marker on last packet of frame
		pt = 26 # MJPEG type
		ssrc = 0 
		
		rtpPacket = RtpPacket()
		
		rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload)
		
		return rtpPacket.getPacket()
		
	def replyRtsp(self, code, seq):
		"""Send RTSP reply to the client."""
		if code == self.OK_200:
			#print("200 OK")
			reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + str(self.clientInfo['session'])
			connSocket = self.clientInfo['rtspSocket'][0]
			connSocket.send(reply.encode())
		
		# Error messages
		elif code == self.FILE_NOT_FOUND_404:
			print("404 NOT FOUND")
		elif code == self.CON_ERR_500:
			print("500 CONNECTION ERROR")
