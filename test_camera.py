#!/usr/bin/env python3
"""
Camera diagnostic — tests /dev/video0 with MJPEG + warmup frames.
Run: python3 test_camera.py
"""
import cv2
import os
import time

USER = os.getenv('USER', 'vyrrs')

print("\nTesting /dev/video0 with MJPEG + 30 warmup frames...")
print("─" * 50)

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)

if not cap.isOpened():
    print("  Cannot open /dev/video0")
    exit(1)

print("  Camera opened. Discarding 30 warmup frames...")
for _ in range(30):
    cap.read()

time.sleep(0.5)
ret, frame = cap.read()
cap.release()

if ret and frame is not None:
    mean = frame.mean()
    h, w = frame.shape[:2]
    path = f"/home/{USER}/test_frame_warm.jpg"
    cv2.imwrite(path, frame)
    print(f"  Frame: {w}x{h}  brightness={mean:.1f}")
    print(f"  Saved: {path}")
    if mean < 5:
        print("  Still black — camera may need a different fix")
    else:
        print("  Looks good! ✓")
else:
    print("  Failed to read frame")

print()
