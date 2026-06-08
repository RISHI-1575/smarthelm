# SmartHelm — Central Configuration

# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
USE_PI_CAMERA: bool = True       # True = use CSI Pi camera for CAM1
PI_CAMERA_WIDTH: int  = 640
PI_CAMERA_HEIGHT: int = 480

USE_WEBCAM_FALLBACK: bool = False
WEBCAM_INDEX: int = 0

# ESP32-CAM URLs (only used when USE_PI_CAMERA = False)
CAM1_URL: str = ""                              # Pi CSI camera (USE_PI_CAMERA=True)
CAM2_URL: str = "http://10.42.0.173:81/stream"  # ESP32-CAM front view
CAM3_URL: str = "http://10.42.0.79:81/stream"   # ESP32-CAM rear view

# ---------------------------------------------------------------------------
# MediaPipe eye landmark indices (468-point model)
# EAR = (||P2-P6|| + ||P3-P5||) / (2 * ||P1-P4||)
# ---------------------------------------------------------------------------
LEFT_EYE_INDICES: tuple  = (362, 385, 387, 263, 373, 380)
RIGHT_EYE_INDICES: tuple = (33,  160, 158, 133, 153, 144)

# ---------------------------------------------------------------------------
# Eye Aspect Ratio thresholds
# ---------------------------------------------------------------------------
EAR_OPEN_THRESHOLD: float   = 0.25
EAR_CLOSED_THRESHOLD: float = 0.20
EAR_SMOOTHING_WINDOW: int   = 5

# ---------------------------------------------------------------------------
# Drowsiness detection
# ---------------------------------------------------------------------------
PERCLOS_THRESHOLD: float         = 30.0
PERCLOS_WINDOW_SECONDS: int      = 60
CLOSED_DURATION_THRESHOLD: float = 1.5
ALERT_CLEAR_DELAY: float         = 2.0

# ---------------------------------------------------------------------------
# Detection mode: "EAR" or "CNN"
# ---------------------------------------------------------------------------
DETECTION_MODE: str         = "EAR"
CNN_MODEL_PATH: str         = "models/eye_state_mobilenetv2.onnx"
CNN_INPUT_SIZE: tuple       = (64, 64)
CNN_CLOSED_THRESHOLD: float = 0.5

# ---------------------------------------------------------------------------
# Buzzer (GPIO)
# ---------------------------------------------------------------------------
BUZZER_PIN: int = 17

# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------
MQTT_BROKER: str          = "localhost"
MQTT_PORT: int            = 1883
MQTT_TOPIC_TEMPLATE: str  = "smarthelm/{cam}/eye_state"
MQTT_PUBLISH_HZ: float    = 1.0

# ---------------------------------------------------------------------------
# Flask / Dashboard
# ---------------------------------------------------------------------------
FLASK_HOST: str          = "0.0.0.0"
FLASK_PORT: int          = 5000
MJPEG_FRAME_DELAY: float = 0.067  # 15 FPS — saves CPU

# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
ALERT_COOLDOWN_SECONDS: float = 3.0
ALERT_BEEP_FREQUENCY: int     = 1000
ALERT_BEEP_DURATION_MS: int   = 300
ALERT_BEEP_COUNT: int         = 3

# ---------------------------------------------------------------------------
# SMS (SIM800L via UART — set SMS_ENABLED=True once SIM is inserted)
# ---------------------------------------------------------------------------
SMS_ENABLED: bool         = False
SMS_PORT: str             = "/dev/ttyAMA0"   # Pi UART after disable-bt
SMS_BAUD: int             = 9600
EMERGENCY_CONTACT: str    = "+91XXXXXXXXXX"
SMS_COOLDOWN_MINUTES: float = 5.0

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR: str             = "logs"
LOG_CSV_FILENAME: str    = "events.csv"
LOG_TO_CSV: bool         = True
LOG_INTERVAL_SECONDS: float = 1.0
