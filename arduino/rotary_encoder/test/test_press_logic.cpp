// Host test of press_logic.h (g++ -std=c++17 -Wall -Wextra -Werror).
// Run from pytest (tests/test_arduino_firmware.py) and `make -C arduino test`.
#include <cstdio>
#include <cstdlib>

#include "../press_logic.h"

static int failures = 0;
#define CHECK(cond)                                                     \
  do {                                                                  \
    if (!(cond)) {                                                      \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
      failures++;                                                       \
    }                                                                   \
  } while (0)

static const unsigned long CONFIRM = 60;
static const unsigned long LONG_MS = 2000;
static const int8_t PLAY = 2;  // the only holdable button in these tests

static bool holdable(int8_t b) { return b == PLAY; }

struct Run {
  PressState s;
  unsigned long t;
  int downs[16] = {};
  int shorts[16] = {};
  int longs[16] = {};
  explicit Run(unsigned long start = 0) : t(start) { pressInit(s, t); }

  // Feed `btn` every 5 ms for `ms` milliseconds.
  void hold(int8_t btn, unsigned long ms) {
    for (unsigned long e = 0; e < ms; e += 5, t += 5) {
      int8_t which;
      PressEvent ev = pressStep(s, btn, t, CONFIRM, LONG_MS, holdable, which);
      if (ev == PRESS_DOWN) downs[which]++;
      if (ev == PRESS_SHORT) shorts[which]++;
      if (ev == PRESS_LONG) longs[which]++;
    }
  }
};

static void test_plain_button_fires_once_on_press() {
  Run r;
  r.hold(-1, 100);
  r.hold(3, 400);
  CHECK(r.downs[3] == 1);
  r.hold(-1, 100);
  r.hold(3, 100);
  CHECK(r.downs[3] == 2);
  CHECK(r.shorts[3] == 0 && r.longs[3] == 0);
}

static void test_glitch_shorter_than_confirm_is_ignored() {
  Run r;
  r.hold(-1, 100);
  r.hold(3, 40);
  r.hold(-1, 100);
  CHECK(r.downs[3] == 0);
}

static void test_play_short_press() {
  Run r;
  r.hold(-1, 100);
  r.hold(PLAY, 300);
  CHECK(r.shorts[PLAY] == 0);          // nothing while held
  r.hold(-1, 100);
  CHECK(r.shorts[PLAY] == 1 && r.longs[PLAY] == 0 && r.downs[PLAY] == 0);
}

static void test_play_long_press_fires_once_and_no_short() {
  Run r;
  r.hold(-1, 100);
  r.hold(PLAY, 1900);
  CHECK(r.longs[PLAY] == 0);
  r.hold(PLAY, 2000);                  // held ~3.9 s in total
  CHECK(r.longs[PLAY] == 1);
  r.hold(-1, 100);
  CHECK(r.shorts[PLAY] == 0);
  CHECK(r.longs[PLAY] == 1);
}

static void test_button_to_button_needs_release() {
  Run r;
  r.hold(-1, 100);
  r.hold(3, 200);
  r.hold(4, 200);                      // slid over the ladder, no release
  CHECK(r.downs[3] == 1 && r.downs[4] == 0);
  r.hold(-1, 100);
  r.hold(4, 100);
  CHECK(r.downs[4] == 1);
}

static void test_play_then_other_without_release_is_ignored() {
  Run r;
  r.hold(-1, 100);
  r.hold(PLAY, 300);
  r.hold(3, 300);                      // ladder artefact
  CHECK(r.downs[3] == 0 && r.shorts[PLAY] == 0);
  r.hold(-1, 100);
  CHECK(r.shorts[PLAY] == 1);          // the release still ends PLAY short
}

static void test_millis_rollover() {
  Run r(0xFFFFFFFFUL - 500);           // press across the 32-bit wrap
  r.hold(-1, 100);
  r.hold(PLAY, 2500);
  CHECK(r.longs[PLAY] == 1);
  r.hold(-1, 100);
  CHECK(r.shorts[PLAY] == 0);
}

int main() {
  test_plain_button_fires_once_on_press();
  test_glitch_shorter_than_confirm_is_ignored();
  test_play_short_press();
  test_play_long_press_fires_once_and_no_short();
  test_button_to_button_needs_release();
  test_play_then_other_without_release_is_ignored();
  test_millis_rollover();
  if (failures) {
    std::fprintf(stderr, "%d failure(s)\n", failures);
    return 1;
  }
  std::printf("rotary_encoder press_logic: OK\n");
  return 0;
}
