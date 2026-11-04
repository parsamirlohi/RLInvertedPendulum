// LED Keyboard Control
// Type these keys in the Serial Monitor, then press Enter:
//   o = turn LED on/off
//   f = blink faster
//   s = blink slower
//   + = brighter
//   - = dimmer

const int LED_PIN = 13;

bool ledEnabled = true;            // is the LED turned on?
unsigned long blinkInterval = 500; // milliseconds between on and off
int brightness = 100;              // percent (10 to 100)

bool blinkPhaseOn = true;          // is the blink currently in its "on" half?
unsigned long lastBlinkChange = 0; // when the blink last switched

void setup() {
  pinMode(LED_PIN, OUTPUT);
  Serial.begin(9600);
  Serial.println("Controls: o = on/off, f = faster, s = slower, + = brighter, - = dimmer");
}

void loop() {
  handleKeys();

  // Switch between the on and off halves of the blink when it's time
  unsigned long now = millis();
  if (now - lastBlinkChange >= blinkInterval) {
    blinkPhaseOn = !blinkPhaseOn;
    lastBlinkChange = now;
  }

  if (ledEnabled && blinkPhaseOn) {
    // Dimming: flick the LED on and off very fast (every 2 ms).
    // The higher the brightness, the bigger the part of each cycle it stays on.
    unsigned long cyclePosition = micros() % 2000;
    if (cyclePosition < (unsigned long)brightness * 20) {
      digitalWrite(LED_PIN, HIGH);
    } else {
      digitalWrite(LED_PIN, LOW);
    }
  } else {
    digitalWrite(LED_PIN, LOW);
  }
}

void handleKeys() {
  if (Serial.available() == 0) {
    return; // no key typed
  }

  char key = Serial.read();

  if (key == 'o') {
    ledEnabled = !ledEnabled;
    Serial.println(ledEnabled ? "LED on" : "LED off");
  }
  else if (key == 'f') {
    blinkInterval = blinkInterval / 2;
    if (blinkInterval < 50) blinkInterval = 50;
    Serial.print("Faster: ");
    Serial.print(blinkInterval);
    Serial.println(" ms");
  }
  else if (key == 's') {
    blinkInterval = blinkInterval * 2;
    if (blinkInterval > 2000) blinkInterval = 2000;
    Serial.print("Slower: ");
    Serial.print(blinkInterval);
    Serial.println(" ms");
  }
  else if (key == '+') {
    brightness = brightness + 10;
    if (brightness > 100) brightness = 100;
    Serial.print("Brightness: ");
    Serial.print(brightness);
    Serial.println("%");
  }
  else if (key == '-') {
    brightness = brightness - 10;
    if (brightness < 10) brightness = 10;
    Serial.print("Brightness: ");
    Serial.print(brightness);
    Serial.println("%");
  }
  // any other key (like Enter) is ignored
}