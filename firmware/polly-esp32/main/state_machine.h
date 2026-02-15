#ifndef STATE_MACHINE_H
#define STATE_MACHINE_H

/**
 * Application states
 */
typedef enum {
    STATE_INIT,           // Initializing
    STATE_CONNECTING,     // Connecting to WiFi/WebSocket
    STATE_IDLE,           // Listening for wake word
    STATE_WAKE_DETECTED,  // Wake word detected, streaming command
    STATE_PROCESSING,     // Waiting for server response
    STATE_PLAYING,        // Playing TTS response
    STATE_ERROR           // Error state
} app_state_t;

/**
 * Initialize the state machine
 */
void state_machine_init(void);

/**
 * Set the current application state
 *
 * @param new_state The new state to transition to
 */
void state_machine_set(app_state_t new_state);

/**
 * Get the current application state
 *
 * @return Current state
 */
app_state_t state_machine_get(void);

/**
 * Convert state to string for logging
 *
 * @param state The state to convert
 * @return String representation of the state
 */
const char* state_to_string(app_state_t state);

#endif // STATE_MACHINE_H
