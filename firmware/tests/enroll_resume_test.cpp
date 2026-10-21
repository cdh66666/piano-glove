#include "../src/enroll_flow.h"
#include <assert.h>
#include <initializer_list>
#include <stdio.h>
#include <string.h>

static uint32_t bit(unsigned id) { return 1ul << id; }
static uint32_t staged(unsigned count) {
  uint32_t mask = 0;
  for (unsigned slot = 0; slot < count; ++slot) mask |= bit(20 - slot);
  return mask;
}
static uint32_t canonical(unsigned finalized) {
  uint32_t mask = 0;
  for (unsigned slot = 0; slot < 6; ++slot)
    mask |= bit(slot < finalized ? slot + 1 : 20 - slot);
  return mask;
}
static bool twice(EnrollFlow &flow, uint32_t seen) {
  assert(!flow.observe(seen, 100));
  return flow.observe(seen, 200);
}
static void unchanged(const EnrollFlow &a, const EnrollFlow &b) {
  assert(a.phase == b.phase && a.next == b.next && a.count == b.count);
  assert(a.from == b.from && a.to == b.to && a.slot == b.slot);
  assert(a.stable == b.stable && a.mode == b.mode && a.finalSlot == b.finalSlot);
  assert(a.missingScans == b.missingScans && a.expected == b.expected);
  assert(a.previous == b.previous && a.originals == b.originals);
  assert(a.lastSeen == b.lastSeen && a.lastExpected == b.lastExpected);
  assert(a.missingSinceMs == b.missingSinceMs && !strcmp(a.reason, b.reason));
}
static void rejected(uint32_t seen, uint32_t requiredStages = 0) {
  EnrollFlow flow;
  flow.start();
  flow.phase = EnrollFlow::FAILED;
  flow.count = 2;
  flow.next = 3;
  flow.expected = staged(2);
  flow.lastSeen = bit(19);
  flow.reason = "test_previous_failure";
  const EnrollFlow before = flow;
  assert(!flow.resume(seen, requiredStages));
  unchanged(flow, before);
}
static void finish(EnrollFlow &flow, uint32_t bus, unsigned firstFinalSlot) {
  assert(flow.count == 6 && flow.phase == EnrollFlow::WAIT_NEXT);
  assert(flow.finalSlot == firstFinalSlot && flow.expected == bus);
  assert(twice(flow, bus));
  for (unsigned slot = firstFinalSlot; slot < 6; ++slot) {
    assert(flow.phase == EnrollFlow::VERIFY_FINAL);
    assert(flow.slot == slot && flow.from == 20 - slot && flow.to == slot + 1);
    bus = (bus & ~bit(flow.from)) | bit(flow.to);
    const bool nextWrite = twice(flow, bus);
    assert(nextWrite == (slot < 5));
  }
  assert(bus == canonical(6) && flow.phase == EnrollFlow::DONE);
  assert(flow.count == 6 && !flow.active());
}

int main() {
  // The incident: all six EEPROM ID writes succeeded; the final one was not
  // acknowledged in RAM. A fresh flow must recover the connected 20..15 bus.
  {
    EnrollFlow flow;
    assert(flow.resume(staged(6)));
    assert(flow.count == 6 && flow.next == 6 && flow.finalSlot == 0);
    finish(flow, staged(6), 0);
  }

  // Partial staging is retained, with no request to rewrite the four known IDs.
  {
    EnrollFlow flow;
    assert(flow.resume(staged(4)));
    assert(flow.phase == EnrollFlow::WAIT_NEXT && flow.count == 4 && flow.next == 5);
    assert(flow.expected == staged(4) && flow.from == 0 && flow.to == 0);
    assert(twice(flow, staged(4) | bit(1)));
    assert(flow.from == 1 && flow.to == 16 && flow.slot == 4);
    assert(!twice(flow, staged(5)));
    assert(flow.count == 5 && flow.next == 6);
    assert(twice(flow, staged(5) | bit(1)));
    assert(flow.from == 1 && flow.to == 15 && flow.slot == 5);
    assert(twice(flow, staged(6)));
    // All six staged slots now exist; normal finalization starts at slot zero.
    uint32_t bus = staged(6);
    for (unsigned slot = 0; slot < 6; ++slot) {
      assert(flow.from == 20 - slot && flow.to == slot + 1 && flow.slot == slot);
      bus = (bus & ~bit(flow.from)) | bit(flow.to);
      assert(twice(flow, bus) == (slot < 5));
    }
    assert(flow.phase == EnrollFlow::DONE && bus == canonical(6));
  }

  // Every power-loss point during finalization is reconstructible from IDs.
  // NVS may still contain all temporary IDs when EEPROM was already changed.
  for (unsigned finalized = 1; finalized < 6; ++finalized) {
    EnrollFlow fresh;
    assert(fresh.resume(canonical(finalized), staged(6)));
    assert(fresh.count == 6 && fresh.finalSlot == finalized);
    finish(fresh, canonical(finalized), finalized);
  }
  {
    EnrollFlow flow;
    assert(flow.resume(canonical(6), staged(6)));
    assert(flow.phase == EnrollFlow::DONE && flow.count == 6 && !flow.active());
    assert(flow.expected == canonical(6) && flow.from == 0 && flow.to == 0);
  }

  // Rebooted state needs no prior RAM counters. Confirmed staged mappings set
  // a minimum; missed replies must never free a previously assigned address.
  for (unsigned count = 1; count <= 6; ++count) {
    EnrollFlow fresh;
    assert(fresh.resume(staged(count), staged(count)));
    assert(fresh.count == count && fresh.expected == staged(count));
    assert(fresh.phase == EnrollFlow::WAIT_NEXT);
    rejected(staged(count - 1), staged(count));
  }
  rejected(staged(4) | bit(1), staged(5));
  rejected(staged(5) & ~bit(19), staged(5));

  // A new source remains unconfirmed until normal two-scan assignment.
  for (unsigned source : {1u, 6u}) {
    EnrollFlow fresh;
    const uint32_t seen = staged(2) | bit(source);
    assert(fresh.resume(seen, staged(2)));
    assert(fresh.count == 2 && fresh.next == 3 && fresh.expected == staged(2));
    assert(fresh.from == 0 && fresh.to == 0);
    assert(twice(fresh, seen));
    assert(fresh.from == source && fresh.to == 18 && fresh.slot == 2);
  }

  // Address patterns that do not encode a unique saved slot order must not be
  // treated as a complete bus. In particular, seven addresses cannot be six.
  rejected(staged(6) | bit(1));
  rejected(canonical(6) | bit(20));
  rejected(bit(20) | bit(18));
  rejected(bit(19));
  rejected(bit(1) | bit(3));
  rejected(staged(2) | bit(1) | bit(2));
  rejected(staged(2) | bit(0));
  rejected(staged(2) | bit(21));
  rejected(0);

  puts("enrollment resume PASS: connected six, partial staging, every finalization restart, NVS required slots, pending source, invalid pattern rejection");
}
