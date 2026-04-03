#include <ESP32Servo.h>

#define TRIG_PIN 12
#define ECHO_PIN 13
#define SERVO_PIN 14
#define LED_PIN 2

Servo sorterServo;

const int ANGLE_PLASTIC = 30;
const int ANGLE_PAPER   = 60;    // changed
const int ANGLE_METAL   = 150;
const int ANGLE_UNKNOWN = 90;    // neutral

int triggerThresholdCm = 40;

long measureDistanceCM() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration == 0) return -1;
  return duration / 58;
}

void moveToClass(String cls) {
  cls.trim();
  cls.toUpperCase();

  int angle = ANGLE_UNKNOWN;
  if (cls == "PLASTIC") angle = ANGLE_PLASTIC;
  else if (cls == "PAPER") angle = ANGLE_PAPER;    // now distinct
  else if (cls == "METAL") angle = ANGLE_METAL;
  else angle = ANGLE_UNKNOWN;

  Serial.print("Moving servo to angle: ");
  Serial.print(angle);
  Serial.print(" for class ");
  Serial.println(cls);

  sorterServo.write(angle);
  delay(1500);
  sorterServo.write(ANGLE_UNKNOWN);
  Serial.print("Returning servo to angle: ");
  Serial.println(ANGLE_UNKNOWN);
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  sorterServo.setPeriodHertz(50);
  // If some servos are picky, try 600..2400 instead of 500..2500
  sorterServo.attach(SERVO_PIN, 500, 2500);
  sorterServo.write(ANGLE_UNKNOWN);

  Serial.println("ESP32 ready. Send PLASTIC, PAPER or METAL.");
}

void loop() {
  long d = measureDistanceCM();
  Serial.print("Distance: ");
  Serial.print(d);
  Serial.println(" cm");

  if (d > 0 && d < triggerThresholdCm) {
    Serial.println("DETECT");
    digitalWrite(LED_PIN, HIGH);
    delay(1000);

    unsigned long start = millis();
    while (millis() - start < 5000) {
      if (Serial.available()) {
        String cls = Serial.readStringUntil('\n');
        Serial.print("Received class: ");
        Serial.println(cls);
        moveToClass(cls);
        break;
      }
    }

    digitalWrite(LED_PIN, LOW);
  }

  delay(300);
}
