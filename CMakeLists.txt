cmake_minimum_required(VERSION 3.16)
project(g1_dex3_care_vla LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(UNITREE_SDK2_ROOT "/home/user/github-product/unitree_sdk2" CACHE PATH
    "Official unitree_sdk2 checkout")
set(UNITREE_ARCH "x86_64" CACHE STRING "unitree_sdk2 library architecture")

find_package(Threads REQUIRED)
find_package(PkgConfig REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
pkg_check_modules(JSONCPP REQUIRED IMPORTED_TARGET jsoncpp)

add_library(g1_intent_core src/g1_intent.cpp)
target_include_directories(g1_intent_core PUBLIC src)
target_compile_options(g1_intent_core PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_intent_core PRIVATE PkgConfig::JSONCPP)

add_library(g1_command_runtime_core src/g1_command_runtime.cpp)
target_include_directories(g1_command_runtime_core PUBLIC src)
target_compile_options(g1_command_runtime_core PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_command_runtime_core PRIVATE
  g1_intent_core
  PkgConfig::JSONCPP
)

add_library(g1_runtime_core src/g1_runtime.cpp)
target_include_directories(g1_runtime_core PUBLIC src)
target_compile_options(g1_runtime_core PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_runtime_core PRIVATE
  g1_command_runtime_core
  PkgConfig::JSONCPP
)

add_library(g1_care_task_core src/g1_care_task.cpp)
target_include_directories(g1_care_task_core PUBLIC src)
target_compile_options(g1_care_task_core PRIVATE -Wall -Wextra -Werror)

add_library(g1_dex3_command_core src/g1_dex3_command_core.cpp)
target_include_directories(g1_dex3_command_core PUBLIC src)
target_compile_options(g1_dex3_command_core PRIVATE -Wall -Wextra -Werror)

add_library(g1_dex3_log_replay_core src/g1_dex3_log_replay.cpp)
target_include_directories(g1_dex3_log_replay_core PUBLIC src)
target_compile_options(g1_dex3_log_replay_core PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_dex3_log_replay_core PRIVATE
  g1_dex3_command_core
  PkgConfig::JSONCPP
)

add_library(g1_dex3_episode_log_core src/g1_dex3_episode_log.cpp)
target_include_directories(g1_dex3_episode_log_core PUBLIC src)
target_compile_options(g1_dex3_episode_log_core PRIVATE -Wall -Wextra -Werror)

add_library(g1_dex3_readonly_diagnostic_core src/g1_dex3_readonly_diagnostic.cpp)
target_include_directories(g1_dex3_readonly_diagnostic_core PUBLIC src)
target_compile_options(g1_dex3_readonly_diagnostic_core PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_dex3_readonly_diagnostic_core PUBLIC PkgConfig::JSONCPP)

add_library(g1_dex3_touch_demo_record_core src/g1_dex3_touch_demo_record.cpp)
target_include_directories(g1_dex3_touch_demo_record_core PUBLIC src)
target_compile_options(g1_dex3_touch_demo_record_core PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_dex3_touch_demo_record_core PUBLIC PkgConfig::JSONCPP)

add_library(g1_state_monitor_core src/g1_state_monitor.cpp)
target_include_directories(g1_state_monitor_core PUBLIC src)
target_compile_options(g1_state_monitor_core PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_state_monitor_core PUBLIC Threads::Threads)

# SDK-R3: hardware-free 24D source fusion; the DDS executable below is only a
# protocol adapter and never owns layout or time-alignment semantics.
add_library(g1_upper_body_observation_core src/g1_upper_body_observation.cpp)
target_include_directories(g1_upper_body_observation_core PUBLIC src)
target_compile_options(g1_upper_body_observation_core PRIVATE -Wall -Wextra -Werror)

# SDK-R3: hardware-free 24D Action/Execution/runtime owner. Unitree/DDS stays
# below the adapter in the production transport targets declared below.
add_library(g1_upper_body_execution_core src/g1_upper_body_execution.cpp)
target_include_directories(g1_upper_body_execution_core PUBLIC src)
target_compile_options(g1_upper_body_execution_core PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_upper_body_execution_core PUBLIC
  g1_upper_body_observation_core)

add_library(g1_upper_body_runtime_codec_core
  src/g1_upper_body_runtime_codec.cpp)
target_include_directories(g1_upper_body_runtime_codec_core PUBLIC src)
target_compile_options(g1_upper_body_runtime_codec_core PRIVATE
  -Wall -Wextra -Werror)
target_link_libraries(g1_upper_body_runtime_codec_core PUBLIC
  g1_upper_body_execution_core
  PkgConfig::JSONCPP)

add_library(g1_upper_body_unitree_adapter_core
  src/g1_upper_body_unitree_adapter.cpp)
target_include_directories(g1_upper_body_unitree_adapter_core PUBLIC src)
target_compile_options(g1_upper_body_unitree_adapter_core PRIVATE
  -Wall -Wextra -Werror)
target_link_libraries(g1_upper_body_unitree_adapter_core PUBLIC
  g1_upper_body_execution_core
  g1_robot_capability_profile_core
  g1_dex3_command_core)

add_library(g1_upper_body_functional_24d_smoke_plan_core
  src/g1_upper_body_functional_24d_smoke_plan.cpp)
target_include_directories(g1_upper_body_functional_24d_smoke_plan_core
  PUBLIC src)
target_compile_options(g1_upper_body_functional_24d_smoke_plan_core PRIVATE
  -Wall -Wextra -Werror)
target_link_libraries(g1_upper_body_functional_24d_smoke_plan_core PUBLIC
  g1_upper_body_unitree_adapter_core)

add_library(g1_upper_body_unitree_transport_core
  src/g1_upper_body_unitree_transport.cpp)
target_include_directories(g1_upper_body_unitree_transport_core PUBLIC src)
target_compile_options(g1_upper_body_unitree_transport_core PRIVATE
  -Wall -Wextra -Werror)
target_link_libraries(g1_upper_body_unitree_transport_core PUBLIC
  g1_upper_body_unitree_adapter_core)

add_library(g1_sport_mode_state_core src/g1_sport_mode_state.cpp)
target_include_directories(g1_sport_mode_state_core PUBLIC src)
target_compile_options(g1_sport_mode_state_core PRIVATE -Wall -Wextra -Werror)

add_library(g1_upper_body_unitree_sdk_io
  src/g1_upper_body_unitree_sdk_io.cpp)
target_include_directories(g1_upper_body_unitree_sdk_io PUBLIC src)
target_include_directories(g1_upper_body_unitree_sdk_io SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_upper_body_unitree_sdk_io PRIVATE
  -Wall -Wextra -Werror)
target_link_libraries(g1_upper_body_unitree_sdk_io PUBLIC
  g1_upper_body_unitree_transport_core
  g1_sport_mode_state_core
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_upper_body_unitree_sdk_io PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_library(g1_package_version_readonly_core src/g1_package_version_readonly.cpp)
target_include_directories(g1_package_version_readonly_core PUBLIC src)
target_compile_options(g1_package_version_readonly_core PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_package_version_readonly_core PUBLIC PkgConfig::JSONCPP)

add_library(g1_official_asr_core src/g1_official_asr.cpp)
target_include_directories(g1_official_asr_core PUBLIC src)
target_compile_options(g1_official_asr_core PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_official_asr_core PUBLIC PkgConfig::JSONCPP)

add_executable(g1_state_monitor src/g1_state_monitor_main.cpp)
target_include_directories(g1_state_monitor PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)

add_executable(g1_sport_mode_readonly src/g1_sport_mode_readonly_main.cpp)
target_include_directories(g1_sport_mode_readonly SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_sport_mode_readonly PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_sport_mode_readonly PRIVATE
  g1_sport_mode_state_core
  Threads::Threads
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_sport_mode_readonly PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_package_version_readonly src/g1_package_version_readonly_main.cpp)
target_include_directories(g1_package_version_readonly SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_package_version_readonly PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_package_version_readonly PRIVATE
  g1_package_version_readonly_core
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_package_version_readonly PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_official_asr_probe src/g1_official_asr_probe.cpp)
target_include_directories(g1_official_asr_probe SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_official_asr_probe PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_official_asr_probe PRIVATE
  g1_official_asr_core
  Threads::Threads
  PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_official_asr_probe PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_tts_probe src/g1_tts_probe.cpp)
target_include_directories(g1_tts_probe SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_tts_probe PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_tts_probe PRIVATE
  g1_official_asr_core
  Threads::Threads
  PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_tts_probe PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_tts_phrase_bridge src/g1_tts_phrase_bridge.cpp)
target_include_directories(g1_tts_phrase_bridge PRIVATE src)
target_include_directories(g1_tts_phrase_bridge SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_tts_phrase_bridge PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_tts_phrase_bridge PRIVATE
  g1_official_asr_core
  Threads::Threads
  PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_tts_phrase_bridge PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_companion_tts_phrase_bridge
  src/g1_companion_tts_phrase_bridge.cpp)
target_include_directories(g1_companion_tts_phrase_bridge PRIVATE src)
target_include_directories(g1_companion_tts_phrase_bridge SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_companion_tts_phrase_bridge PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_companion_tts_phrase_bridge PRIVATE
  g1_official_asr_core
  Threads::Threads
  PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_companion_tts_phrase_bridge PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_companion_pcm_bridge src/g1_companion_pcm_bridge.cpp)
target_include_directories(g1_companion_pcm_bridge PRIVATE src)
target_include_directories(g1_companion_pcm_bridge SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_companion_pcm_bridge PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_companion_pcm_bridge PRIVATE
  PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_companion_pcm_bridge PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_companion_led_demo src/g1_companion_led_demo.cpp)
target_include_directories(g1_companion_led_demo PRIVATE src)
target_include_directories(g1_companion_led_demo SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_companion_led_demo PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(g1_companion_led_demo PRIVATE
  G1_LED_SDK_CHECK_SCRIPT="${CMAKE_SOURCE_DIR}/scripts/g1_companion_led_test.sh"
)
target_link_libraries(g1_companion_led_demo PRIVATE
  Threads::Threads PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_companion_led_demo PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_audio_volume_probe src/g1_audio_volume_probe.cpp)
target_include_directories(g1_audio_volume_probe PRIVATE src)
target_include_directories(g1_audio_volume_probe SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_audio_volume_probe PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_audio_volume_probe PRIVATE
  PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_audio_volume_probe PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_voice_wake_mode src/g1_voice_wake_mode.cpp)
target_include_directories(g1_voice_wake_mode PRIVATE src)
target_include_directories(g1_voice_wake_mode SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_voice_wake_mode PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_voice_wake_mode PRIVATE
  PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_voice_wake_mode PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_right_arm_service_roundtrip
  src/g1_right_arm_service_roundtrip_main.cpp)
target_include_directories(g1_right_arm_service_roundtrip SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_right_arm_service_roundtrip PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_right_arm_service_roundtrip PRIVATE
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_right_arm_service_roundtrip PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_right_arm_current_pose_hold src/g1_right_arm_current_pose_hold_main.cpp)
target_include_directories(g1_right_arm_current_pose_hold SYSTEM PRIVATE "${UNITREE_SDK2_ROOT}/include" "${UNITREE_SDK2_ROOT}/thirdparty/include" "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx")
target_include_directories(g1_right_arm_current_pose_hold PRIVATE src)
target_compile_options(g1_right_arm_current_pose_hold PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(g1_right_arm_current_pose_hold PRIVATE G1_RIGHT_ARM_CURRENT_POSE_HOLD)
target_link_libraries(g1_right_arm_current_pose_hold PRIVATE g1_dex3_episode_log_core g1_sport_mode_state_core PkgConfig::JSONCPP "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so")
set_target_properties(g1_right_arm_current_pose_hold PROPERTIES BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}")

add_executable(g1_right_arm_single_joint_microstep src/g1_right_arm_current_pose_hold_main.cpp)
target_include_directories(g1_right_arm_single_joint_microstep SYSTEM PRIVATE "${UNITREE_SDK2_ROOT}/include" "${UNITREE_SDK2_ROOT}/thirdparty/include" "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx")
target_include_directories(g1_right_arm_single_joint_microstep PRIVATE src)
target_compile_options(g1_right_arm_single_joint_microstep PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(g1_right_arm_single_joint_microstep PRIVATE G1_RIGHT_ARM_SINGLE_JOINT_MICROSTEP)
target_link_libraries(g1_right_arm_single_joint_microstep PRIVATE g1_dex3_episode_log_core g1_sport_mode_state_core PkgConfig::JSONCPP "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so")
set_target_properties(g1_right_arm_single_joint_microstep PROPERTIES BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}")

add_executable(g1_right_wrist_roll_microstep_hold src/g1_right_arm_current_pose_hold_main.cpp)
target_include_directories(g1_right_wrist_roll_microstep_hold SYSTEM PRIVATE "${UNITREE_SDK2_ROOT}/include" "${UNITREE_SDK2_ROOT}/thirdparty/include" "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx")
target_include_directories(g1_right_wrist_roll_microstep_hold PRIVATE src)
target_compile_options(g1_right_wrist_roll_microstep_hold PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(g1_right_wrist_roll_microstep_hold PRIVATE G1_RIGHT_WRIST_ROLL_MICROSTEP_HOLD)
target_link_libraries(g1_right_wrist_roll_microstep_hold PRIVATE g1_dex3_episode_log_core g1_sport_mode_state_core PkgConfig::JSONCPP "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so")
set_target_properties(g1_right_wrist_roll_microstep_hold PROPERTIES BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}")

add_executable(g1_right_arm_full_packet_microstep src/g1_right_arm_current_pose_hold_main.cpp)
target_include_directories(g1_right_arm_full_packet_microstep SYSTEM PRIVATE "${UNITREE_SDK2_ROOT}/include" "${UNITREE_SDK2_ROOT}/thirdparty/include" "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx")
target_include_directories(g1_right_arm_full_packet_microstep PRIVATE src)
target_compile_options(g1_right_arm_full_packet_microstep PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(g1_right_arm_full_packet_microstep PRIVATE G1_RIGHT_ARM_FULL_PACKET_MICROSTEP)
target_link_libraries(g1_right_arm_full_packet_microstep PRIVATE g1_dex3_episode_log_core g1_sport_mode_state_core PkgConfig::JSONCPP "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so")
set_target_properties(g1_right_arm_full_packet_microstep PROPERTIES BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}")

add_executable(g1_right_arm_lifecycle_microstep src/g1_right_arm_current_pose_hold_main.cpp)
target_include_directories(g1_right_arm_lifecycle_microstep SYSTEM PRIVATE "${UNITREE_SDK2_ROOT}/include" "${UNITREE_SDK2_ROOT}/thirdparty/include" "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx")
target_include_directories(g1_right_arm_lifecycle_microstep PRIVATE src)
target_compile_options(g1_right_arm_lifecycle_microstep PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(g1_right_arm_lifecycle_microstep PRIVATE G1_RIGHT_ARM_LIFECYCLE_MICROSTEP)
target_link_libraries(g1_right_arm_lifecycle_microstep PRIVATE g1_dex3_episode_log_core g1_sport_mode_state_core PkgConfig::JSONCPP "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so")
set_target_properties(g1_right_arm_lifecycle_microstep PROPERTIES BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}")

add_executable(g1_dual_arm_teleop_smoke src/g1_right_arm_current_pose_hold_main.cpp)
target_include_directories(g1_dual_arm_teleop_smoke SYSTEM PRIVATE "${UNITREE_SDK2_ROOT}/include" "${UNITREE_SDK2_ROOT}/thirdparty/include" "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx")
target_include_directories(g1_dual_arm_teleop_smoke PRIVATE src)
target_compile_options(g1_dual_arm_teleop_smoke PRIVATE -Wall -Wextra -Werror)
target_compile_definitions(g1_dual_arm_teleop_smoke PRIVATE G1_RIGHT_ARM_CONTINUOUS_POSITION_MICROTRAJECTORY)
target_link_libraries(g1_dual_arm_teleop_smoke PRIVATE g1_dex3_episode_log_core g1_sport_mode_state_core PkgConfig::JSONCPP "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so")
set_target_properties(g1_dual_arm_teleop_smoke PROPERTIES BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}")

add_executable(g1_arm_action_forward_release src/g1_arm_action_forward_release_main.cpp)
target_include_directories(g1_arm_action_forward_release SYSTEM PRIVATE "${UNITREE_SDK2_ROOT}/include" "${UNITREE_SDK2_ROOT}/thirdparty/include" "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx")
target_compile_options(g1_arm_action_forward_release PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_arm_action_forward_release PRIVATE "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so" "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so")
set_target_properties(g1_arm_action_forward_release PROPERTIES BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}")

add_executable(g1_dex3_state_monitor src/g1_dex3_state_monitor_main.cpp)
target_include_directories(g1_dex3_state_monitor SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_dex3_state_monitor PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_dex3_state_monitor PRIVATE
  PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_dex3_state_monitor PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_upper_body_observation_monitor
  src/g1_upper_body_observation_main.cpp)
target_include_directories(g1_upper_body_observation_monitor SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_upper_body_observation_monitor PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_upper_body_observation_monitor PRIVATE
  g1_upper_body_observation_core
  PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_upper_body_observation_monitor PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_upper_body_runtime src/g1_upper_body_runtime_main.cpp)
target_compile_definitions(g1_upper_body_runtime PRIVATE
  G1_SOURCE_DIR="${CMAKE_SOURCE_DIR}")
target_compile_options(g1_upper_body_runtime PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_upper_body_runtime PRIVATE
  g1_upper_body_unitree_sdk_io
  g1_upper_body_functional_24d_smoke_plan_core
  g1_upper_body_runtime_codec_core
  PkgConfig::JSONCPP)
set_target_properties(g1_upper_body_runtime PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_dex3_right_readonly_diagnostic
  src/g1_dex3_right_readonly_diagnostic_main.cpp)
target_include_directories(g1_dex3_right_readonly_diagnostic SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_dex3_right_readonly_diagnostic PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_dex3_right_readonly_diagnostic PRIVATE
  g1_dex3_readonly_diagnostic_core
  g1_dex3_episode_log_core
  PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_dex3_right_readonly_diagnostic PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_dex3_right_touch_demo_record
  src/g1_dex3_right_touch_demo_record_main.cpp)
target_include_directories(g1_dex3_right_touch_demo_record SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_dex3_right_touch_demo_record PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_dex3_right_touch_demo_record PRIVATE
  g1_dex3_touch_demo_record_core
  g1_dex3_episode_log_core
  PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_dex3_right_touch_demo_record PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_dex3_log_replay src/g1_dex3_log_replay_main.cpp)
target_compile_options(g1_dex3_log_replay PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_dex3_log_replay PRIVATE g1_dex3_log_replay_core)

function(add_g1_dex3_right_publisher target)
  add_executable(${target} src/g1_dex3_right_hold_main.cpp)
  target_include_directories(${target} SYSTEM PRIVATE
    "${UNITREE_SDK2_ROOT}/include"
    "${UNITREE_SDK2_ROOT}/thirdparty/include"
    "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
  )
  target_compile_options(${target} PRIVATE -Wall -Wextra -Werror)
  target_link_libraries(${target} PRIVATE
    g1_dex3_command_core
    g1_dex3_episode_log_core
    PkgConfig::JSONCPP
    "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
    "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
    "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
  )
  set_target_properties(${target} PROPERTIES
    BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
  )
endfunction()

add_g1_dex3_right_publisher(g1_dex3_right_hold)
add_g1_dex3_right_publisher(g1_dex3_right_thumb_microstep)
target_compile_definitions(g1_dex3_right_thumb_microstep PRIVATE
  G1_DEX3_RIGHT_THUMB_MICROSTEP=1
)
add_g1_dex3_right_publisher(g1_dex3_right_thumb_microstep_100hz)
target_compile_definitions(g1_dex3_right_thumb_microstep_100hz PRIVATE
  G1_DEX3_RIGHT_THUMB_MICROSTEP=1
  G1_DEX3_RIGHT_THUMB_MICROSTEP_100HZ=1
)
add_g1_dex3_right_publisher(g1_dex3_right_thumb_0_negative_probe_100hz)
target_compile_definitions(g1_dex3_right_thumb_0_negative_probe_100hz PRIVATE
  G1_DEX3_RIGHT_THUMB_NEGATIVE_PROBE_100HZ=1
)
add_g1_dex3_right_publisher(g1_dex3_right_whole_hand_microstep_100hz)
target_compile_definitions(g1_dex3_right_whole_hand_microstep_100hz PRIVATE
  G1_DEX3_RIGHT_WHOLE_HAND_MICROSTEP_100HZ=1
)
add_g1_dex3_right_publisher(g1_dex3_right_whole_hand_visible_100hz)
target_compile_definitions(g1_dex3_right_whole_hand_visible_100hz PRIVATE
  G1_DEX3_RIGHT_WHOLE_HAND_VISIBLE_100HZ=1
)
add_g1_dex3_right_publisher(g1_dex3_right_whole_hand_close_return_100hz)
target_compile_definitions(g1_dex3_right_whole_hand_close_return_100hz PRIVATE
  G1_DEX3_RIGHT_WHOLE_HAND_CLOSE_RETURN_100HZ=1
)
add_g1_dex3_right_publisher(g1_dex3_right_whole_hand_close_hold_return_100hz)
target_compile_definitions(g1_dex3_right_whole_hand_close_hold_return_100hz PRIVATE
  G1_DEX3_RIGHT_WHOLE_HAND_CLOSE_HOLD_RETURN_100HZ=1
)
add_g1_dex3_right_publisher(g1_dex3_right_whole_hand_return_grip_gain_100hz)
target_compile_definitions(g1_dex3_right_whole_hand_return_grip_gain_100hz PRIVATE
  G1_DEX3_RIGHT_WHOLE_HAND_CLOSE_HOLD_RETURN_100HZ=1
  G1_DEX3_RIGHT_WHOLE_HAND_RETURN_GRIP_GAIN_100HZ=1
)
add_g1_dex3_right_publisher(g1_dex3_left_whole_hand_basic_action_return_100hz)
target_compile_definitions(g1_dex3_left_whole_hand_basic_action_return_100hz PRIVATE
  G1_DEX3_LEFT_WHOLE_HAND_BASIC_ACTION_RETURN_100HZ=1
)
add_g1_dex3_right_publisher(g1_dex3_left_whole_hand_return_grip_gain_100hz)
target_compile_definitions(g1_dex3_left_whole_hand_return_grip_gain_100hz PRIVATE
  G1_DEX3_LEFT_WHOLE_HAND_RETURN_GRIP_GAIN_100HZ=1
)
add_g1_dex3_right_publisher(g1_dex3_right_index_0_visual_map_100hz)
target_compile_definitions(g1_dex3_right_index_0_visual_map_100hz PRIVATE
  G1_DEX3_RIGHT_INDEX_0_VISUAL_MAP_100HZ=1
)
target_link_libraries(g1_dex3_right_index_0_visual_map_100hz PRIVATE
  g1_sport_mode_state_core
  Threads::Threads
)
target_compile_options(g1_state_monitor PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_state_monitor PRIVATE
  g1_state_monitor_core
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_state_monitor PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_intent_cli src/g1_intent_cli.cpp)
target_include_directories(g1_intent_cli SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_intent_cli PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_intent_cli PRIVATE
  g1_intent_core
  PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_intent_cli PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_command_runtime_cli src/g1_sdk_runtime_main.cpp)
target_include_directories(g1_command_runtime_cli SYSTEM PRIVATE
  "${UNITREE_SDK2_ROOT}/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include"
  "${UNITREE_SDK2_ROOT}/thirdparty/include/ddscxx"
)
target_compile_options(g1_command_runtime_cli PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_command_runtime_cli PRIVATE
  g1_runtime_core
  PkgConfig::JSONCPP
  "${UNITREE_SDK2_ROOT}/lib/${UNITREE_ARCH}/libunitree_sdk2.a"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddscxx.so"
  "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}/libddsc.so"
)
set_target_properties(g1_command_runtime_cli PROPERTIES
  BUILD_RPATH "${UNITREE_SDK2_ROOT}/thirdparty/lib/${UNITREE_ARCH}"
)

add_executable(g1_chinese_command_cli src/g1_chinese_command_cli.cpp)
target_compile_options(g1_chinese_command_cli PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_chinese_command_cli PRIVATE
  g1_intent_core
  PkgConfig::JSONCPP
)

enable_testing()
add_executable(g1_state_monitor_test tests/g1_state_monitor_test.cpp)
target_compile_options(g1_state_monitor_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_state_monitor_test PRIVATE g1_state_monitor_core)
add_test(NAME g1_state_monitor_core COMMAND g1_state_monitor_test)

add_executable(g1_upper_body_observation_test
  tests/g1_upper_body_observation_test.cpp)
target_compile_options(g1_upper_body_observation_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_upper_body_observation_test PRIVATE
  g1_upper_body_observation_core)
add_test(NAME g1_upper_body_observation_core
  COMMAND g1_upper_body_observation_test)
add_test(NAME g1_upper_body_observation_invalid_cli
  COMMAND g1_upper_body_observation_monitor --duration 0)
set_tests_properties(g1_upper_body_observation_invalid_cli PROPERTIES WILL_FAIL TRUE)

add_executable(g1_upper_body_execution_test
  tests/g1_upper_body_execution_test.cpp)
target_compile_options(g1_upper_body_execution_test PRIVATE
  -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_upper_body_execution_test PRIVATE
  g1_upper_body_execution_core)
add_test(NAME g1_upper_body_execution_core
  COMMAND g1_upper_body_execution_test)

add_executable(g1_upper_body_functional_24d_smoke_plan_test
  tests/g1_upper_body_functional_24d_smoke_plan_test.cpp)
target_compile_options(g1_upper_body_functional_24d_smoke_plan_test PRIVATE
  -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_upper_body_functional_24d_smoke_plan_test PRIVATE
  g1_upper_body_functional_24d_smoke_plan_core)
add_test(NAME g1_upper_body_functional_24d_smoke_plan
  COMMAND g1_upper_body_functional_24d_smoke_plan_test)

add_executable(g1_upper_body_runtime_codec_test
  tests/g1_upper_body_runtime_codec_test.cpp)
target_compile_options(g1_upper_body_runtime_codec_test PRIVATE
  -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_upper_body_runtime_codec_test PRIVATE
  g1_upper_body_runtime_codec_core
  PkgConfig::JSONCPP)
add_test(NAME g1_upper_body_runtime_codec_core
  COMMAND g1_upper_body_runtime_codec_test)
add_executable(g1_upper_body_unitree_adapter_test
  tests/g1_upper_body_unitree_adapter_test.cpp)
target_compile_options(g1_upper_body_unitree_adapter_test PRIVATE
  -Wall -Wextra -Werror -UNDEBUG)
target_compile_definitions(g1_upper_body_unitree_adapter_test PRIVATE
  G1_SOURCE_DIR="${CMAKE_SOURCE_DIR}")
target_link_libraries(g1_upper_body_unitree_adapter_test PRIVATE
  g1_upper_body_functional_24d_smoke_plan_core)
add_test(NAME g1_upper_body_unitree_adapter_core
  COMMAND g1_upper_body_unitree_adapter_test)
add_executable(g1_upper_body_unitree_transport_test
  tests/g1_upper_body_unitree_transport_test.cpp)
target_compile_options(g1_upper_body_unitree_transport_test PRIVATE
  -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_upper_body_unitree_transport_test PRIVATE
  g1_upper_body_unitree_transport_core)
add_test(NAME g1_upper_body_unitree_transport_core
  COMMAND g1_upper_body_unitree_transport_test)
add_test(NAME g1_upper_body_runtime_no_confirm
  COMMAND "${CMAKE_COMMAND}"
    "-DPROGRAM=$<TARGET_FILE:g1_upper_body_runtime>"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_64.cmake")
add_test(NAME g1_upper_body_runtime_invalid_confirm
  COMMAND /bin/bash -c
    "output=\"$($1 --confirm-upper-body-functional-24d-smoke-typo 2>&1)\"; code=$?; test \"$code\" -eq 64 && grep -q -- \"$2\" <<< \"$output\" && grep -q -- \"$3\" <<< \"$output\" && grep -q -- \"$4\" <<< \"$output\" && grep -q -- \"$5\" <<< \"$output\""
    _
    $<TARGET_FILE:g1_upper_body_runtime>
    --confirm-upper-body-transport-hold-smoke
    --confirm-upper-body-functional-24d-smoke
    --confirm-upper-body-policy-first-frame
    --confirm-upper-body-policy-bounded-run)
add_test(NAME g1_dex3_left_whole_hand_basic_action_return_requires_confirmation
  COMMAND /bin/bash -c
    "output=\"$($1 2>&1)\"; code=$?; test \"$code\" -eq 64 && grep -q -- \"$2\" <<< \"$output\""
    _
    $<TARGET_FILE:g1_dex3_left_whole_hand_basic_action_return_100hz>
    --confirm-left-whole-hand-basic-action-return-100hz)
add_test(NAME g1_dex3_left_whole_hand_return_grip_gain_requires_confirmation
  COMMAND /bin/bash -c
    "output=\"$($1 2>&1)\"; code=$?; test \"$code\" -eq 64 && grep -q -- \"$2\" <<< \"$output\""
    _
    $<TARGET_FILE:g1_dex3_left_whole_hand_return_grip_gain_100hz>
    --confirm-left-whole-hand-return-grip-gain-100hz)
add_test(NAME g1_dex3_right_whole_hand_return_grip_gain_requires_confirmation
  COMMAND /bin/bash -c
    "output=\"$($1 2>&1)\"; code=$?; test \"$code\" -eq 64 && grep -q -- \"$2\" <<< \"$output\""
    _
    $<TARGET_FILE:g1_dex3_right_whole_hand_return_grip_gain_100hz>
    --confirm-right-whole-hand-return-grip-gain-100hz)

add_executable(g1_right_arm_hold_core_test tests/g1_right_arm_hold_core_test.cpp)
target_include_directories(g1_right_arm_hold_core_test PRIVATE src)
target_compile_options(g1_right_arm_hold_core_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
add_test(NAME g1_right_arm_hold_core COMMAND g1_right_arm_hold_core_test)

add_executable(g1_right_arm_microstep_core_test tests/g1_right_arm_microstep_core_test.cpp)
target_include_directories(g1_right_arm_microstep_core_test PRIVATE src)
target_compile_options(g1_right_arm_microstep_core_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
add_test(NAME g1_right_arm_microstep_core COMMAND g1_right_arm_microstep_core_test)

add_executable(g1_sport_mode_state_test tests/g1_sport_mode_state_test.cpp)
target_compile_options(g1_sport_mode_state_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_sport_mode_state_test PRIVATE g1_sport_mode_state_core)
add_test(NAME g1_sport_mode_state_core COMMAND g1_sport_mode_state_test)
add_test(NAME g1_sport_mode_readonly_invalid_cli
  COMMAND g1_sport_mode_readonly --duration 0)
set_tests_properties(g1_sport_mode_readonly_invalid_cli PROPERTIES WILL_FAIL TRUE)
add_executable(g1_package_version_readonly_test tests/g1_package_version_readonly_test.cpp)
target_compile_options(g1_package_version_readonly_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_package_version_readonly_test PRIVATE
  g1_package_version_readonly_core
)
add_test(NAME g1_package_version_readonly_core COMMAND g1_package_version_readonly_test)
add_executable(g1_official_asr_test tests/g1_official_asr_test.cpp)
target_compile_options(g1_official_asr_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_official_asr_test PRIVATE g1_official_asr_core)
add_test(NAME g1_official_asr_core COMMAND g1_official_asr_test)
add_executable(g1_official_asr_probe_options_test
  tests/g1_official_asr_probe_options_test.cpp)
target_include_directories(g1_official_asr_probe_options_test PRIVATE src)
target_compile_options(g1_official_asr_probe_options_test PRIVATE
  -Wall -Wextra -Werror -UNDEBUG)
add_test(NAME g1_official_asr_probe_options
  COMMAND g1_official_asr_probe_options_test)
add_executable(g1_companion_led_test tests/g1_companion_led_test.cpp)
target_include_directories(g1_companion_led_test PRIVATE src)
target_compile_options(g1_companion_led_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
add_test(NAME g1_companion_led_core COMMAND g1_companion_led_test)
add_test(NAME g1_companion_led_dry_run COMMAND g1_companion_led_demo --dry-run 9)
add_test(NAME g1_companion_led_requires_confirmation
  COMMAND ${CMAKE_COMMAND}
    "-DPROGRAM=$<TARGET_FILE:g1_companion_led_demo>"
    -P "${CMAKE_SOURCE_DIR}/tests/assert_exit_64.cmake")

add_executable(g1_audio_volume_test tests/g1_audio_volume_test.cpp)
target_include_directories(g1_audio_volume_test PRIVATE src)
target_compile_options(g1_audio_volume_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
add_test(NAME g1_audio_volume_core COMMAND g1_audio_volume_test)
add_test(NAME g1_audio_volume_dry_run
  COMMAND g1_audio_volume_probe --dry-run 45)
add_test(NAME g1_audio_volume_requires_confirmation
  COMMAND ${CMAKE_COMMAND}
    "-DPROGRAM=$<TARGET_FILE:g1_audio_volume_probe>"
    -P "${CMAKE_SOURCE_DIR}/tests/assert_exit_64.cmake")
add_executable(g1_voice_wake_mode_test tests/g1_voice_wake_mode_test.cpp)
target_include_directories(g1_voice_wake_mode_test PRIVATE src)
target_compile_options(g1_voice_wake_mode_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_voice_wake_mode_test PRIVATE PkgConfig::JSONCPP)
add_test(NAME g1_voice_wake_mode_core COMMAND g1_voice_wake_mode_test)
add_test(NAME g1_voice_wake_mode_dry_run
  COMMAND /bin/bash -c
    "output=\"$($1 --dry-run 2>&1)\"; code=$?; test \"$code\" -eq 0 && grep -Fq '\"interface\":\"enp3s0\"' <<< \"$output\" && grep -Fq '\"target_mode\":1' <<< \"$output\""
    _
    $<TARGET_FILE:g1_voice_wake_mode>)
add_test(NAME g1_voice_wake_mode_requires_confirmation
  COMMAND ${CMAKE_COMMAND}
    "-DPROGRAM=$<TARGET_FILE:g1_voice_wake_mode>"
    -P "${CMAKE_SOURCE_DIR}/tests/assert_exit_64.cmake")
add_executable(g1_tts_phrase_test tests/g1_tts_phrase_test.cpp)
target_include_directories(g1_tts_phrase_test PRIVATE src)
target_compile_options(g1_tts_phrase_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
add_test(NAME g1_tts_phrase_core COMMAND g1_tts_phrase_test)
add_executable(g1_companion_tts_phrase_test tests/g1_companion_tts_phrase_test.cpp)
target_include_directories(g1_companion_tts_phrase_test PRIVATE src)
target_compile_options(g1_companion_tts_phrase_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
add_test(NAME g1_companion_tts_phrase_core COMMAND g1_companion_tts_phrase_test)
add_test(NAME g1_companion_tts_phrase_bridge_dry_run
  COMMAND /bin/bash -c
    "output=\"$($1 --dry-run companion_share_positive 2>&1)\"; code=$?; test \"$code\" -eq 0 && grep -Fq '\"interface\":\"enp3s0\"' <<< \"$output\""
    _
    $<TARGET_FILE:g1_companion_tts_phrase_bridge>)
add_test(NAME g1_companion_tts_phrase_bridge_requires_confirmation
  COMMAND "${CMAKE_COMMAND}"
    "-DPROGRAM=$<TARGET_FILE:g1_companion_tts_phrase_bridge>"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_64.cmake")
add_executable(g1_companion_pcm_test tests/g1_companion_pcm_test.cpp)
target_include_directories(g1_companion_pcm_test PRIVATE src)
target_compile_options(g1_companion_pcm_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
add_test(NAME g1_companion_pcm_core COMMAND g1_companion_pcm_test)
add_test(NAME g1_companion_pcm_requires_confirmation
  COMMAND "${CMAKE_COMMAND}"
    "-DPROGRAM=$<TARGET_FILE:g1_companion_pcm_bridge>"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_64.cmake")
add_test(NAME g1_package_version_readonly_invalid_cli
  COMMAND "${CMAKE_COMMAND}"
    "-DPROGRAM=$<TARGET_FILE:g1_package_version_readonly>"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_64.cmake")
add_test(NAME g1_right_arm_service_roundtrip_no_confirm
  COMMAND g1_right_arm_service_roundtrip)
set_tests_properties(g1_right_arm_service_roundtrip_no_confirm PROPERTIES
  WILL_FAIL TRUE)
add_test(NAME g1_right_arm_current_pose_hold_no_confirm COMMAND g1_right_arm_current_pose_hold)
set_tests_properties(g1_right_arm_current_pose_hold_no_confirm PROPERTIES WILL_FAIL TRUE)
add_test(NAME g1_right_arm_single_joint_microstep_no_confirm COMMAND g1_right_arm_single_joint_microstep)
set_tests_properties(g1_right_arm_single_joint_microstep_no_confirm PROPERTIES WILL_FAIL TRUE)
add_test(NAME g1_right_wrist_roll_microstep_hold_no_confirm COMMAND g1_right_wrist_roll_microstep_hold)
set_tests_properties(g1_right_wrist_roll_microstep_hold_no_confirm PROPERTIES WILL_FAIL TRUE)
add_test(NAME g1_right_arm_full_packet_microstep_no_confirm
  COMMAND "${CMAKE_COMMAND}"
    "-DPROGRAM=$<TARGET_FILE:g1_right_arm_full_packet_microstep>"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_64.cmake")
add_test(NAME g1_right_arm_lifecycle_microstep_no_confirm
  COMMAND "${CMAKE_COMMAND}"
    "-DPROGRAM=$<TARGET_FILE:g1_right_arm_lifecycle_microstep>"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_64.cmake")
add_test(NAME g1_dual_arm_teleop_smoke_no_confirm
  COMMAND "${CMAKE_COMMAND}"
    "-DPROGRAM=$<TARGET_FILE:g1_dual_arm_teleop_smoke>"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_64.cmake")
add_test(NAME g1_arm_action_forward_release_no_confirm
  COMMAND "${CMAKE_COMMAND}"
    "-DPROGRAM=$<TARGET_FILE:g1_arm_action_forward_release>"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_64.cmake")
add_executable(g1_intent_test tests/g1_intent_test.cpp)
target_compile_options(g1_intent_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_intent_test PRIVATE g1_intent_core)
add_test(NAME g1_intent_core COMMAND g1_intent_test)

add_executable(g1_command_runtime_test tests/g1_command_runtime_test.cpp)
target_compile_options(g1_command_runtime_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_command_runtime_test PRIVATE g1_command_runtime_core)
add_test(NAME g1_command_runtime_core COMMAND g1_command_runtime_test)

add_executable(g1_runtime_test tests/g1_runtime_test.cpp)
target_compile_options(g1_runtime_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_runtime_test PRIVATE g1_runtime_core)
add_test(NAME g1_runtime_core COMMAND g1_runtime_test)

add_executable(g1_care_task_test tests/g1_care_task_test.cpp)
target_compile_options(g1_care_task_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_care_task_test PRIVATE g1_care_task_core)
add_test(NAME g1_care_task_core COMMAND g1_care_task_test)

add_executable(g1_dex3_command_core_test tests/g1_dex3_command_core_test.cpp)
target_compile_options(g1_dex3_command_core_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_dex3_command_core_test PRIVATE g1_dex3_command_core)
add_test(NAME g1_dex3_command_core COMMAND g1_dex3_command_core_test)

add_executable(g1_dex3_log_replay_test tests/g1_dex3_log_replay_test.cpp)
target_compile_options(g1_dex3_log_replay_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_dex3_log_replay_test PRIVATE g1_dex3_log_replay_core PkgConfig::JSONCPP)
add_test(NAME g1_dex3_log_replay_core COMMAND g1_dex3_log_replay_test)

add_executable(g1_dex3_episode_log_test tests/g1_dex3_episode_log_test.cpp)
target_compile_options(g1_dex3_episode_log_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_dex3_episode_log_test PRIVATE g1_dex3_episode_log_core Threads::Threads)
add_test(NAME g1_dex3_episode_log_core COMMAND g1_dex3_episode_log_test)

add_executable(g1_dex3_readonly_diagnostic_test tests/g1_dex3_readonly_diagnostic_test.cpp)
target_compile_options(g1_dex3_readonly_diagnostic_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_dex3_readonly_diagnostic_test PRIVATE g1_dex3_readonly_diagnostic_core)
add_test(NAME g1_dex3_readonly_diagnostic_core COMMAND g1_dex3_readonly_diagnostic_test)

add_executable(g1_dex3_touch_demo_record_test tests/g1_dex3_touch_demo_record_test.cpp)
target_compile_options(g1_dex3_touch_demo_record_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(g1_dex3_touch_demo_record_test PRIVATE
g1_dex3_touch_demo_record_core)
add_test(NAME g1_dex3_touch_demo_record_core COMMAND g1_dex3_touch_demo_record_test)

add_test(NAME g1_dex3_right_readonly_diagnostic_no_confirm
  COMMAND g1_dex3_right_readonly_diagnostic)
set_tests_properties(g1_dex3_right_readonly_diagnostic_no_confirm PROPERTIES
  WILL_FAIL TRUE
)
add_test(NAME g1_dex3_right_touch_demo_record_no_confirm
  COMMAND "${CMAKE_COMMAND}"
    "-DPROGRAM=$<TARGET_FILE:g1_dex3_right_touch_demo_record>"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_64.cmake")
add_test(NAME g1_dex3_right_whole_hand_close_return_100hz_no_confirm
  COMMAND g1_dex3_right_whole_hand_close_return_100hz)
set_tests_properties(g1_dex3_right_whole_hand_close_return_100hz_no_confirm PROPERTIES
  WILL_FAIL TRUE
)
add_test(NAME g1_dex3_right_whole_hand_close_hold_return_100hz_no_confirm
  COMMAND g1_dex3_right_whole_hand_close_hold_return_100hz)
set_tests_properties(g1_dex3_right_whole_hand_close_hold_return_100hz_no_confirm PROPERTIES
  WILL_FAIL TRUE
)
add_test(NAME g1_dex3_right_index_0_visual_map_100hz_no_confirm
  COMMAND "${CMAKE_COMMAND}"
    "-DPROGRAM=$<TARGET_FILE:g1_dex3_right_index_0_visual_map_100hz>"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_64.cmake")

# Gate 11B: 只用 fake 相机离线验证帧记录、哈希和确认门禁；CTest 不访问 /dev/video*。
add_test(NAME g1_camera_episode_record
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_camera_episode_record_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_camera_episode_record.py"
)
add_test(NAME g1_front_rgb_episode_record
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_front_rgb_episode_record_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_front_rgb_episode_record.py"
)
add_test(NAME g1_elder_medication_tabletop_capture
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_elder_medication_tabletop_capture_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_elder_medication_tabletop_capture.py"
)
add_test(NAME g1_elder_medication_tabletop_annotation
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_elder_medication_tabletop_annotation_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_elder_medication_tabletop_annotation.py"
)
add_test(NAME g1_elder_medication_tabletop_state
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_elder_medication_tabletop_state_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_elder_medication_tabletop_state.py"
)
add_test(NAME g1_elder_medication_tabletop_presence
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_elder_medication_tabletop_presence_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_elder_medication_tabletop_presence.py"
)
add_test(NAME g1_elder_medication_tabletop_live
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_elder_medication_tabletop_live_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_elder_medication_tabletop_live.py"
)
add_test(NAME g1_official_audio_visual_demo
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_official_audio_visual_demo_test.py"
)
add_test(NAME g1_medication_competition_flow
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_medication_competition_flow_test.py"
)

# Gate 12: 只在临时 fixture 上验证逐帧 RGB—Dex3 对齐，不读取真实 episode 或连接 G1。
add_test(NAME g1_vla_frame_manifest
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_vla_frame_manifest_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_vla_frame_manifest.py"
)

# Gate 13: 固定历史 episode 的语义标签只在 fake manifest 上验证，不读取真实数据或 G1。
add_test(NAME g1_gate13_label_episode
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_gate13_label_episode_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_gate13_label_episode.py"
)

# Gate 14: 仅在 fake 前视 RGB episode 上验证黄色杯子人工观察标签；不接收组播或连接 DDS。
add_test(NAME g1_gate14_observation_label
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_gate14_observation_label_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_gate14_observation_label.py"
)

# Gate 36: 只用合成 BGR 图像验证黄色杯检测；不读取相机或连接 G1。
add_test(NAME g1_yellow_cup_detector
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_yellow_cup_detector_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_yellow_cup_detector.py"
)

add_executable(g1_runtime_demo tests/g1_runtime_demo.cpp)
target_compile_options(g1_runtime_demo PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_runtime_demo PRIVATE g1_runtime_core)

# SDK-R2: hardware-independent Observation/Action/ExecutionResult/Episode contract
# and fake/replay runtime. It intentionally does not link Unitree SDK or DDS.
add_library(g1_sdk_contract_runtime_core src/g1_sdk_contract_runtime.cpp)
target_include_directories(g1_sdk_contract_runtime_core PUBLIC src)
target_compile_options(g1_sdk_contract_runtime_core PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_sdk_contract_runtime_core PRIVATE PkgConfig::JSONCPP)

add_executable(g1_sdk_contract_runtime_test tests/g1_sdk_contract_runtime_test.cpp)
target_compile_options(g1_sdk_contract_runtime_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_compile_definitions(g1_sdk_contract_runtime_test PRIVATE
  G1_SOURCE_DIR="${CMAKE_SOURCE_DIR}"
  G1_BINARY_DIR="${CMAKE_CURRENT_BINARY_DIR}"
)
target_link_libraries(g1_sdk_contract_runtime_test PRIVATE
  g1_sdk_contract_runtime_core
  g1_robot_capability_profile_core
  PkgConfig::JSONCPP
)
add_test(NAME g1_sdk_contract_runtime_core COMMAND g1_sdk_contract_runtime_test)

# SDK-R1: machine-readable capability facts for future RobotCommandPort preflight.
add_library(g1_robot_capability_profile_core src/g1_robot_capability_profile.cpp)
target_include_directories(g1_robot_capability_profile_core PUBLIC src)
target_compile_options(g1_robot_capability_profile_core PRIVATE -Wall -Wextra -Werror)
target_link_libraries(g1_robot_capability_profile_core PRIVATE PkgConfig::JSONCPP)

add_executable(g1_robot_capability_profile_test tests/g1_robot_capability_profile_test.cpp)
target_compile_options(g1_robot_capability_profile_test PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_compile_definitions(g1_robot_capability_profile_test PRIVATE
  G1_SOURCE_DIR="${CMAKE_SOURCE_DIR}"
)
target_link_libraries(g1_robot_capability_profile_test PRIVATE
  g1_robot_capability_profile_core
  PkgConfig::JSONCPP
)
add_test(NAME g1_robot_capability_profile_core COMMAND g1_robot_capability_profile_test)

# SDK-R2 EpisodeV2: 纯离线 24D 遥操事件、终态处置与训练资格验证。
add_test(NAME g1_teleop_episode_v2
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_teleop_episode_v2_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_teleop_episode_v2.py"
)

add_test(NAME g1_official_xr_adapter
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_official_xr_adapter_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_official_xr_adapter.py"
)

add_test(NAME g1_official_xr_dataset_tools
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_official_xr_dataset_tools_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_official_xr_success_view.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_official_xr_cleanup.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_official_xr_training_release.py"
)

add_test(NAME g1_teleop_runtime_bridge
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_teleop_runtime_bridge_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_teleop_episode_v2.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_teleop_runtime_bridge.py"
          "$<TARGET_FILE:g1_upper_body_runtime_codec_test>"
)

add_test(NAME g1_teleop_readonly_capture
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_teleop_readonly_capture_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_teleop_readonly_capture.py"
)

add_test(NAME g1_quest_raw_capture
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_quest_raw_capture_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_quest_raw_capture.py"
)

add_test(NAME g1_quest_realtime_preview
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_quest_realtime_preview_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_quest_realtime_preview.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_quest_24d_mapping_preview.py"
)

add_test(NAME g1_teleop_collection_session
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_teleop_collection_session_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_teleop_collection_session.py"
)

add_test(NAME g1_quest_g1_teleop_qualification
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_quest_g1_teleop_qualification_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_quest_g1_teleop_qualification.py"
          "$<TARGET_FILE:g1_upper_body_runtime_codec_test>"
)

add_test(NAME g1_quest_g1_bounded_teleop_smoke
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_quest_g1_bounded_teleop_smoke_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_quest_g1_bounded_teleop_smoke.py"
          "$<TARGET_FILE:g1_upper_body_runtime_codec_test>"
)

add_test(NAME g1_pi05_policy_preview
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_pi05_policy_preview_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_pi05_policy_preview.py"
)

add_test(NAME g1_pi05_policy_first_frame
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_pi05_policy_first_frame_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_pi05_policy_first_frame.py"
)

add_test(NAME g1_pi05_policy_bounded_run
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_pi05_policy_bounded_run_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_pi05_policy_bounded_run.py"
)

add_test(NAME g1_pi05_safety_sidecar
  COMMAND "${Python3_EXECUTABLE}"
          "${CMAKE_SOURCE_DIR}/tests/g1_pi05_safety_sidecar_test.py"
          "${CMAKE_SOURCE_DIR}/scripts/g1_pi05_safety_sidecar.py"
)
