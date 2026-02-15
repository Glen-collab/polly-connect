set(srcs
    "esphome/components/micro_wake_word/micro_wake_word.cpp"
    "esphome/components/i2s_audio/microphone/i2s_audio_microphone.cpp"
    "esphome/core/helpers.cpp"
)

idf_component_register(
    SRCS ${srcs}
    INCLUDE_DIRS
        "."
        "include"
        "esphome"
    REQUIRES
        driver
        esp_http_client
        tensorflow-lite
)
