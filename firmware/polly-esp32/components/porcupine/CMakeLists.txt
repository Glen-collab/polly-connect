# Porcupine Wake Word Component

# Create a dummy source file (required by idf_component_register)
set(COMPONENT_SRCS "porcupine_dummy.c")
set(COMPONENT_ADD_INCLUDEDIRS "include")

idf_component_register(
    SRCS "porcupine_dummy.c"
    INCLUDE_DIRS "include"
    PRIV_REQUIRES ""
)

# Add pre-compiled Porcupine library
# Note: You need to download libpv_porcupine.a from Porcupine SDK
# and place it in the lib/ directory
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/lib/libpv_porcupine.a")
    target_link_libraries(${COMPONENT_LIB} INTERFACE
        "${CMAKE_CURRENT_SOURCE_DIR}/lib/libpv_porcupine.a"
    )
    message(STATUS "Porcupine library found and linked")
else()
    message(WARNING "Porcupine library not found at ${CMAKE_CURRENT_SOURCE_DIR}/lib/libpv_porcupine.a")
    message(WARNING "Please download the library from https://github.com/Picovoice/porcupine")
endif()

# Embed wake word model file
# Note: You need to download the .ppn model file and place it in models/ directory
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/models/jarvis_esp.ppn")
    target_add_binary_data(${COMPONENT_LIB}
        "${CMAKE_CURRENT_SOURCE_DIR}/models/jarvis_esp.ppn"
        BINARY
    )
    message(STATUS "Wake word model found and will be embedded")
else()
    message(WARNING "Wake word model not found at ${CMAKE_CURRENT_SOURCE_DIR}/models/jarvis_esp.ppn")
    message(WARNING "Please download a wake word model from https://github.com/Picovoice/porcupine")
endif()
