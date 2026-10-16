#pragma once

#include <cstddef>
#include <algorithm>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <vector>

namespace g1 {

constexpr std::size_t kCompanionPcmByteRate = 16000U * 2U;
constexpr std::size_t kCompanionPcmMaxBytes = 32U * 1024U * 1024U;

constexpr std::uint64_t CompanionPcmChunkPlaybackMilliseconds(
    std::size_t pcm_bytes) noexcept {
  return (static_cast<std::uint64_t>(pcm_bytes) * 1000U +
          kCompanionPcmByteRate - 1U) /
         kCompanionPcmByteRate;
}

struct CompanionPcmWav {
  std::vector<std::uint8_t> pcm;
  std::uint64_t duration_milliseconds;
};

struct CompanionPcmPlaybackResult {
  std::int32_t play_result{0};
  std::int32_t stop_result{0};
  std::size_t pcm_bytes_sent{0};
  bool interrupted{false};
};

template <typename Play, typename Stop, typename Sleep, typename Cancelled>
CompanionPcmPlaybackResult PlayCompanionPcm(
    const std::vector<std::uint8_t>& pcm, std::size_t chunk_bytes,
    Play play, Stop stop, Sleep sleep, Cancelled cancelled) {
  if (chunk_bytes == 0) {
    throw std::invalid_argument("chunk_bytes must be non-zero");
  }
  CompanionPcmPlaybackResult result;
  try {
    for (std::size_t offset = 0; offset < pcm.size();) {
      if (cancelled()) { result.interrupted = true; break; }
      const auto end = offset + std::min(chunk_bytes, pcm.size() - offset);
      result.play_result = play(std::vector<std::uint8_t>(
          pcm.begin() + static_cast<std::ptrdiff_t>(offset),
          pcm.begin() + static_cast<std::ptrdiff_t>(end)));
      if (result.play_result != 0) break;
      result.pcm_bytes_sent += end - offset;
      auto remaining = CompanionPcmChunkPlaybackMilliseconds(end - offset);
      while (remaining > 0) {
        if (cancelled()) { result.interrupted = true; break; }
        const auto interval = std::min<std::uint64_t>(remaining, 20);
        sleep(static_cast<int>(interval));
        remaining -= interval;
      }
      if (result.interrupted) break;
      offset = end;
    }
  } catch (...) {
    stop();
    throw;
  }
  result.stop_result = stop();
  return result;
}

inline std::uint16_t ReadLe16(const std::vector<std::uint8_t>& bytes,
                              std::size_t offset) {
  return static_cast<std::uint16_t>(bytes[offset]) |
         (static_cast<std::uint16_t>(bytes[offset + 1]) << 8U);
}

inline std::uint32_t ReadLe32(const std::vector<std::uint8_t>& bytes,
                              std::size_t offset) {
  std::uint32_t value = 0;
  for (std::size_t shift = 0; shift < 32; shift += 8) {
    value |= static_cast<std::uint32_t>(bytes[offset + shift / 8U]) << shift;
  }
  return value;
}

inline bool HasTag(const std::vector<std::uint8_t>& bytes, std::size_t offset,
                   const char (&tag)[5]) {
  return bytes[offset] == static_cast<std::uint8_t>(tag[0]) &&
         bytes[offset + 1] == static_cast<std::uint8_t>(tag[1]) &&
         bytes[offset + 2] == static_cast<std::uint8_t>(tag[2]) &&
         bytes[offset + 3] == static_cast<std::uint8_t>(tag[3]);
}

inline std::optional<CompanionPcmWav> ParseCompanionPcmWav(
    const std::vector<std::uint8_t>& bytes) {
  if (bytes.size() < 12 || !HasTag(bytes, 0, "RIFF") || !HasTag(bytes, 8, "WAVE")) {
    return std::nullopt;
  }
  const std::uint32_t riff_size = ReadLe32(bytes, 4);
  if (
      (riff_size != bytes.size() - 8U && riff_size <= kCompanionPcmMaxBytes)) {
    return std::nullopt;
  }

  bool found_fmt = false;
  bool found_data = false;
  std::uint16_t channels = 0;
  std::uint32_t sample_rate = 0;
  std::uint32_t byte_rate = 0;
  std::uint16_t block_align = 0;
  std::uint16_t bits_per_sample = 0;
  std::vector<std::uint8_t> pcm;

  for (std::size_t offset = 12; offset < bytes.size();) {
    if (bytes.size() - offset < 8) return std::nullopt;
    const std::uint32_t chunk_size = ReadLe32(bytes, offset + 4);
    const std::size_t data_offset = offset + 8;
    const bool streaming_data = HasTag(bytes, offset, "data") &&
                                chunk_size > bytes.size() - data_offset;
    const std::size_t payload_size =
        streaming_data ? bytes.size() - data_offset : chunk_size;
    if (payload_size > bytes.size() - data_offset) return std::nullopt;
    const std::size_t next = streaming_data ? bytes.size()
                                             : data_offset + payload_size + (payload_size & 1U);
    if (next > bytes.size()) return std::nullopt;

    if (HasTag(bytes, offset, "fmt ")) {
      if (found_fmt || chunk_size < 16) return std::nullopt;
      found_fmt = true;
      if (ReadLe16(bytes, data_offset) != 1) return std::nullopt;
      channels = ReadLe16(bytes, data_offset + 2);
      sample_rate = ReadLe32(bytes, data_offset + 4);
      byte_rate = ReadLe32(bytes, data_offset + 8);
      block_align = ReadLe16(bytes, data_offset + 12);
      bits_per_sample = ReadLe16(bytes, data_offset + 14);
    } else if (HasTag(bytes, offset, "data")) {
      if (found_data || payload_size == 0 || payload_size > kCompanionPcmMaxBytes) {
        return std::nullopt;
      }
      found_data = true;
      pcm.assign(bytes.begin() + static_cast<std::ptrdiff_t>(data_offset),
                 bytes.begin() + static_cast<std::ptrdiff_t>(data_offset + payload_size));
    }
    offset = next;
  }

  constexpr std::uint32_t kExpectedSampleRate = 16000;
  constexpr std::uint16_t kExpectedChannels = 1;
  constexpr std::uint16_t kExpectedBits = 16;
  constexpr std::uint16_t kExpectedBlockAlign = 2;
  constexpr std::uint32_t kExpectedByteRate =
      static_cast<std::uint32_t>(kCompanionPcmByteRate);
  if (!found_fmt || !found_data || channels != kExpectedChannels ||
      sample_rate != kExpectedSampleRate || bits_per_sample != kExpectedBits ||
      block_align != kExpectedBlockAlign || byte_rate != kExpectedByteRate ||
      pcm.size() % block_align != 0) {
    return std::nullopt;
  }
  const std::uint64_t duration_milliseconds =
      CompanionPcmChunkPlaybackMilliseconds(pcm.size());
  return CompanionPcmWav{std::move(pcm), duration_milliseconds};
}

}  // namespace g1
