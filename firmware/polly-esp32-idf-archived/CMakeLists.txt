cmake_minimum_required(VERSION 3.16)

# Set component directories
set(EXTRA_COMPONENT_DIRS components)

# Include ESP-IDF cmake
include($ENV{IDF_PATH}/tools/cmake/project.cmake)

project(polly-esp32)
