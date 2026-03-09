idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES esp_wifi esp_event nvs_flash driver esp_timer json esp_websocket_client mbedtls esp_http_server esp_https_ota app_update esp_http_client
)
