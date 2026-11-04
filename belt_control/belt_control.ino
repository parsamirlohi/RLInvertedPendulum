// Belt cart keyboard control - Arduino Nano side (smooth reversal version)
// Commands: L = left, R = right, S = stop, V800 = set speed (steps/s)
//           G<pos> = go to absolute position in steps (e.g. G1200, G-300)
//                    keep sending it (>= every 300 ms) or the watchdog stops the cart
//           Z      = set the current position as 0 (only when the cart is not moving)
// Sends "P<position>" every 100 ms.

#include <AccelStepper.h>

const int STEP_PIN = 9;   // -> DM542T PUL+
const int DIR_PIN  = 8;   // -> DM542T DIR+

const long TRAVEL_LIMIT = 1000000;          // effectively no limit
const float MAX_SPEED_CAP = 4000;           // steps/s
const float ACCELERATION  = 1500;           // steps/s^2 (lower = gentler starts/stops)
const unsigned long WATCHDOG_MS = 300;      // stop if the Mac goes quiet
const unsigned long REVERSE_PAUSE_MS = 80;  // rest time before changing direction

AccelStepper stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);

enum Mode { STOPPED, LEFT, RIGHT };
Mode mode = STOPPED;     // what the motor is doing now
Mode wanted = STOPPED;   // what the Mac is asking for
bool trackMode = false;  // true while following G<pos> position targets

unsigned long lastCmdMs = 0;
unsigned long lastReportMs = 0;
unsigned long stoppedAtMs = 0;
char buf[16];
byte bufLen = 0;

// Leaving position-following mode: decelerate smoothly to a stop
void leaveTrackMode() {
  if (trackMode) {
    stepper.stop();
    trackMode = false;
  }
}

void handleLine(const char *line) {
  lastCmdMs = millis();
  switch (line[0]) {
    case 'L': leaveTrackMode(); wanted = LEFT; break;
    case 'R': leaveTrackMode(); wanted = RIGHT; break;
    case 'S': leaveTrackMode(); wanted = STOPPED; break;
    case 'G':
      // Position target: AccelStepper plans the move (and any reversal) itself
      trackMode = true;
      wanted = STOPPED;
      mode = STOPPED;
      stepper.moveTo(atol(line + 1));
      break;
    case 'Z':
      if (!stepper.isRunning()) stepper.setCurrentPosition(0);
      break;
    case 'V': {
      float v = atof(line + 1);
      if (v < 50) v = 50;
      if (v > MAX_SPEED_CAP) v = MAX_SPEED_CAP;
      stepper.setMaxSpeed(v);
      break;
    }
  }
}

void updateMotion() {
  if (trackMode) return;  // G<pos> targets are handled directly by stepper.run()
  if (wanted == mode) return;

  // Moving and asked to stop or reverse: decelerate to a full stop first
  if (mode != STOPPED) {
    stepper.stop();
    mode = STOPPED;
    return;
  }

  // Wait until the motor has fully stopped, then rest briefly
  if (stepper.isRunning()) {
    stoppedAtMs = millis();
    return;
  }
  if (millis() - stoppedAtMs < REVERSE_PAUSE_MS) return;

  // Set the direction signal ahead of the first step pulse
  if (wanted == RIGHT) {
    digitalWrite(DIR_PIN, HIGH);
    delayMicroseconds(20);
    stepper.moveTo(TRAVEL_LIMIT);
    mode = RIGHT;
  } else if (wanted == LEFT) {
    digitalWrite(DIR_PIN, LOW);
    delayMicroseconds(20);
    stepper.moveTo(-TRAVEL_LIMIT);
    mode = LEFT;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(DIR_PIN, OUTPUT);
  stepper.setMinPulseWidth(5);
  stepper.setMaxSpeed(400);
  stepper.setAcceleration(ACCELERATION);
  stepper.setCurrentPosition(0);
  Serial.println("READY");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      buf[bufLen] = '\0';
      if (bufLen > 0) handleLine(buf);
      bufLen = 0;
    } else if (c != '\r' && bufLen < sizeof(buf) - 1) {
      buf[bufLen++] = c;
    }
  }

  if (millis() - lastCmdMs > WATCHDOG_MS) {
    wanted = STOPPED;
    leaveTrackMode();
  }

  updateMotion();
  stepper.run();

  if (millis() - lastReportMs >= 100) {
    lastReportMs = millis();
    Serial.print('P');
    Serial.println(stepper.currentPosition());
  }
}