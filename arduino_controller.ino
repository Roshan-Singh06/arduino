/*
  Arduino Universal Control Center
  Board: Arduino Uno
  Serial baud: 115200

  Commands:
  PING
  STATUS
  ARM
  DISARM
  ESTOP
  RESET
  HB
  MODE,pin,IN
  MODE,pin,OUT
  D,pin,0
  D,pin,1
  PWM,pin,0-255
  STREAM,1,interval_ms
  STREAM,0
*/

const unsigned long BAUD_RATE = 115200;
const unsigned long WATCHDOG_MS = 1500;

const byte FIRST_PIN = 2;
const byte LAST_PIN = 13;

const byte PWM_PINS[] = {3, 5, 6, 9, 10, 11};
const byte PWM_COUNT = sizeof(PWM_PINS) / sizeof(PWM_PINS[0]);

bool outputMode[14] = {false};
bool armed = false;
bool estop = false;

bool streaming = false;
unsigned long streamInterval = 250;
unsigned long lastStream = 0;
unsigned long lastHeartbeat = 0;

String commandBuffer;

bool validPin(int pin) {
  return pin >= FIRST_PIN && pin <= LAST_PIN;
}

bool isPwmPin(int pin) {
  for (byte i = 0; i < PWM_COUNT; i++) {
    if (PWM_PINS[i] == pin) return true;
  }
  return false;
}

void outputsOff() {
  for (int pin = FIRST_PIN; pin <= LAST_PIN; pin++) {
    if (outputMode[pin]) {
      digitalWrite(pin, LOW);
      if (isPwmPin(pin)) analogWrite(pin, 0);
    }
  }
}

void disarm() {
  armed = false;
  outputsOff();
}

void acknowledge(const String &message) {
  Serial.print("ACK,");
  Serial.println(message);
}

void processCommand(String cmd) {
  cmd.trim();

  if (cmd == "PING") {
    Serial.println("PONG");
    return;
  }

  if (cmd == "STATUS") {
    Serial.print("STATUS,");
    Serial.print(armed ? "ARMED" : "DISARMED");
    Serial.print(",");
    Serial.println(estop ? "ESTOP" : "NORMAL");
    return;
  }

  if (cmd == "HB") {
    lastHeartbeat = millis();
    return;
  }

  if (cmd == "ARM") {
    if (estop) {
      Serial.println("FAULT,ESTOP_ACTIVE");
      return;
    }

    armed = true;
    lastHeartbeat = millis();
    acknowledge("ARMED");
    return;
  }

  if (cmd == "DISARM") {
    disarm();
    acknowledge("DISARMED");
    return;
  }

  if (cmd == "ESTOP") {
    estop = true;
    disarm();
    Serial.println("FAULT,ESTOP_LATCHED");
    return;
  }

  if (cmd == "RESET") {
    disarm();
    estop = false;
    acknowledge("ESTOP_RESET");
    return;
  }

  if (cmd.startsWith("MODE,")) {
    int first = cmd.indexOf(',');
    int second = cmd.indexOf(',', first + 1);

    int pin = cmd.substring(first + 1, second).toInt();
    String mode = cmd.substring(second + 1);

    if (!validPin(pin)) {
      Serial.println("ERROR,INVALID_PIN");
      return;
    }

    if (mode == "OUT") {
      if (armed || estop) {
        Serial.println("ERROR,DISARM_BEFORE_CONFIG");
        return;
      }

      pinMode(pin, OUTPUT);
      digitalWrite(pin, LOW);
      outputMode[pin] = true;
      acknowledge("PIN_OUTPUT");
    }
    else if (mode == "IN") {
      if (armed || estop) {
        Serial.println("ERROR,DISARM_BEFORE_CONFIG");
        return;
      }

      pinMode(pin, INPUT);
      outputMode[pin] = false;
      acknowledge("PIN_INPUT");
    }
    else {
      Serial.println("ERROR,INVALID_MODE");
    }
    return;
  }

  if (cmd.startsWith("D,")) {
    int first = cmd.indexOf(',');
    int second = cmd.indexOf(',', first + 1);

    int pin = cmd.substring(first + 1, second).toInt();
    int value = cmd.substring(second + 1).toInt();

    if (!validPin(pin) || !outputMode[pin]) {
      Serial.println("ERROR,PIN_NOT_OUTPUT");
      return;
    }

    if (!armed || estop) {
      Serial.println("ERROR,OUTPUT_NOT_ARMED");
      return;
    }

    if (value != 0 && value != 1) {
      Serial.println("ERROR,INVALID_VALUE");
      return;
    }

    digitalWrite(pin, value);
    acknowledge("DIGITAL_SET");
    return;
  }

  if (cmd.startsWith("PWM,")) {
    int first = cmd.indexOf(',');
    int second = cmd.indexOf(',', first + 1);

    int pin = cmd.substring(first + 1, second).toInt();
    int value = cmd.substring(second + 1).toInt();

    if (!validPin(pin) || !isPwmPin(pin) || !outputMode[pin]) {
      Serial.println("ERROR,PWM_PIN_NOT_CONFIGURED");
      return;
    }

    if (!armed || estop) {
      Serial.println("ERROR,OUTPUT_NOT_ARMED");
      return;
    }

    if (value < 0 || value > 255) {
      Serial.println("ERROR,INVALID_PWM");
      return;
    }

    analogWrite(pin, value);
    acknowledge("PWM_SET");
    return;
  }

  if (cmd.startsWith("STREAM,")) {
    int first = cmd.indexOf(',');
    int second = cmd.indexOf(',', first + 1);

    int enabled = cmd.substring(first + 1, second).toInt();

    if (enabled == 1) {
      unsigned long interval =
        cmd.substring(second + 1).toInt();

      streamInterval = constrain(interval, 100, 5000);
      streaming = true;
      lastStream = 0;
    } else {
      streaming = false;
    }

    acknowledge("STREAM_UPDATED");
    return;
  }

  Serial.println("ERROR,UNKNOWN_COMMAND");
}

void setup() {
  Serial.begin(BAUD_RATE);

  for (int pin = FIRST_PIN; pin <= LAST_PIN; pin++) {
    pinMode(pin, INPUT);
  }

  commandBuffer.reserve(80);
  lastHeartbeat = millis();

  Serial.println("READY,ARDUINO_UNIVERSAL_CONTROLLER");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();

    if (c == '\n') {
      processCommand(commandBuffer);
      commandBuffer = "";
    }
    else if (c != '\r') {
      if (commandBuffer.length() < 80) {
        commandBuffer += c;
      } else {
        commandBuffer = "";
        Serial.println("ERROR,COMMAND_TOO_LONG");
      }
    }
  }

  if (armed && millis() - lastHeartbeat > WATCHDOG_MS) {
    disarm();
    Serial.println("FAULT,HOST_TIMEOUT");
  }

  if (streaming && millis() - lastStream >= streamInterval) {
    lastStream = millis();

    Serial.print("DATA,");
    Serial.print(millis());

    for (int pin = A0; pin <= A5; pin++) {
      Serial.print(",");
      Serial.print(analogRead(pin));
    }

    Serial.println();
  }
}
