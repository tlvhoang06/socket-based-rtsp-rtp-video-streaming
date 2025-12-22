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
					# Đếm tổng frame cho thanh nền của progress bar
					total_frames = self.clientInfo['videoStream'].countFrames()
				except IOError:
					self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
				
				# Generate a randomized RTSP session ID
				self.clientInfo['session'] = randint(100000, 999999)

				# Gửi kèm thông tin Total-Frames trong header phản hồi
				extra_header = 'Total-Frames: ' + str(total_frames)

				# Send RTSP reply
				self.replyRtsp(self.OK_200, seq[1], extra_header)

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
			
			# Tạo luồng gửi RTP riêng biệt
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
					
					# Giao thức UDP có giới hạn kích thước gói tin (MTU - Maximum Transmission Unit).
					# Nếu gửi 1 frame ảnh lớn (>65KB) sẽ bị lỗi hoặc bị router chặn.
					# Giải pháp: Chia nhỏ frame thành các đoạn payload nhỏ hơn (1400 bytes).
					# UDP datagram limit: thường là 65535 bytes max, nhưng limit thực tế khoảng 1472 bytes

					PAYLOAD_SIZE = 1400
					
					# Gửi frame theo chunks
					num_chunks = (len(data) + PAYLOAD_SIZE - 1) // PAYLOAD_SIZE
					for chunk_idx in range(num_chunks):
						start = chunk_idx * PAYLOAD_SIZE
						end = min(start + PAYLOAD_SIZE, len(data))
						chunk = data[start:end]

						# Kiểm tra xem đây có phải là mảnh cuối cùng của frame không?
						# Nếu đúng, set Marker bit = 1 để Client biết là đã nhận đủ frame.
						is_last_chunk = (chunk_idx == num_chunks - 1)

						packet = self.makeRtp(chunk, seq_number, is_last_chunk)
						self.clientInfo['rtpSocket'].sendto(packet, (address, port))

						# Sequence Number là số 16-bit, cần quay vòng về 0 khi vượt quá 65535
						seq_number = (seq_number + 1) % 65536
						
				except Exception as e:
					print(f"Connection Error: {e}")

			# Điều khiển tốc độ gửi (Congestion Control đơn giản)
			time.sleep(0.05)

	def makeRtp(self, payload, seqnum, is_marker=False):
		"""RTP-packetize the video data."""
		version = 2
		padding = 0
		extension = 0
		cc = 0
		marker = 1 if is_marker else 0 # Bit Marker quan trọng để đánh dấu kết thúc Frame
		pt = 26 # MJPEG payload type
		ssrc = 0 
		
		rtpPacket = RtpPacket()
		
		rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload)
		
		return rtpPacket.getPacket()
		
	def replyRtsp(self, code, seq, extra_data = None): # Thêm 1 parameter (để truyền vào total frames)
		"""Send RTSP reply to the client."""
		if code == self.OK_200:
			reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + str(self.clientInfo['session'])
			if extra_data: # Nếu có dữ liệu
				reply += '\n' + extra_data
			connSocket = self.clientInfo['rtspSocket'][0]
			connSocket.send(reply.encode())
		
		# Error messages
		elif code == self.FILE_NOT_FOUND_404:
			print("404 NOT FOUND")
		elif code == self.CON_ERR_500:
			print("500 CONNECTION ERROR")
