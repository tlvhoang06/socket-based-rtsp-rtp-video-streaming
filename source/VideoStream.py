class VideoStream:
	def __init__(self, filename):
		self.filename = filename
		try:
			self.file = open(filename, 'rb')
		except:
			raise IOError
		self.frameNum = 0
		self.currentPos = 0
		
		# Tự động phát hiện format file
		self.buffer = b''
		current_pos = self.file.tell()
		first_byte = self.file.read(1)
		self.file.seek(current_pos)
		
		# Nếu byte đầu là ký tự số -> Định dạng cũ (Custom Format với header độ dài 5 byte)
		if first_byte and first_byte.isdigit():
			self.mode = 'custom'  # Định dạng cũ: 5 byte độ dài + frame
		else:
			self.mode = 'standard'  # Định dạng MJPEG chuẩn (các ảnh JPEG nối tiếp nhau)
		
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
				# 0xFFD8 là Start of Image (SOI)
				start_idx = self.buffer.find(b'\xff\xd8')

				# 0xFFD9 là End of Image (EOI)
				end_idx = self.buffer.find(b'\xff\xd9', start_idx)

				if start_idx != -1 and end_idx != -1:
					# Cắt dữ liệu từ SOI đến EOI để được 1 frame hoàn chỉnh
					frame = self.buffer[start_idx: end_idx + 2]

					# Cập nhật lại buffer: Loại bỏ frame đã lấy, giữ lại phần dư (nếu có)
					self.buffer = self.buffer[end_idx + 2:]

					self.frameNum += 1
					return frame

				# Nếu chưa tìm thấy đủ cặp SOI/EOI, đọc thêm dữ liệu từ file vào buffer
				# Đọc theo chunk (40KB) để tối ưu
				chunk = self.file.read(40960)
				if not chunk: # Hết File
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
						self.file.seek(framelength, 1) # Seek (nhảy) qua phần dữ liệu ảnh để đếm cho nhanh
						count += 1
					except ValueError:
						break
				else:
					break
		else:
			# Với MJPEG: Quét toàn bộ file để tìm số lượng cặp FFD8...FFD9
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
	
	