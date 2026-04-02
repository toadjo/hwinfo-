// GPUStress dx12_engine.h - v1.0.0
#pragma once

#include <d3d12.h>
#include <dxgi1_6.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <string>
#include <atomic>
#include <thread>
#include <chrono>
#include "d3dx12.h"

using Microsoft::WRL::ComPtr;

enum class StressMode {
    COMPUTE_FLOPS,
    VRAM_BANDWIDTH,
    RASTERIZER,
    ALL
};

struct StressConfig {
    StressMode mode = StressMode::ALL;
    int durationSeconds = 0; // 0 = infinite
    float intensity = 1.0f;  // 0.0 - 1.0
};

class DX12Engine {
public:
    bool Init();
    void Run(const StressConfig& config);
    void Stop();
    ~DX12Engine();

private:
    // Device
    ComPtr<ID3D12Device>              m_device;
    ComPtr<IDXGIFactory6>             m_factory;
    ComPtr<IDXGIAdapter1>             m_adapter;

    // Command infrastructure
    ComPtr<ID3D12CommandQueue>        m_cmdQueue;
    ComPtr<ID3D12CommandAllocator>    m_cmdAlloc;
    ComPtr<ID3D12GraphicsCommandList> m_cmdList;

    // Fence
    ComPtr<ID3D12Fence>               m_fence;
    UINT64                            m_fenceValue = 0;
    HANDLE                            m_fenceEvent = nullptr;

    // Compute pipeline
    ComPtr<ID3D12RootSignature>       m_computeRootSig;
    ComPtr<ID3D12PipelineState>       m_computePSO;

    // Rasterizer pipeline
    ComPtr<ID3D12RootSignature>       m_gfxRootSig;
    ComPtr<ID3D12PipelineState>       m_gfxPSO;

    // VRAM buffers
    ComPtr<ID3D12Resource>            m_vramSrc;
    ComPtr<ID3D12Resource>            m_vramDst;

    // Render target (offscreen)
    ComPtr<ID3D12Resource>            m_renderTarget;
    ComPtr<ID3D12DescriptorHeap>      m_rtvHeap;
    ComPtr<ID3D12DescriptorHeap>      m_cbvSrvUavHeap;

    std::atomic<bool>                 m_running{ false };

    bool InitDevice();
    bool InitComputePipeline();
    bool InitRasterizerPipeline();
    bool InitVRAMBuffers();
    bool InitRenderTarget();

    void RunCompute();
    void RunVRAMBandwidth();
    void RunRasterizer();

    void WaitForGPU();
    ComPtr<ID3DBlob> CompileShader(const std::wstring& filename,
                                   const std::string& entrypoint,
                                   const std::string& target);
};