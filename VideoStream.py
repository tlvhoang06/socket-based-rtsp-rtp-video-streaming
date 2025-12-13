class VideoStream:
	def __init__(self, filename):
		self.filename = filename
		try:
			self.file = open(filename, 'rb')
		except:
			raise IOError
		self.frameNum = 0
		self.currentPos = 0
		
		# Detect file format
		self.isRawMjpeg = self.detectFormat()
		
	def detectFormat(self):
		"""Detect if file is raw MJPEG stream or has length headers."""
		self.file.seek(0)
		header = self.file.read(5)
		self.file.seek(0)
		
		# Check if starts with JPEG magic bytes (FF D8)
		if len(header) >= 2 and header[0] == 0xFF and header[1] == 0xD8:
			return True  # Raw MJPEG
		
		# Otherwise assume it has length headers
		return False
		
	def nextFrame(self):
		"""Get next frame."""
		if self.isRawMjpeg:
			return self.nextFrameRawMjpeg()
		else:
			return self.nextFrameWithLength()
	
	def nextFrameWithLength(self):
		"""Get next frame with 5-byte length header format."""
		data = self.file.read(5)
		if data: 
			framelength = int(data)
			# Read the current frame
			data = self.file.read(framelength)
			self.frameNum += 1
		return data
	
	def nextFrameRawMjpeg(self):
		"""Get next frame from raw MJPEG stream (JPEG frames back-to-back)."""
		# Find JPEG start marker (FF D8 FF)
		self.file.seek(self.currentPos)
		
		# Scan for JPEG start marker
		while True:
			byte = self.file.read(1)
			if not byte:
				# End of file
				return b''
			
			if byte == b'\xff':
				next_byte = self.file.read(1)
				if not next_byte:
					return b''
				
				if next_byte == b'\xd8':
					# Found JPEG start (FF D8)
					# Go back 2 bytes to include FF D8
					self.file.seek(self.currentPos)
					frame_start = self.currentPos
					
					# Now find JPEG end marker (FF D9)
					found_end = False
					while True:
						byte = self.file.read(1)
						if not byte:
							break
						
						if byte == b'\xff':
							next_byte = self.file.read(1)
							if not next_byte:
								break
							if next_byte == b'\xd9':
								# Found JPEG end (FF D9)
								frame_end = self.file.tell()
								self.currentPos = frame_end
								found_end = True
								break
					
					if found_end:
						# Read the complete JPEG frame
						self.file.seek(frame_start)
						frame_data = self.file.read(frame_end - frame_start)
						self.frameNum += 1
						return frame_data
					else:
						# No end marker found, read till EOF
						self.file.seek(frame_start)
						frame_data = self.file.read()
						self.frameNum += 1
						return frame_data
		
	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum
	
	