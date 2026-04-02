# GPUStress CMakeLists.txt - v1.0.0
cmake_minimum_required(VERSION 3.20)
project(GPUStress)

set(CMAKE_CXX_STANDARD 17)

add_executable(GPUStress
    main.cpp
    dx12_engine.cpp
)

target_compile_definitions(GPUStress PRIVATE UNICODE _UNICODE)

target_link_libraries(GPUStress
    d3d12.lib
    dxgi.lib
    d3dcompiler.lib
    dxguid.lib
)

# Copy shaders to build output
add_custom_command(TARGET GPUStress POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
    ${CMAKE_SOURCE_DIR}/shaders
    $<TARGET_FILE_DIR:GPUStress>/shaders
)