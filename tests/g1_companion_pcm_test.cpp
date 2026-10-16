#include "g1_companion_pcm.hpp"

#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace {

void Put16(std::vector<std::uint8_t>& bytes, std::uint16_t value) {
  bytes.push_back(static_cast<std::uint8_t>(value & 0xffU));
  bytes.push_back(static_cast<std::uint8_t>(value >> 8U));
}

void Put32(std::vector<std::uint8_t>& bytes, std::uint32_t value) {
  for (int shift = 0; shift < 32; shift += 8) {
    bytes.push_back(static_cast<std::uint8_t>(value >> shift));
  }
}

std::vector<std::uint8_t> Wav(std::uint16_t channels = 1,
                              std::uint32_t sample_rate = 16000,
                              std::uint16_t bits = 16) {
  const std::array<std::uint8_t, 4> pcm{{1, 0, 2, 0}};
  std::vector<std::uint8_t> bytes{'R', 'I', 'F', 'F'};
  Put32(bytes, 36U + pcm.size());
  bytes.insert(bytes.end(), {'W', 'A', 'V', 'E', 'f', 'm', 't', ' '});
  Put32(bytes, 16);
  Put16(bytes, 1);
  Put16(bytes, channels);
  Put32(bytes, sample_rate);
  Put32(bytes, sample_rate * channels * bits / 8U);
  Put16(bytes, channels * bits / 8U);
  Put16(bytes, bits);
  bytes.insert(bytes.end(), {'d', 'a', 't', 'a'});
  Put32(bytes, pcm.size());
  bytes.insert(bytes.end(), pcm.begin(), pcm.end());
  return bytes;
}

std::vector<std::uint8_t> PcmWav(std::size_t pcm_bytes) {
  std::vector<std::uint8_t> pcm(pcm_bytes, 0);
  std::vector<std::uint8_t> bytes{'R', 'I', 'F', 'F'};
  Put32(bytes, static_cast<std::uint32_t>(36U + pcm.size()));
  bytes.insert(bytes.end(), {'W', 'A', 'V', 'E', 'f', 'm', 't', ' '});
  Put32(bytes, 16);
  Put16(bytes, 1);
  Put16(bytes, 1);
  Put32(bytes, 16000);
  Put32(bytes, 32000);
  Put16(bytes, 2);
  Put16(bytes, 16);
  bytes.insert(bytes.end(), {'d', 'a', 't', 'a'});
  Put32(bytes, static_cast<std::uint32_t>(pcm.size()));
  bytes.insert(bytes.end(), pcm.begin(), pcm.end());
  return bytes;
}

void TestPlaybackCompletion() {
  const std::vector<std::uint8_t> pcm(151162, 0);
  std::vector<std::size_t> chunks;
  int stops = 0;
  int waited = 0;
  const auto completed = g1::PlayCompanionPcm(
      pcm, 96000,
      [&](const auto& chunk) { chunks.push_back(chunk.size()); return 0; },
      [&] { ++stops; return 0; },
      [&](int milliseconds) {
        assert(milliseconds > 0 && milliseconds <= 20);
        waited += milliseconds;
      }, [] { return false; });
  assert(chunks == (std::vector<std::size_t>{96000, 55162}));
  assert(completed.play_result == 0 && completed.stop_result == 0);
  assert(!completed.interrupted && completed.pcm_bytes_sent == pcm.size());
  assert(stops == 1 && waited == 4724);
}

void TestPlaybackExceptionCleanup() {
  const std::vector<std::uint8_t> pcm(96000, 0);
  for (const bool fail_play : {false, true}) {
    int stops = 0;
    bool caught = false;
    try {
      g1::PlayCompanionPcm(
          pcm, 96000,
          [fail_play](const auto&) {
            if (fail_play) throw std::runtime_error("play failed");
            return 0;
          },
          [&] { ++stops; return 0; },
          [](int) { throw std::runtime_error("sleep failed"); },
          [] { return false; });
    } catch (const std::runtime_error&) {
      caught = true;
    }
    assert(caught && stops == 1);
  }

  int stops = 0;
  bool caught = false;
  try {
    g1::PlayCompanionPcm(
        pcm, 96000, [](const auto&) { return 0; },
        [&]() -> int { ++stops; throw std::runtime_error("stop failed"); },
        [](int) {}, [] { return false; });
  } catch (const std::runtime_error&) {
    caught = true;
  }
  assert(caught && stops == 1);
}

void TestPlaybackRejectsZeroChunk() {
  const std::vector<std::uint8_t> pcm(2, 0);
  int plays = 0;
  int stops = 0;
  bool caught = false;
  try {
    g1::PlayCompanionPcm(
        pcm, 0,
        [&](const auto&) { ++plays; return 0; },
        [&] { ++stops; return 0; },
        [](int) {}, [] { return false; });
  } catch (const std::invalid_argument&) {
    caught = true;
  }
  assert(caught && plays == 0 && stops == 0);
}

}  // namespace

int main() {
  TestPlaybackCompletion();
  TestPlaybackExceptionCleanup();
  TestPlaybackRejectsZeroChunk();
  {
    const std::vector<std::uint8_t> pcm(192000, 0);
    int writes = 0;
    int stops = 0;
    int waited = 0;
    bool cancelled = false;
    const auto interrupted = g1::PlayCompanionPcm(
        pcm, 96000,
        [&](const auto&) { ++writes; return 0; },
        [&] { ++stops; return 0; },
        [&](int milliseconds) { waited += milliseconds; cancelled = true; },
        [&] { return cancelled; });
    assert(interrupted.interrupted && interrupted.play_result == 0);
    assert(interrupted.stop_result == 0 && interrupted.pcm_bytes_sent == 96000);
    assert(writes == 1 && stops == 1 && waited == 20);

    const auto stopped_before_play = g1::PlayCompanionPcm(
        pcm, 96000, [&](const auto&) { ++writes; return 0; },
        [&] { ++stops; return 17; }, [](int) {}, [] { return true; });
    assert(stopped_before_play.interrupted && stopped_before_play.pcm_bytes_sent == 0);
    assert(stopped_before_play.stop_result == 17 && writes == 1 && stops == 2);

    const auto failed = g1::PlayCompanionPcm(
        pcm, 96000, [](const auto&) { return 11; },
        [] { return 19; }, [](int) { assert(false); }, [] { return false; });
    assert(failed.play_result == 11 && failed.stop_result == 19);
    assert(!failed.interrupted && failed.pcm_bytes_sent == 0);
  }
  assert(g1::kCompanionPcmMaxBytes == 32U * 1024U * 1024U);
  assert(g1::CompanionPcmChunkPlaybackMilliseconds(96000) == 3000);
  assert(g1::CompanionPcmChunkPlaybackMilliseconds(55162) == 1724);

  const auto valid = g1::ParseCompanionPcmWav(Wav());
  assert(valid);
  assert(valid->pcm.size() == 4);
  assert(valid->duration_milliseconds == 1);

  auto streaming_wav = Wav();
  streaming_wav[4] = 0xff;
  streaming_wav[5] = 0xff;
  streaming_wav[6] = 0xff;
  streaming_wav[7] = 0x7f;
  streaming_wav[40] = 0xff;
  streaming_wav[41] = 0xff;
  streaming_wav[42] = 0xff;
  streaming_wav[43] = 0x7f;
  assert(g1::ParseCompanionPcmWav(streaming_wav));

  assert(!g1::ParseCompanionPcmWav(Wav(2)));
  assert(!g1::ParseCompanionPcmWav(Wav(1, 22050)));
  assert(!g1::ParseCompanionPcmWav(Wav(1, 16000, 8)));
  assert(!g1::ParseCompanionPcmWav(std::vector<std::uint8_t>{'R', 'I', 'F', 'F'}));
  assert(!g1::ParseCompanionPcmWav(PcmWav(g1::kCompanionPcmMaxBytes + 2U)));
}
