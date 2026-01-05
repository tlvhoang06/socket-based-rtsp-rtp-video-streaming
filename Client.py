import io
import queue
import time  # Để control tốc độ video
from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os

# Đảm bảo import RtpPacket thành công
try:
    from RtpPacket import RtpPacket
except ImportError:
    print("Lỗi: Thiếu file RtpPacket.py")
    sys.exit()

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"

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
        self.serverAddr = serveraddr
        self.serverPort = int(serverport)
        self.rtpPort = int(rtpport)
        self.fileName = filename
        self.rtspSeq = 0
        self.sessionId = 0
        self.requestSent = -1
        self.teardownAcked = 0
        self.connectToServer() 
        self.rtpSocket = None
        self.current_photo = None
        # Thêm cờ đánh dấu luồng đang chạy, tránh tạo nhiều luồng
        self.isListening = False
        self.frameNbr = 0
        
        #  CACHING SETUP 
        self.dataBuffer = b''
        # Hàng đợi chứa các frame ảnh hoàn chỉnh
        self.frameBuffer = queue.Queue(maxsize=1000) 
        # Số lượng frame cần nạp trước khi bắt đầu chiếu (Pre-buffering)
        self.bufferThreshold = 60 
        self.isPlayingBuffer = False
        
        self.totalFrames = 0
        
        self.createWidgets()

    def createWidgets(self):
        """Build GUI."""
        # Create Setup button
        self.setup = Button(self.master, width=20, padx=3, pady=3)
        self.setup["text"] = "Setup"
        self.setup["command"] = self.setupMovie
        self.setup.grid(row=1, column=0, padx=2, pady=2, sticky="s")
        
        # Create Play button        
        self.start = Button(self.master, width=20, padx=3, pady=3)
        self.start["text"] = "Play"
        self.start["command"] = self.playMovie
        self.start.grid(row=1, column=1, padx=2, pady=2, sticky="s")
        
        # Create Pause button           
        self.pause = Button(self.master, width=20, padx=3, pady=3)
        self.pause["text"] = "Pause"
        self.pause["command"] = self.pauseMovie
        self.pause.grid(row=1, column=2, padx=2, pady=2, sticky="s")
        
        # Create Teardown button
        self.teardown = Button(self.master, width=20, padx=3, pady=3)
        self.teardown["text"] = "Teardown"
        self.teardown["command"] =  self.exitClient
        self.teardown.grid(row=1, column=3, padx=2, pady=2, sticky="s")
        
        # Create a label to display the movie
        self.label = Label(self.master, height=19)
        self.label.grid(row=0, column=0, columnspan=4, sticky=W+E+N+S, padx=5, pady=5)

        # Label hiển thị thời gian: 00:00 / 00:00
        self.labelTime = Label(self.master, text="00:00 / 00:00", font=("Helvetica", 10, "bold"))
        self.labelTime.grid(row=2, column=0, padx=5, sticky=W)

        # Sử dụng Canvas để vẽ thanh timeline
        # Thanh timeline (Thanh nhạt)
        self.timelineWidth = 450
        self.timeline = Canvas(self.master, width=self.timelineWidth, height=15, bg='#caf0f8', highlightthickness=0)
        self.timeline.grid(row=2, column=0, columnspan=4, pady=5)
        # Thanh buffer (Màu đậm hơn - thể hiện đã tải được bao nhiêu)
        self.rect_buffer = self.timeline.create_rectangle(0, 0, 0, 15, fill="#90e0ef", width=0)
        # Thanh play (Màu đỏ/xanh đậm - thể hiện đang xem tới đâu)
        self.rect_play = self.timeline.create_rectangle(0, 0, 0, 15, fill="#0077b6", width=0)

        # Thêm khung hiển thị thông số mạng
        stats_frame = LabelFrame(self.master, text="Network Statistics", padx=10, pady=5)
        stats_frame.grid(row=3, column=0, columnspan=4, sticky=W + E, padx=5, pady=5)

        stats_frame.columnconfigure(1, weight=1) # Để tạo ra khoảng trống ở giữa
        
        # Hiển thị Số Frame trong buffer
        self.label_buffer = Label(stats_frame, text="Buffer: 0 frames", width=20, anchor=W)
        self.label_buffer.grid(row=0, column=0, sticky=W)

        # Hiển thị chất lượng video
        self.label_quality = Label(stats_frame, text="Quality: N/A", width=20, anchor=W)
        self.label_quality.grid(row=0, column=4, sticky=W)
    
    # Hàm chuyển đổi frame thành phút / giây (VD frame 60 -> 00:03)
    def convertTime(self, frame_count):
        """Chuyển đổi số frame thành định dạng MM:SS dựa trên FPS."""
        FPS = 20.0  # Tương ứng với time.sleep(0.05)

        total_seconds = frame_count / FPS
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        return f"{minutes:02d}:{seconds:02d}"
    
    # Hàm cập nhật thanh thông số
    def updateProgressBar(self):
        """Cập nhật giao diện Progress Bar"""
        if self.totalFrames == 0:
            return

        current_time_str = self.convertTime(self.frameNbr)
        total_time_str = self.convertTime(self.totalFrames)

        self.labelTime.config(text=f"{current_time_str} / {total_time_str}")


        # Lấy chiều rộng thực tế của thanh Canvas trên màn hình
        w = self.timeline.winfo_width()
        # Lúc mới chạy chưa hiện hình thì mặc định lấy width 450
        if w < 50:
            w = self.timelineWidth
        # Tính % thanh play (Đang phát)
        ratio_play = self.frameNbr / self.totalFrames
        width_play = int(w * ratio_play)

        # Tính % thanh Buffer (Đã tải được tới đâu)
        current_buffered = self.frameNbr + self.frameBuffer.qsize()
        ratio_buffer = current_buffered / self.totalFrames
        width_buffer = int(w * ratio_buffer)

        # Chặn không cho vẽ tràn ra ngoài canvas (nếu buffer > 100%)
        width_play = min(width_play, w)
        width_buffer = min(width_buffer, w)

        try:
            # Vẽ lại (Update toạ độ x2 của hình chữ nhật)
            self.timeline.coords(self.rect_buffer, 0, 0, width_buffer, 15)
            self.timeline.coords(self.rect_play, 0, 0, width_play, 15)
        except:
            pass
        try:
            current_sz = self.frameBuffer.qsize()
            target_sz = self.bufferThreshold
            remaining_frames = self.totalFrames - self.frameNbr

            # Khi Các frame trong buffer là các frame cuối cùng của video -> màu xanh dương
            if  remaining_frames < target_sz:
                 self.label_buffer.config(
                    text=f"Remaining Buffer: {remaining_frames} frames", 
                    fg="#0066FF",
                    font=("Helvetica", 9, "bold")
                )
            # Nếu buffer đang cạn (ít hơn 60) -> Cảnh báo đỏ
            elif current_sz < target_sz:
                self.label_buffer.config(
                    text=f"Buffer: {current_sz}/{target_sz}", 
                    fg="#FF0000", 
                    font=("Helvetica", 9, "bold")
                )
            else:
            # Buffer đầy -> Màu xanh lá 
                self.label_buffer.config(
                    text=f"Buffer {current_sz} frames", 
                    fg="#36F04E",
                    font=("Helvetica", 9, "bold")
                )
        except:
            pass

    def update_gui_safe(self):
        """Cập nhật giao diện trong luồng chính của Tkinter"""
        # Cập nhật ảnh (nếu có ảnh mới nhất được gán vào self.current_photo)
        if hasattr(self, 'current_photo') and self.current_photo:
            self.label.configure(image=self.current_photo, height=340)
            self.label.image = self.current_photo

        # Cập nhật Progress Bar và Thời gian
        self.updateProgressBar()
    
    def setupMovie(self):
        """Setup button handler."""
        if self.state == self.INIT:
            self.sendRtspRequest(self.SETUP)
    
    def exitClient(self):
        """Teardown button handler."""
        self.sendRtspRequest(self.TEARDOWN)		
        self.master.destroy() # Close the gui window
        try:
            os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT) # Delete the cache image from video
        except OSError:
            pass

    def pauseMovie(self):
        """Pause button handler."""
        if self.state == self.PLAYING:
            self.sendRtspRequest(self.PAUSE)
    
    def playMovie(self):
        """Play button handler."""
        if self.state == self.READY:
            # Create a new thread to listen for RTP packets
            # Chỉ tạo luồng mới nếu chưa có luồng nào đang chạy
            if self.isListening == False:
                threading.Thread(target=self.listenRtp).start()
                self.isListening = True
            self.playEvent = threading.Event()
            self.playEvent.clear()
            self.sendRtspRequest(self.PLAY)
        if not self.isPlayingBuffer:
            self.isPlayingBuffer = True
            threading.Thread(target=self.runCache).start()
    
    # PHẦN 1: PRODUCER (Nhận gói tin -> Đẩy vào Queue) 
    def listenRtp(self):        
        """Listen for RTP packets."""

        self.dataBuffer = b"" # Đảm bảo buffer rỗng khi bắt đầu
        prev_seq_num = -1 # Biến theo dõi gói tin trước đó
        while True:
            try:
                data = self.rtpSocket.recv(65536)
                if not data: continue
                
                rtpPacket = RtpPacket()
                rtpPacket.decode(data)
                
                curr_seq_num = rtpPacket.seqNum()
                
                # Logic chống xước phim (mất gói)
                # Nếu số thứ tự gói hiện tại không liền kề với gói trước đó (VD: nhận 5 xong nhảy lên 7),
                # nghĩa là gói 6 đã bị mất trên đường truyền.
                # --> Hủy bỏ buffer đang lắp ráp dở để tránh hiển thị hình ảnh bị lỗi (glitch).
                if prev_seq_num != -1 and curr_seq_num != (prev_seq_num + 1):
                    self.dataBuffer = b""
                
                # Cập nhật số thứ tự gói tin
                prev_seq_num = curr_seq_num
                # Nối phần dữ liệu (Payload) vào buffer tạm
                self.dataBuffer += rtpPacket.getPayload()
                
                # Cơ chế ghép 
                # Kiểm tra Marker bit trong header RTP.
                # Marker = 1 báo hiệu đây là gói tin cuối cùng của một Frame ảnh.
                if rtpPacket.marker() == 1:
                    # Thay vì hiển thị ngay, ta ĐẨY VÀO BUFFER (QUEUE)
                    if len(self.dataBuffer) > 0:    
                        if self.frameBuffer.full() == False:
                            self.frameBuffer.put(self.dataBuffer)
                    
                    # Reset buffer tạm để chuẩn bị cho frame tiếp theo
                    self.dataBuffer = b''
            except:
                if self.teardownAcked == 1:
                    if self.rtpSocket:
                        self.rtpSocket.shutdown(socket.SHUT_RDWR)
                        self.rtpSocket.close()
                    break

    #  PHẦN 2: CONSUMER (Lấy từ Queue -> Hiển thị) 
    def runCache(self):
        FRAME_TIME = 0.05 # Thời gian hiển thị mỗi frame (0.05s = 20 FPS)

        # Giai đoạn Pre-buffering:
        # Chờ buffer nạp đủ lượng frame tối thiểu (Threshold) mới bắt đầu phát.
        print(f"Đang nạp buffer... Cần {self.bufferThreshold} frame.")
        while self.frameBuffer.qsize() < self.bufferThreshold and self.state != self.TEARDOWN:
            self.master.after(0, self.updateProgressBar) # Cập nhật hiển thị buffer khi nạp
            time.sleep(0.1)
        print("Đã nạp đủ! Bắt đầu chiếu.")

        stuck_counter = 0

        while True:
            if self.requestSent == self.TEARDOWN:
                break

            if self.state == self.PLAYING:
                #  TRƯỜNG HỢP 1: CÓ ẢNH ĐỂ CHIẾU 
                if not self.frameBuffer.empty():
                    stuck_counter = 0  # Reset đếm kẹt

                    # Lấy frame và chiếu
                    image_data = self.frameBuffer.get()
                    print(f"Lấy frame. Trong buffer còn lại: {self.frameBuffer.qsize()} frame")
                    self.frameNbr += 1

                    # Đo thời gian xử lý ảnh để bù trừ độ trễ
                    start_process_time = time.time()
                    self.updateMovie(image_data)
                    self.master.after(0, self.update_gui_safe)

                    # Đồng bộ thời gian
                    # Nếu xử lý ảnh quá nhanh, cần ngủ (sleep) một chút để duy trì đúng 20 FPS.
                    process_duration = time.time() - start_process_time
                    time_to_sleep = FRAME_TIME - process_duration
                    if time_to_sleep > 0:
                        time.sleep(time_to_sleep)

                #  TRƯỜNG HỢP 2: BUFFER RỖNG 
                else:
                    # 1. KIỂM TRA ĐÃ HẾT VIDEO CHƯA
                    # Nếu số frame đã chiếu >= Tổng số frame của video
                    if self.totalFrames > 0 and self.frameNbr >= self.totalFrames:
                        print("Video kết thúc.")
                        self.isListening = False  # Dừng luồng nghe
                        break  # Thoát vòng lặp

                    # 2. XỬ LÝ KHI CHƯA HẾT MÀ BỊ RỖNG (Do mạng lag)
                    if self.isListening:
                        stuck_counter += 1
                        print(f"Buffer đã hết... (Chờ lần {stuck_counter})")
                        time.sleep(0.1)

                        # Cơ chế Timeout: Nếu chờ quá lâu (> 3 giây) mà không có dữ liệu -> Ngắt kết nối.
                        if stuck_counter > 30:
                            print("Time out! Kết thúc video sớm.")
                            self.isListening = False
                            break
                    else:
                        break
            else:
                time.sleep(0.1)

    def updateMovie(self, image_data):
        """Update the image file as video frame in the GUI."""
        try:
            # Xử lý trực tiếp từ Bytes (không cần ghi ra file đĩa -> nhanh hơn)
            image_stream = io.BytesIO(image_data)
            original_image = Image.open(image_stream)
            
            # Logic kiểm tra chất lượng (chạy 1 lần ở frame đầu hoặc định kỳ)
            if self.frameNbr % 30 == 1: 
                w, h = original_image.size
                if h >= 1080: res_text = "FHD (1080p)"
                elif h >= 720: res_text = "HD (720p)"
                elif h >= 480: res_text = "SD (480p)"
                else: res_text = f"Low ({w}x{h})"
                try: self.label_quality.config(text=f"Quality: {res_text}")
                except: pass

            target_width = 600
            target_height = 340
            resized_image = original_image.resize((target_width, target_height))
            
            # Cần dùng threading lock hoặc master.after nếu muốn chuẩn chỉ, 
            # nhưng với Tkinter đơn giản có thể gán trực tiếp
            self.current_photo = ImageTk.PhotoImage(resized_image)

        except Exception as e:
            # print(e)
            pass
        
    def connectToServer(self):
        """Connect to the Server."""
        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.rtspSocket.connect((self.serverAddr, self.serverPort))
        except:
            tkinter.messagebox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)
    
    def sendRtspRequest(self, requestCode):
        """Send RTSP request to the server."""  
        if requestCode == self.SETUP and self.state == self.INIT:
            threading.Thread(target=self.recvRtspReply).start()
            self.rtspSeq += 1
            request = "SETUP " + self.fileName + " RTSP/1.0\n" + "CSeq: " + str(self.rtspSeq) + "\n" + "Transport: RTP/UDP; client_port=" + str(self.rtpPort) + "\n"
            self.requestSent = self.SETUP
        
        elif requestCode == self.PLAY and self.state == self.READY:
            self.rtspSeq += 1
            request = "PLAY " + self.fileName + " RTSP/1.0\n" + "CSeq: " + str(self.rtspSeq) + "\n" + "Session: " + str(self.sessionId) + "\n"
            self.requestSent = self.PLAY
        
        elif requestCode == self.PAUSE and self.state == self.PLAYING:
            self.rtspSeq += 1
            request = "PAUSE " + self.fileName + " RTSP/1.0\n" + "CSeq: " + str(self.rtspSeq) + "\n" + "Session: " + str(self.sessionId) + "\n"
            self.requestSent = self.PAUSE
            
        elif requestCode == self.TEARDOWN and not self.state == self.INIT:
            self.rtspSeq += 1
            request = "TEARDOWN " + self.fileName + " RTSP/1.0\n" + "CSeq: " + str(self.rtspSeq) + "\n" + "Session: " + str(self.sessionId) + "\n"
            self.requestSent = self.TEARDOWN
        else:
            return
        
        self.rtspSocket.send(request.encode('utf-8'))
        print('\nData sent:\n' + request)
    
    def recvRtspReply(self):
        """Receive RTSP reply from the server."""
        while True:
            try:
                reply = self.rtspSocket.recv(1024)
                if reply: 
                    self.parseRtspReply(reply.decode("utf-8"))
                
                if self.requestSent == self.TEARDOWN:
                    self.rtspSocket.shutdown(socket.SHUT_RDWR)
                    self.rtspSocket.close()
                    break
            except:
                break
     
    def parseRtspReply(self, data):
        """Parse the RTSP reply from the server."""
        lines = data.split('\n')
        seqNum = int(lines[1].split(' ')[1])
        
        # Process only if the server reply's sequence number is the same as the request's
        if seqNum == self.rtspSeq:
            session = int(lines[2].split(' ')[1])
            # New RTSP session ID
            if self.sessionId == 0:
                self.sessionId = session
            
            # Process only if the session ID is the same
            if self.sessionId == session:
                if int(lines[0].split(' ')[1]) == 200: 
                    if self.requestSent == self.SETUP:
                        # Update RTSP state.
                        self.state = self.READY
                        
                        # Lấy totalFrames từ header mở rộng
                        for line in lines:
                            if "Total-Frames" in line:
                                try:
                                    self.totalFrames = int(line.split(':')[1])
                                    print(f"Total frames: {self.totalFrames}")
                                except:
                                    self.totalFrames = 0

                        # Open RTP port.
                        self.openRtpPort() 
                    elif self.requestSent == self.PLAY:
                        self.state = self.PLAYING
                    elif self.requestSent == self.PAUSE:
                        self.state = self.READY
                        
                        # The play thread exits. A new thread is created on resume.
                        self.playEvent.set()
                    elif self.requestSent == self.TEARDOWN:
                        self.state = self.INIT
                        
                        # Flag the teardownAcked to close the socket.
                        self.teardownAcked = 1 
	

    def openRtpPort(self):
        """Open RTP socket binded to a specified port."""
        # Create a new datagram socket to receive RTP packets from the server
        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # [QUAN TRỌNG] Tối ưu hóa Socket Buffer:
        # Tăng kích thước bộ đệm nhận (Receive Buffer) của kernel lên 5MB.
        # Lý do: Nếu Python xử lý chậm, dữ liệu UDP đến quá nhanh sẽ bị kernel drop (vứt bỏ).
        # Tăng buffer giúp giảm thiểu hiện tượng mất gói tin (packet loss) ở tầng Transport.
        self.rtpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 5 * 1024 * 1024)
        
        # Set the timeout value of the socket to 0.5sec
        self.rtpSocket.settimeout(0.5)

        try:
            # Bind the socket to the address using the RTP port given by the client user
            self.rtpSocket.bind(("", self.rtpPort))
        except:
            tkinter.messagebox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)

    def handler(self):
        """Handler on explicitly closing the GUI window."""
        self.pauseMovie()
        if tkinter.messagebox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else: # When the user presses cancel, resume playing.
            self.playMovie()
