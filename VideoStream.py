class VideoStream:
	def __init__(self, filename):
		self.filename = filename
		try:
			self.file = open(filename, 'rb')
		except:
			raise IOError
		self.frameNum = 0
		self.currentPos = 0
		
		# Bổ sung tự động phát hiện format
		self.buffer = b''
		current_pos = self.file.tell()
		first_byte = self.file.read(1)
		self.file.seek(current_pos)
		
		# Nếu byte đầu là số
		if first_byte and first_byte.isdigit():
			self.mode = 'custom'  # Định dạng cũ: 5 byte độ dài + frame
		else:
			self.mode = 'standard'  # Định dạng MJPEG chuẩn (các file JPEG nối tiếp)
		
	def nextFrame(self):
		"""Get next frame."""
		if self.mode == 'custom':
			return self.nextFrameWithLength()
		else:
			return self.nextFrameRawMjpeg()
	
	def nextFrameWithLength(self):
		"""Get next frame with 5-byte length header format."""
		data = self.file.read(5)
		if data: 
			framelength = int(data)
			# Read the current frame
			data = self.file.read(framelength)
			self.frameNum += 1
		return data
	
	# Đọc liên tục file vào buffer cho đến khi tìm thấy một khung hình JPEG trọn vẹn
	def nextFrameRawMjpeg(self):
		"""Get next frame from raw MJPEG stream (JPEG frames back-to-back)."""
		while True:
				start_idx = self.buffer.find(b'\xff\xd8')
				end_idx = self.buffer.find(b'\xff\xd9', start_idx)
				if start_idx != -1 and end_idx != -1:
					frame = self.buffer[start_idx: end_idx + 2]
					self.buffer = self.buffer[end_idx + 2:]

					self.frameNum += 1
					return frame

				# Nếu chưa đủ dữ liệu, đọc thêm từ file (đọc chunk 4KB hoặc 40KB)
				chunk = self.file.read(40960)
				if not chunk:
					return None

				self.buffer += chunk
					
	def countFrames(self):
		"""Count total frames in the video file."""
		# Lưu vị trí hiện tại
		current_pos = self.file.tell()
		self.file.seek(0)	
		count = 0

		if self.mode == 'custom':
			# Cách đếm cho Custom Format (Length Header)
			while True:
				data = self.file.read(5)
				if data:
					try:
						framelength = int(data)
						self.file.seek(framelength, 1) # Nhảy cóc qua frame data
						count += 1
					except ValueError:
						break
				else:
					break
		else:
			# Video độ phân giải cao (FHD) thường chứa các ảnh JPEG có kèm Thumbnail (ảnh nhỏ) hoặc metadata (Exif) bên trong.
			# Sửa thành Logic "tìm cặp mở-đóng" (Start-End) để loại bỏ rác/thumbnail.
			content = self.file.read()
			pos = 0
			while True:
				start_idx = content.find(b'\xff\xd8', pos)
				if start_idx == -1:
					break

				end_idx = content.find(b'\xff\xd9', start_idx)
				if end_idx == -1:
					break

				count += 1
				pos = end_idx + 2
		# Trả về vị trí cũ để không ảnh hưởng luồng phát
		self.file.seek(current_pos)
		return count	
	
	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum
	
	