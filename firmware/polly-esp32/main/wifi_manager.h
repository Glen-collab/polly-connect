#ifndef WIFI_MANAGER_H
#define WIFI_MANAGER_H

#include "esp_err.h"

/**
 * Initialize WiFi in station mode and connect to configured AP
 *
 * @return ESP_OK on success, ESP_FAIL on failure
 */
esp_err_t wifi_init_sta(void);

#endif // WIFI_MANAGER_H
