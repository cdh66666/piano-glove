#pragma once
#include <Arduino.h>
namespace library {
void begin();
void tick();
bool command(int n,char **tokens);
void stop(const char *reason="stopped");
bool active();
const char *ssid();
String ip();
bool apReady();
void setExclusiveBusy(bool value);
}
