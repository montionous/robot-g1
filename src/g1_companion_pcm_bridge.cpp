#include "g1_companion_pcm.hpp"

#include <json/json.h>
#include <unitree/common/time/sleep.hpp>
#include <unitree/common/time/time_tool.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/g1/audio/g1_audio_client.hpp>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <csignal>
#include <exception>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <string>
#include <string_view>
#include <vector>
#include <unistd.h>

namespace {

constexpr int kDomain = 0;
constexpr char kInterface[] = "enp3s0";
constexpr char kAppName[] = "companion_pcm";
constexpr float kRpcTimeoutSeconds = 3.0F;
constexpr std::size_t kChunkBytes = 96000;

static_assert(std::atomic<bool>::is_always_lock_free);
std::atomic<bool> stop_requested{false};
void RequestStop(int) noexcept { stop_requested.store(true, std::memory_order_relaxed); }

class CompanionAudioClient final : public unitree::robot::g1::AudioClient {
 public:
  std::int32_t StopStream(const std::string& app_name) {
    unitree::robot::g1::PlayStopParameter parameter;
    parameter.app_name = app_name;
    std::string response;
    // The pinned SDK PlayStop discards Call's status; preserve it in this adapter.
    return Call(unitree::robot::g1::ROBOT_API_ID_AUDIO_STOP_PLAY,
                unitree::common::ToJsonString(parameter), response);
  }
};

void PrintJson(const Json::Value& value) {
  Json::StreamWriterBuilder builder;
  builder["indentation"] = "";
  std::cout << Json::writeString(builder, value) << '\n' << std::flush;
}

std::optional<g1::CompanionPcmWav> ReadPcmWav(std::string_view path) {
  std::ifstream input(std::string{path}, std::ios::binary | std::ios::ate);
  if (!input) return std::nullopt;
  const auto size = input.tellg();
  if (size <= 0 || static_cast<std::uintmax_t>(size) >
                       g1::kCompanionPcmMaxBytes + 4096U) {
    return std::nullopt;
  }
  input.seekg(0);
  std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(input)),
                                  std::istreambuf_iterator<char>());
  return g1::ParseCompanionPcmWav(bytes);
}

Json::Value BaseResult(std::string_view path, const g1::CompanionPcmWav& wav) {
  Json::Value result;
  result["kind"] = "g1_companion_pcm_bridge";
  result["domain"] = kDomain;
  result["interface"] = kInterface;
  result["app_name"] = kAppName;
  result["wav_path"] = std::string{path};
  result["pcm_bytes"] = Json::UInt64(wav.pcm.size());
  result["duration_milliseconds"] = Json::UInt64(wav.duration_milliseconds);
  return result;
}

int DryRun(std::string_view path, const g1::CompanionPcmWav& wav) {
  auto result = BaseResult(path, wav);
  result["status"] = "dry_run";
  result["physical_actions_emitted"] = 0;
  PrintJson(result);
  return 0;
}

int Play(std::string_view path, const g1::CompanionPcmWav& wav, bool interruptible) {
  bool factory_initialized = false;
  std::unique_ptr<CompanionAudioClient> client;
  try {
    unitree::robot::ChannelFactory::Instance()->Init(kDomain, kInterface);
    factory_initialized = true;
    client = std::make_unique<CompanionAudioClient>();
    client->SetTimeout(kRpcTimeoutSeconds);
    client->Init();

    const std::string stream_id =
        std::to_string(unitree::common::GetCurrentTimeMillisecond());
    const std::string app_name = interruptible
        ? std::string{kAppName} + "_" + stream_id + "_" + std::to_string(getpid()) : kAppName;
    if (interruptible) {
      auto ready = BaseResult(path, wav);
      ready["app_name"] = app_name;
      ready["status"] = "ready";
      PrintJson(ready);
    }
    const auto playback = g1::PlayCompanionPcm(
        wav.pcm, kChunkBytes,
        [&](const auto& pcm) { return client->PlayStream(app_name, stream_id, pcm); },
        [&] { return client->StopStream(app_name); },
        [](int milliseconds) { unitree::common::MilliSleep(milliseconds); },
        [interruptible] { return interruptible && stop_requested.load(std::memory_order_relaxed); });
    client.reset();
    unitree::robot::ChannelFactory::Instance()->Release();
    factory_initialized = false;

    auto result = BaseResult(path, wav);
    result["app_name"] = app_name;
    result["status"] = playback.play_result == 0 && playback.stop_result == 0
        ? (playback.interrupted ? "interrupted" : "completed") : "failed";
    result["stream_id"] = stream_id;
    result["play_result"] = playback.play_result;
    result["stop_result"] = playback.stop_result;
    result["pcm_bytes_sent"] = Json::UInt64(playback.pcm_bytes_sent);
    if (result["status"].asString() == "failed") result["error_code"] = "pcm_play_failed";
    PrintJson(result);
    return result["status"].asString() == "failed" ? 2 : 0;
  } catch (...) {
    client.reset();
    if (factory_initialized) unitree::robot::ChannelFactory::Instance()->Release();
    throw;
  }
}

}  // namespace

int main(int argc, char** argv) {
  const bool dry_run = argc == 3 && std::string_view{argv[1]} == "--dry-run";
  const bool confirmed = argc == 3 &&
                         std::string_view{argv[1]} == "--confirm-g1-companion-pcm";
  const bool interruptible = argc == 4 &&
      std::string_view{argv[1]} == "--confirm-g1-companion-pcm" &&
      std::string_view{argv[2]} == "--allow-interrupt";
  if (!dry_run && !confirmed && !interruptible) {
    Json::Value result;
    result["kind"] = "g1_companion_pcm_bridge";
    result["status"] = "failed";
    result["error_code"] = "expected_confirmed_wav_path";
    result["usage"] = "--dry-run <wav-path> | --confirm-g1-companion-pcm <wav-path>";
    PrintJson(result);
    return 64;
  }
  const auto wav = ReadPcmWav(argv[argc - 1]);
  if (!wav) {
    Json::Value result;
    result["kind"] = "g1_companion_pcm_bridge";
    result["status"] = "failed";
    result["error_code"] = "wav_format_invalid";
    PrintJson(result);
    return 64;
  }
  if (dry_run) return DryRun(argv[2], *wav);
  if (interruptible && std::signal(SIGUSR1, RequestStop) == SIG_ERR) return 70;
  try {
    return Play(argv[argc - 1], *wav, interruptible);
  } catch (const std::exception& error) {
    Json::Value result;
    result["kind"] = "g1_companion_pcm_bridge";
    result["status"] = "failed";
    result["error_code"] = "sdk_exception";
    result["reason"] = error.what();
    PrintJson(result);
    return 70;
  }
}
