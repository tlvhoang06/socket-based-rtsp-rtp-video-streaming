# Socket-based RTSP/RTP Video Streaming Application
## This is a group project of the Computer Network Course
![Language](https://img.shields.io/badge/language-Python-blue.svg) ![Protocol](https://img.shields.io/badge/protocol-RTSP%2FRTP-orange.svg) ![License](https://img.shields.io/badge/license-MIT-green.svg)

A lightweight Video Streaming implementation based on the **Real-Time Streaming Protocol (RTSP)** and **Real-time Transport Protocol (RTP)** using Python socket programming.

This project demonstrates how video data is packetized and transmitted over UDP (RTP) while being controlled by a separate TCP connection (RTSP), following a Client-Server architecture.

##  Demo

<img width="1399" height="1050" alt="Screenshot 2026-01-05 211409" src="https://github.com/user-attachments/assets/a89524e2-8057-4860-aa73-3d259e47bb24" />


##  Features

* **RTSP Protocol Implementation:** Handles standard RTSP methods:
    * `SETUP`: Initialize session and transport mechanism.
    * `PLAY`: Start transmitting video data.
    * `PAUSE`: Temporarily stop the stream.
    * `TEARDOWN`: Terminate the session and close connections.
* **RTP Packetization:** Encapsulates MJPEG video frames into RTP packets with sequence numbers and timestamps.
* **Socket Programming:**
    * **TCP:** Used for RTSP control commands (Reliable).
    * **UDP:** Used for RTP video data transmission (Fast/Low latency).
* **Multi-threading:** Server handles video sending in a separate thread to maintain responsiveness.
* **Support Both SD and HD videos
##  Architecture

The application follows a standard Client-Server model:



1.  **Client (RTSP):** Sends requests to change the state of the stream.
2.  **Server (RTSP):** Listens for requests and updates the state machine.
3.  **Server (RTP):** When in `PLAY` state, reads video frames, packetizes them, and sends them via UDP.
4.  **Client (RTP):** Receives UDP packets, depacketizes them, and renders the video frames.

##  Prerequisites

Ensure you have **Python 3.x** installed. You may need the standard libraries and `Pillow` (PIL) for image rendering (if you used it).

```bash
pip install Pillow
