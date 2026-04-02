// GPUStress main.cpp - v1.0.2
#include "dx12_engine.h"
#include <iostream>
#include <string>
#include <csignal>

static DX12Engine* g_engine = nullptr;

void SignalHandler(int) {
    std::cout << "[GPUStress] Stopped by user." << std::endl;
    if (g_engine) g_engine->Stop();
}

int main(int argc, char* argv[]) {
    std::cout.setf(std::ios::unitbuf);
    std::cerr.setf(std::ios::unitbuf);

    std::signal(SIGINT, SignalHandler);

    StressConfig config;
    config.mode            = StressMode::ALL;
    config.durationSeconds = 0;
    config.intensity       = 1.0f;

    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--mode" && i + 1 < argc) {
            std::string m = argv[++i];
            if (m == "compute") config.mode = StressMode::COMPUTE_FLOPS;
            else if (m == "vram") config.mode = StressMode::VRAM_BANDWIDTH;
            else if (m == "raster") config.mode = StressMode::RASTERIZER;
            else config.mode = StressMode::ALL;
        }
        else if (arg == "--duration" && i + 1 < argc) {
            config.durationSeconds = std::stoi(argv[++i]);
        }
    }

    DX12Engine engine;
    g_engine = &engine;

    std::cout << "[GPUStress] Initializing DX12..." << std::endl;
    if (!engine.Init()) {
        std::cerr << "[GPUStress] Failed to initialize DX12!" << std::endl;
        return 1;
    }

    switch (config.mode) {
        case StressMode::COMPUTE_FLOPS:
            std::cout << "[GPUStress] Mode: GPU Core — dispatching 16M FMA compute threads" << std::endl;
            break;
        case StressMode::VRAM_BANDWIDTH:
            std::cout << "[GPUStress] Mode: VRAM — copying 256MB/s across GPU memory bus" << std::endl;
            break;
        case StressMode::RASTERIZER:
            std::cout << "[GPUStress] Mode: Rasterizer — drawing 3000 triangles @ 1080p" << std::endl;
            break;
        default:
            std::cout << "[GPUStress] Mode: Combined — Compute + VRAM + Rasterizer" << std::endl;
            std::cout << "[GPUStress]   • 16M FMA shader threads" << std::endl;
            std::cout << "[GPUStress]   • 256MB VRAM bandwidth transfers" << std::endl;
            std::cout << "[GPUStress]   • 3000 triangle rasterization @ 1080p" << std::endl;
            break;
    }
    std::cout << "[GPUStress] GPU under load — click Stop to end." << std::endl;

    engine.Run(config);

    std::cout << "[GPUStress] Done." << std::endl;
    return 0;
}