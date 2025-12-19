import io
import queue
import time  # Cần import time để xử lý độ trễ
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
        
        # --- FIX 1: Kết nối và GIỮ socket (không gán None) ---
        self.connectToServer() 
        self.rtpSocket = None
        self.current_photo = None
        # Thêm cờ đánh dấu luồng đang chạy
        self.isListening = False
        self.frameNbr = 0
        
        # --- CACHING SETUP ---
        self.dataBuffer = b''
        # Hàng đợi chứa các frame ảnh hoàn chỉnh
        self.frameBuffer = queue.Queue(maxsize=1000) 
        # Số lượng frame cần nạp trước khi bắt đầu chiếu (Pre-buffering)
        self.bufferThreshold = 20 
        self.isPlayingBuffer = False
        
        self.totalFrames = 0
        self.fps_count = 0
        
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

        # --- FIX 2: Thêm Label Quality và Status Buffer ---
        self.label_info = Label(self.master, text="State: INIT", anchor=W)
        self.label_info.grid(row=2, column=0, columnspan=2, sticky="ew")
        
        self.label_quality = Label(self.master, text="Quality: Unknown", anchor=E)
        self.label_quality.grid(row=2, column=2, columnspan=2, sticky="ew")

    def update_gui_safe(self):
        """Cập nhật giao diện trong luồng chính của Tkinter"""
        # Cập nhật ảnh (nếu có ảnh mới nhất được gán vào self.current_photo)
        if hasattr(self, 'current_photo') and self.current_photo:
            self.label.configure(image=self.current_photo, height=340)
            self.label.image = self.current_photo

        # Cập nhật Progress Bar và Thời gian
        #self.updateProgressBar()
    
    def setupMovie(self):
        """Setup button handler."""
        if self.state == self.INIT:
            self.sendRtspRequest(self.SETUP)
    
    def exitClient(self):
        """Teardown button handler."""
        self.sendRtspRequest(self.TEARDOWN)        
        self.master.destroy() 
        try:
            os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT)
        except:
            pass

    def pauseMovie(self):
        """Pause button handler."""
        if self.state == self.PLAYING:
            self.sendRtspRequest(self.PAUSE)
    
    def playMovie(self):
        """Play button handler."""
        if self.state == self.READY:
            # Khi bấm Play, ta bắt đầu luồng chạy Buffer (Consumer)
            if not self.isPlayingBuffer:
                self.isPlayingBuffer = True
                threading.Thread(target=self.runCache, daemon=True).start()
            
            self.sendRtspRequest(self.PLAY)
    
    # --- PHẦN 1: PRODUCER (Nhận gói tin -> Đẩy vào Queue) ---
    def listenRtp(self):        
        """Listen for RTP packets."""
        while True:
            try:
                data = self.rtpSocket.recv(65536)
                if not data: continue
                
                rtpPacket = RtpPacket()
                rtpPacket.decode(data)
                
                currFrameNbr = rtpPacket.seqNum()
                
                # Logic ghép gói tin
                self.dataBuffer += rtpPacket.getPayload()
                
                # Kiểm tra Marker bit = 1 (Gói cuối cùng của frame)
                if rtpPacket.marker() == 1:
                    # Thay vì hiển thị ngay, ta ĐẨY VÀO BUFFER (QUEUE)
                    if self.frameBuffer.full() == False:
                        # Lưu dữ liệu ảnh vào queue
                        self.frameBuffer.put(self.dataBuffer)
                    
                    # Reset buffer tạm
                    self.dataBuffer = b''
            except:
                if self.teardownAcked == 1:
                    if self.rtpSocket:
                        self.rtpSocket.shutdown(socket.SHUT_RDWR)
                        self.rtpSocket.close()
                    break

    # --- PHẦN 2: CONSUMER (Lấy từ Queue -> Hiển thị) ---
    def runCache(self):
        FRAME_TIME = 0.05

        # Nạp buffer ban đầu
        print(f"Đang nạp buffer... Cần {self.bufferThreshold} frame.")
        while self.frameBuffer.qsize() < self.bufferThreshold and self.state != self.TEARDOWN:
            time.sleep(0.1)
        print("Đã nạp đủ! Bắt đầu chiếu.")

        stuck_counter = 0

        while True:
            if self.requestSent == self.TEARDOWN:
                break

            if self.state == self.PLAYING:
                # --- TRƯỜNG HỢP 1: CÓ ẢNH ĐỂ CHIẾU ---
                if not self.frameBuffer.empty():
                    stuck_counter = 0  # Reset đếm kẹt

                    # Lấy frame và chiếu
                    image_data = self.frameBuffer.get()
                    print(f"-> [Play] Lấy frame. Còn lại: {self.frameBuffer.qsize()} frame")
                    self.frameNbr += 1

                    start_process_time = time.time()
                    self.updateMovie(image_data)
                    self.master.after(0, self.update_gui_safe)

                    # Giữ nhịp FPS
                    process_duration = time.time() - start_process_time
                    time_to_sleep = FRAME_TIME - process_duration
                    if time_to_sleep > 0:
                        time.sleep(time_to_sleep)

                # --- TRƯỜNG HỢP 2: BUFFER RỖNG ---
                else:
                    # 1. KIỂM TRA ĐÃ HẾT VIDEO CHƯA (Ưu tiên số 1)
                    # Nếu số frame đã chiếu >= Tổng số frame của video
                    if self.totalFrames > 0 and self.frameNbr >= self.totalFrames:
                        print("Video finished.")  # <--- In đúng dòng bạn cần
                        self.isListening = False  # Dừng luồng nghe
                        break  # Thoát vòng lặp

                    # 2. XỬ LÝ KHI CHƯA HẾT MÀ BỊ RỖNG (Do mạng lag)
                    if self.isListening:
                        stuck_counter += 1
                        print(f"Buffer cạn... (Chờ lần {stuck_counter})")
                        time.sleep(0.1)

                        # Timeout sau 3 giây chờ đợi
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
            sys.exit(0)
    
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
        lines = data.split('\n')
        if len(lines) < 3: return
        seqNum = int(lines[1].split(' ')[1])
        
        if seqNum == self.rtspSeq:
            session = int(lines[2].split(' ')[1])
            if self.sessionId == 0:
                self.sessionId = session
            
            if self.sessionId == session:
                if int(lines[0].split(' ')[1]) == 200: 
                    if self.requestSent == self.SETUP:
                        self.state = self.READY
                        self.openRtpPort() 
                    elif self.requestSent == self.PLAY:
                        self.state = self.PLAYING
                    elif self.requestSent == self.PAUSE:
                        self.state = self.READY
                    elif self.requestSent == self.TEARDOWN:
                        self.state = self.INIT
                        self.teardownAcked = 1 

    def openRtpPort(self):
        """Open RTP socket binded to a specified port."""
        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtpSocket.settimeout(0.5)
        # Tăng buffer nhận của Socket lên để tránh rớt gói UDP
        self.rtpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024*1024) 
        try:
            self.rtpSocket.bind(('', self.rtpPort))
            threading.Thread(target=self.listenRtp, daemon=True).start()
        except:
            tkinter.messagebox.messagebox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)

    def handler(self):
        self.pauseMovie()
        if tkinter.messagebox.messagebox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else:
            self.playMovie()
