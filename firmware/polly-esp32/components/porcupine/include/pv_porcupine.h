/*
    Porcupine Wake Word Header

    This is a placeholder header file. You need to download the actual
    pv_porcupine.h header from the Porcupine SDK and replace this file.

    Download from: https://github.com/Picovoice/porcupine
    Location in repo: include/pv_porcupine.h

    The header defines the following key functions:
    - pv_porcupine_init()
    - pv_porcupine_process()
    - pv_porcupine_delete()
    - pv_porcupine_frame_length()
    - pv_sample_rate()
*/

#ifndef PV_PORCUPINE_H
#define PV_PORCUPINE_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

// Porcupine status codes
typedef enum {
    PV_STATUS_SUCCESS = 0,
    PV_STATUS_OUT_OF_MEMORY,
    PV_STATUS_IO_ERROR,
    PV_STATUS_INVALID_ARGUMENT,
    PV_STATUS_STOP_ITERATION,
    PV_STATUS_KEY_ERROR,
    PV_STATUS_INVALID_STATE,
    PV_STATUS_RUNTIME_ERROR,
    PV_STATUS_ACTIVATION_ERROR,
    PV_STATUS_ACTIVATION_LIMIT_REACHED,
    PV_STATUS_ACTIVATION_THROTTLED,
    PV_STATUS_ACTIVATION_REFUSED
} pv_status_t;

// Opaque Porcupine object
typedef struct pv_porcupine pv_porcupine_t;

/**
 * Initialize Porcupine
 *
 * NOTE: This is a placeholder declaration. Replace this entire file with
 * the actual pv_porcupine.h from the Porcupine SDK.
 */
pv_status_t pv_porcupine_init(
    const char *access_key,
    int32_t num_keywords,
    const void **keyword_model_paths,
    const float *sensitivities,
    pv_porcupine_t **object);

/**
 * Process audio frame
 */
pv_status_t pv_porcupine_process(
    pv_porcupine_t *object,
    const int16_t *pcm,
    int32_t *keyword_index);

/**
 * Destroy Porcupine instance
 */
void pv_porcupine_delete(pv_porcupine_t *object);

/**
 * Get frame length (number of samples per frame)
 */
int32_t pv_porcupine_frame_length(void);

/**
 * Get sample rate
 */
int32_t pv_sample_rate(void);

#ifdef __cplusplus
}
#endif

#endif // PV_PORCUPINE_H
