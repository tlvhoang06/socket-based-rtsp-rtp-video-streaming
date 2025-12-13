from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os

from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"

# Kích thước cố định cho hiển thị (HD: 1280x720)
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 720

class Client:
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT
	
	SETUP = 0
	PLAY = 1
	PAUSE = 2
	TEARDOWN = 3
	
	# Initiation..
	def __init__(self, master, serveraddr, serverport, rtpport, filename):
		self.master = master
		self.master.protocol("WM_DELETE_WINDOW", self.handler)
		self.createWidgets()
		self.serverAddr = serveraddr
		self.serverPort = int(serverport)
		self.rtpPort = int(rtpport)
		self.fileName = filename
		self.rtspSeq = 0
		self.sessionId = 0
		self.requestSent = -1
		self.teardownAcked = 0
		
		# Sửa lỗi: Khởi tạo socket và bỏ kết nối tự động
		# self.connectToServer() # Chú thích: Bỏ kết nối tự động khi khởi tạo Client
		self.rtspSocket = None # Khởi tạo biến
		
		self.frameNbr = 0
		
		# THÊM: Biến buffer để ghép nối các mảnh gói tin RTP
		self.frameBuffer = b''
		
	def createWidgets(self):
		"""Build GUI."""
		# Create Setup button
		self.setup = Button(self.master, width=20, padx=3, pady=3)
		self.setup["text"] = "Setup"
		self.setup["command"] = self.setupMovie
		self.setup.grid(row=1, column=0, padx=2, pady=2)
		
		# Create Play button 		
		self.start = Button(self.master, width=20, padx=3, pady=3)
		self.start["text"] = "Play"
		self.start["command"] = self.playMovie
		self.start.grid(row=1, column=1, padx=2, pady=2)
		
		# Create Pause button 			
		self.pause = Button(self.master, width=20, padx=3, pady=3)
		self.pause["text"] = "Pause"
		self.pause["command"] = self.pauseMovie
		self.pause.grid(row=1, column=2, padx=2, pady=2)
		
		# Create Teardown button
		self.teardown = Button(self.master, width=20, padx=3, pady=3)
		self.teardown["text"] = "Teardown"
		self.teardown["command"] = 	self.exitClient
		self.teardown.grid(row=1, column=3, padx=2, pady=2)
		
		# Create a label to display the movie
		# Sửa lỗi: Cấu hình kích thước label cố định cho hiển thị HD
		self.label = Label(self.master, height=int(IMAGE_HEIGHT / 20), width=int(IMAGE_WIDTH / 20)) # Kích thước tạm thời
		self.label.grid(row=0, column=0, columnspan=4, sticky=W+E+N+S, padx=5, pady=5) 
	
	def setupMovie(self):
		"""Setup button handler."""
		if self.state == self.INIT:
			self.connectToServer() # Kết nối khi nhấn Setup
			self.sendRtspRequest(self.SETUP)
	
	def exitClient(self):
		"""Teardown button handler."""
		self.sendRtspRequest(self.TEARDOWN) 		
		self.master.destroy() # Close the gui window
		try:
			# Xử lý ngoại lệ nếu file cache chưa được tạo
			os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT) # Delete the cache image from video
		except:
			pass

	def pauseMovie(self):
		"""Pause button handler."""
		if self.state == self.PLAYING:
			self.sendRtspRequest(self.PAUSE)
	
	def playMovie(self):
		"""Play button handler."""
		if self.state == self.READY:
			self.frameBuffer = b''
			self.frameNbr = 0
			self.sendRtspRequest(self.PLAY)
	
	def listenRtp(self): 		
		"""Listen for RTP packets, including reassembly logic."""
		while True:
			try:
				# Nhận gói tin với buffer lớn hơn
				data = self.rtpSocket.recv(65536)

				if not data:
					continue
				if self.state != self.PLAYING:
					continue

				rtpPacket = RtpPacket()
				rtpPacket.decode(data)
					
				currFrameNbr = rtpPacket.seqNum()
					
				# Chỉ xử lý các gói tin có thứ tự lớn hơn hoặc bằng gói tin đã nhận cuối cùng
				if currFrameNbr >= self.frameNbr: 
						
					# THÊM PAYLOAD VÀO BUFFER
					self.frameBuffer += rtpPacket.getPayload()
						
					# KIỂM TRA MARKER BIT: Nếu Marker bit = 1, đây là gói tin cuối cùng của Frame
					if rtpPacket.marker() == 1:
							
						# 1. Cập nhật Frame Number
						self.frameNbr = currFrameNbr
							
						# 2. Ghi Frame hoàn chỉnh và Hiển thị
						# self.frameBuffer chứa Frame JPEG hoàn chỉnh đã được ghép nối
						self.updateMovie(self.writeFrame(self.frameBuffer))
							
						# 3. Reset buffer cho Frame tiếp theo
						self.frameBuffer = b''
								
			except:
				
				if self.teardownAcked == 1:
					if self.rtpSocket:
						self.rtpSocket.shutdown(socket.SHUT_RDWR)
						self.rtpSocket.close()
					break
				
				# Xử lý timeout, không cần in lỗi nếu đây chỉ là hết thời gian chờ
					
	def writeFrame(self, data):
		"""Write the received frame to a temp image file. Return the image file."""
		cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
		file = open(cachename, "wb")
		file.write(data)
		file.close()
		
		return cachename
	
	def updateMovie(self, imageFile):
		"""Update the image file as video frame in the GUI."""
		# Bổ sung xử lý lỗi nếu file cache bị ghi lỗi (payload bị hỏng)
		try:
			img = Image.open(imageFile)
		except Exception as e:
			# print(f"Error opening image file: {e}")
			return
			
		# Resize và căn giữa ảnh (Đã sửa để dùng hằng số)
		img.thumbnail((IMAGE_WIDTH, IMAGE_HEIGHT), Image.Resampling.LANCZOS)
		
		# Tạo ảnh nền cố định (1280x720)
		display_size = (IMAGE_WIDTH, IMAGE_HEIGHT)
		centered_img = Image.new('RGB', display_size, color='black') # Dùng nền đen
		
		# Tính toán vị trí để căn giữa
		paste_x = (display_size[0] - img.width) // 2
		paste_y = (display_size[1] - img.height) // 2
		centered_img.paste(img, (paste_x, paste_y))
		
		photo = ImageTk.PhotoImage(centered_img)
		self.label.configure(image = photo, width=IMAGE_WIDTH, height=IMAGE_HEIGHT) 
		self.label.image = photo
		
	def connectToServer(self):
		"""Connect to the Server. Start a new RTSP/TCP session."""
		self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			self.rtspSocket.connect((self.serverAddr, self.serverPort))
		except:
			messagebox.showwarning('Connection Failed', 'Connection to \'%s\' failed. Please ensure the Server is running.' %self.serverAddr)
			sys.exit(0) # Thoát nếu kết nối thất bại
	
	def sendRtspRequest(self, requestCode):
		"""Send RTSP request to the server.""" 	
		#-------------
		# TO COMPLETE
		#-------------
		
		# Setup request
		if requestCode == self.SETUP and self.state == self.INIT:
			# Gửi yêu cầu và khởi động luồng nhận phản hồi
			threading.Thread(target=self.recvRtspReply).start()
			# Update RTSP sequence number.
			self.rtspSeq += 1

			# Write the RTSP request to be sent.
			request = ("SETUP " + self.fileName + " RTSP/1.0\n"
						+ "CSeq: " + str(self.rtspSeq) + "\n"
						+ "Transport: RTP/UDP; client_port=" + str(self.rtpPort) + "\n"
						+ "\n"
						)
			# Keep track of the sent request.
			self.requestSent = self.SETUP
		
		# Play request
		elif requestCode == self.PLAY and self.state == self.READY:
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			request = ("PLAY " + self.fileName + " RTSP/1.0\n"
						+ "CSeq: " + str(self.rtspSeq) + "\n"
						+ "Session: " + str(self.sessionId) + "\n"
						+ "\n"
						)
			# Keep track of the sent request.
			self.requestSent = self.PLAY
		
		# Pause request
		elif requestCode == self.PAUSE and self.state == self.PLAYING:
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			request = ("PAUSE " + self.fileName + " RTSP/1.0\n"
						+ "CSeq: " + str(self.rtspSeq) + "\n"
						+ "Session: " + str(self.sessionId) + "\n"
						+ "\n"
						)
			# Keep track of the sent request.
			self.requestSent = self.PAUSE
			
		# Teardown request
		elif requestCode == self.TEARDOWN and not self.state == self.INIT:
			# Update RTSP sequence number.
			self.rtspSeq += 1
			
			# Write the RTSP request to be sent.
			request = ("TEARDOWN " + self.fileName + " RTSP/1.0\n"
						+ "CSeq: " + str(self.rtspSeq) + "\n"
						+ "Session: " + str(self.sessionId) + "\n"
						+ "\n"
						)
			# Keep track of the sent request.
			self.requestSent = self.TEARDOWN
		else:
			return
		
		# Send the RTSP request using rtspSocket.
		if self.rtspSocket:
			try:
				self.rtspSocket.send(request.encode('utf-8'))
			except Exception as e:
				# print(f"Error sending RTSP request: {e}")
				messagebox.showerror('Network Error', 'Failed to send RTSP request. Server connection lost.')
		else:
			# print("RTSP Socket not established.")
			pass
	
	def recvRtspReply(self):
		"""Receive RTSP reply from the server."""
		while True:
			try:
				reply = self.rtspSocket.recv(1024)
				
				if reply: 
					self.parseRtspReply(reply.decode("utf-8"))
				
				# Close the RTSP socket upon requesting Teardown
				if self.requestSent == self.TEARDOWN:
					if self.rtspSocket:
						self.rtspSocket.shutdown(socket.SHUT_RDWR)
						self.rtspSocket.close()
					break
			except Exception as e:
				# Xử lý lỗi khi socket bị đóng đột ngột
				if self.requestSent != self.TEARDOWN:
					# print(f"RTSP Socket Error/Closed unexpectedly: {e}")
					pass
				break
	
	def parseRtspReply(self, data):
		"""Parse the RTSP reply from the server."""
		lines = data.split('\n')
		# Kiểm tra xem có đủ dòng hay không trước khi truy cập
		if len(lines) < 3: return
		
		try:
			seqNum = int(lines[1].split(' ')[1])
		except ValueError:
			# print(f"Could not parse sequence number from reply: {lines[1]}")
			return
		
		# Process only if the server reply's sequence number is the same as the request's
		if seqNum == self.rtspSeq:
			try:
				session = int(lines[2].split(' ')[1])
			except ValueError:
				# print(f"Could not parse session ID from reply: {lines[2]}")
				return
			
			# New RTSP session ID
			if self.sessionId == 0:
				self.sessionId = session
			
			# Process only if the session ID is the same
			if self.sessionId == session:
				try:
					status_code = int(lines[0].split(' ')[1])
				except ValueError:
					# print(f"Could not parse status code from reply: {lines[0]}")
					return

				if status_code == 200: 
					if self.requestSent == self.SETUP:
						
						# Update RTSP state.
						self.state = self.READY
						
						# Open RTP port.
						self.openRtpPort() 
						# tạo event & thread listenRtp 1 lần duy nhất   
						threading.Thread(
							target=self.listenRtp,
							daemon=True
						).start()
					elif self.requestSent == self.PLAY:
						self.state = self.PLAYING
					elif self.requestSent == self.PAUSE:
						self.state = self.READY
						
					elif self.requestSent == self.TEARDOWN:
						self.state = self.INIT
						
						# Flag the teardownAcked to close the socket.
						self.teardownAcked = 1 
				else:
					messagebox.showwarning('RTSP Error', f'Server replied with status code {status_code}')

	def openRtpPort(self):
		"""Open RTP socket binded to a specified port."""
		#-------------
		# TO COMPLETE
		#-------------
		# Create a new datagram socket to receive RTP packets from the server
		self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		
		# Tăng kích thước buffer socket cho Frame HD
		self.rtpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 655360) 
		
		# Set the timeout value of the socket to 0.5sec
		self.rtpSocket.settimeout(0.5)
		
		try:
			# Bind the socket to the address using the RTP port given by the client user
			self.rtpSocket.bind(('', self.rtpPort)) 
		except Exception as e:
			messagebox.showwarning('Unable to Bind', 'Unable to bind PORT=%d. Check if port is in use.' %self.rtpPort)
			# print(f"Binding Error: {e}")
			sys.exit(0) # Thoát nếu không bind được

	def handler(self):
		"""Handler on explicitly closing the GUI window."""
		self.pauseMovie()
		if messagebox.askokcancel("Quit?", "Are you sure you want to quit?"):
			self.exitClient()
		else: # When the user presses cancel, resume playing.
			self.playMovie()