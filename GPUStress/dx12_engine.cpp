// GPUStress dx12_engine.cpp - v1.0.0
#include "dx12_engine.h"
#include <stdexcept>
#include <iostream>
#include <vector>
#include <chrono>

#pragma comment(lib, "d3d12.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "d3dcompiler.lib")

bool DX12Engine::Init() {
    if (!InitDevice())             { std::cerr << "[GPUStress] FAIL: InitDevice\n";            return false; }
    if (!InitComputePipeline())    { std::cerr << "[GPUStress] FAIL: InitComputePipeline\n";   return false; }
    if (!InitRasterizerPipeline()) { std::cerr << "[GPUStress] FAIL: InitRasterizerPipeline\n";return false; }
    if (!InitVRAMBuffers())        { std::cerr << "[GPUStress] FAIL: InitVRAMBuffers\n";       return false; }
    if (!InitRenderTarget())       { std::cerr << "[GPUStress] FAIL: InitRenderTarget\n";      return false; }
    return true;
}

bool DX12Engine::InitDevice() {
    UINT dxgiFlags = 0;

    if (FAILED(CreateDXGIFactory2(dxgiFlags, IID_PPV_ARGS(&m_factory))))
        return false;

    // Pick first hardware adapter, try feature levels from high to low
    D3D_FEATURE_LEVEL featureLevels[] = {
        D3D_FEATURE_LEVEL_12_1,
        D3D_FEATURE_LEVEL_12_0,
        D3D_FEATURE_LEVEL_11_1,
        D3D_FEATURE_LEVEL_11_0,
    };
    for (UINT i = 0; m_factory->EnumAdapters1(i, &m_adapter) != DXGI_ERROR_NOT_FOUND; i++) {
        DXGI_ADAPTER_DESC1 desc;
        m_adapter->GetDesc1(&desc);
        if (desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) continue;
        for (auto fl : featureLevels) {
            if (SUCCEEDED(D3D12CreateDevice(m_adapter.Get(), fl, IID_PPV_ARGS(&m_device)))) {
                std::wcout << L"[GPU] " << desc.Description << L"\n";
                goto device_found;
            }
        }
    }
    device_found:;
    if (!m_device) return false;

    // Command queue
    D3D12_COMMAND_QUEUE_DESC qDesc = {};
    qDesc.Type  = D3D12_COMMAND_LIST_TYPE_DIRECT;
    qDesc.Flags = D3D12_COMMAND_QUEUE_FLAG_NONE;
    if (FAILED(m_device->CreateCommandQueue(&qDesc, IID_PPV_ARGS(&m_cmdQueue))))
        return false;

    if (FAILED(m_device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,
                                                 IID_PPV_ARGS(&m_cmdAlloc))))
        return false;

    if (FAILED(m_device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT,
                                            m_cmdAlloc.Get(), nullptr,
                                            IID_PPV_ARGS(&m_cmdList))))
        return false;

    m_cmdList->Close();

    // Fence
    if (FAILED(m_device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&m_fence))))
        return false;

    m_fenceEvent = CreateEvent(nullptr, FALSE, FALSE, nullptr);
    if (!m_fenceEvent) return false;

    return true;
}

bool DX12Engine::InitComputePipeline() {
    // Root signature: 1 UAV — use v1.0 for maximum compatibility
    D3D12_DESCRIPTOR_RANGE range = {};
    range.RangeType          = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    range.NumDescriptors     = 1;
    range.BaseShaderRegister = 0;
    range.RegisterSpace      = 0;
    range.OffsetInDescriptorsFromTableStart = 0;

    D3D12_ROOT_PARAMETER param = {};
    param.ParameterType                       = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    param.DescriptorTable.NumDescriptorRanges = 1;
    param.DescriptorTable.pDescriptorRanges   = &range;
    param.ShaderVisibility                    = D3D12_SHADER_VISIBILITY_ALL;

    D3D12_ROOT_SIGNATURE_DESC rsDesc = {};
    rsDesc.NumParameters = 1;
    rsDesc.pParameters   = &param;
    rsDesc.Flags         = D3D12_ROOT_SIGNATURE_FLAG_NONE;

    ComPtr<ID3DBlob> sigBlob, errBlob;
    if (FAILED(D3D12SerializeRootSignature(&rsDesc, D3D_ROOT_SIGNATURE_VERSION_1,
                                           &sigBlob, &errBlob)))
        return false;

    if (FAILED(m_device->CreateRootSignature(0, sigBlob->GetBufferPointer(),
                                              sigBlob->GetBufferSize(),
                                              IID_PPV_ARGS(&m_computeRootSig))))
        return false;

    auto shader = CompileShader(L"shaders/stress_compute.hlsl", "CSMain", "cs_5_0");
    if (!shader) return false;

    D3D12_COMPUTE_PIPELINE_STATE_DESC psoDesc = {};
    psoDesc.pRootSignature = m_computeRootSig.Get();
    psoDesc.CS = { shader->GetBufferPointer(), shader->GetBufferSize() };

    if (FAILED(m_device->CreateComputePipelineState(&psoDesc, IID_PPV_ARGS(&m_computePSO))))
        return false;

    return true;
}

bool DX12Engine::InitRasterizerPipeline() {
    // Empty root signature for rasterizer — v1.0 for compatibility
    D3D12_ROOT_SIGNATURE_DESC rsDesc = {};
    rsDesc.Flags = D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT;

    ComPtr<ID3DBlob> sigBlob, errBlob;
    if (FAILED(D3D12SerializeRootSignature(&rsDesc, D3D_ROOT_SIGNATURE_VERSION_1,
                                           &sigBlob, &errBlob)))
        return false;

    if (FAILED(m_device->CreateRootSignature(0, sigBlob->GetBufferPointer(),
                                              sigBlob->GetBufferSize(),
                                              IID_PPV_ARGS(&m_gfxRootSig))))
        return false;

    auto vs = CompileShader(L"shaders/stress_vertex.hlsl", "VSMain", "vs_5_0");
    auto ps = CompileShader(L"shaders/stress_pixel.hlsl",  "PSMain", "ps_5_0");
    if (!vs || !ps) return false;

    D3D12_GRAPHICS_PIPELINE_STATE_DESC psoDesc = {};
    psoDesc.pRootSignature        = m_gfxRootSig.Get();
    psoDesc.VS                    = { vs->GetBufferPointer(), vs->GetBufferSize() };
    psoDesc.PS                    = { ps->GetBufferPointer(), ps->GetBufferSize() };
    psoDesc.RasterizerState       = CD3DX12_RASTERIZER_DESC(D3D12_DEFAULT);
    psoDesc.BlendState            = CD3DX12_BLEND_DESC(D3D12_DEFAULT);
    psoDesc.DepthStencilState.DepthEnable   = FALSE;
    psoDesc.DepthStencilState.StencilEnable = FALSE;
    psoDesc.SampleMask            = UINT_MAX;
    psoDesc.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    psoDesc.NumRenderTargets      = 1;
    psoDesc.RTVFormats[0]         = DXGI_FORMAT_R8G8B8A8_UNORM;
    psoDesc.SampleDesc.Count      = 1;

    if (FAILED(m_device->CreateGraphicsPipelineState(&psoDesc, IID_PPV_ARGS(&m_gfxPSO))))
        return false;

    return true;
}

bool DX12Engine::InitVRAMBuffers() {
    const UINT64 bufSize = 256 * 1024 * 1024; // 256MB each

    auto heapProps = CD3DX12_HEAP_PROPERTIES(D3D12_HEAP_TYPE_DEFAULT);
    auto bufDesc   = CD3DX12_RESOURCE_DESC::Buffer(bufSize,
                         D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);

    if (FAILED(m_device->CreateCommittedResource(&heapProps, D3D12_HEAP_FLAG_NONE,
                                                  &bufDesc,
                                                  D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                                                  nullptr, IID_PPV_ARGS(&m_vramSrc))))
        return false;

    if (FAILED(m_device->CreateCommittedResource(&heapProps, D3D12_HEAP_FLAG_NONE,
                                                  &bufDesc,
                                                  D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                                                  nullptr, IID_PPV_ARGS(&m_vramDst))))
        return false;

    return true;
}

bool DX12Engine::InitRenderTarget() {
    // RTV heap
    D3D12_DESCRIPTOR_HEAP_DESC rtvHeapDesc = {};
    rtvHeapDesc.NumDescriptors = 1;
    rtvHeapDesc.Type           = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
    if (FAILED(m_device->CreateDescriptorHeap(&rtvHeapDesc, IID_PPV_ARGS(&m_rtvHeap))))
        return false;

    // CBV/SRV/UAV heap
    D3D12_DESCRIPTOR_HEAP_DESC uavHeapDesc = {};
    uavHeapDesc.NumDescriptors = 1;
    uavHeapDesc.Type           = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    uavHeapDesc.Flags          = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    if (FAILED(m_device->CreateDescriptorHeap(&uavHeapDesc, IID_PPV_ARGS(&m_cbvSrvUavHeap))))
        return false;

    // Offscreen render target 1920x1080
    auto heapProps = CD3DX12_HEAP_PROPERTIES(D3D12_HEAP_TYPE_DEFAULT);
    auto rtDesc    = CD3DX12_RESOURCE_DESC::Tex2D(DXGI_FORMAT_R8G8B8A8_UNORM, 1920, 1080,
                                                   1, 1, 1, 0,
                                                   D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
    D3D12_CLEAR_VALUE clearVal = {};
    clearVal.Format   = DXGI_FORMAT_R8G8B8A8_UNORM;
    clearVal.Color[0] = 0.0f;

    if (FAILED(m_device->CreateCommittedResource(&heapProps, D3D12_HEAP_FLAG_NONE,
                                                  &rtDesc,
                                                  D3D12_RESOURCE_STATE_RENDER_TARGET,
                                                  &clearVal,
                                                  IID_PPV_ARGS(&m_renderTarget))))
        return false;

    m_device->CreateRenderTargetView(m_renderTarget.Get(), nullptr,
                                      m_rtvHeap->GetCPUDescriptorHandleForHeapStart());

    // UAV for compute on VRAM src
    D3D12_UNORDERED_ACCESS_VIEW_DESC uavDesc = {};
    uavDesc.ViewDimension       = D3D12_UAV_DIMENSION_BUFFER;
    uavDesc.Buffer.NumElements  = (UINT)(256 * 1024 * 1024 / sizeof(float));
    uavDesc.Format              = DXGI_FORMAT_UNKNOWN;
    uavDesc.Buffer.StructureByteStride = sizeof(float);
    m_device->CreateUnorderedAccessView(m_vramSrc.Get(), nullptr, &uavDesc,
                                         m_cbvSrvUavHeap->GetCPUDescriptorHandleForHeapStart());

    return true;
}

void DX12Engine::Run(const StressConfig& config) {
    m_running = true;
    bool hasDuration = config.durationSeconds > 0;
    auto deadline  = std::chrono::steady_clock::now() + std::chrono::seconds(hasDuration ? config.durationSeconds : 99999999);
    auto startTime = std::chrono::steady_clock::now();
    auto lastReport = startTime;
    int loop = 0;

    while (m_running) {
        if (hasDuration && std::chrono::steady_clock::now() >= deadline) break;

        if (config.mode == StressMode::COMPUTE_FLOPS || config.mode == StressMode::ALL)
            RunCompute();
        if (config.mode == StressMode::VRAM_BANDWIDTH || config.mode == StressMode::ALL)
            RunVRAMBandwidth();
        if (config.mode == StressMode::RASTERIZER || config.mode == StressMode::ALL)
            RunRasterizer();

        WaitForGPU();
        loop++;

        // Report every 5 seconds regardless of iteration count
        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration_cast<std::chrono::seconds>(now - lastReport).count() >= 5) {
            auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(now - startTime).count();
            std::cout << "[GPUStress] " << elapsed << "s — " << loop << " iterations completed" << std::endl;
            lastReport = now;
        }
    }

    std::cout << "[GPUStress] Stopped." << std::endl;
}

void DX12Engine::RunCompute() {
    m_cmdAlloc->Reset();
    m_cmdList->Reset(m_cmdAlloc.Get(), m_computePSO.Get());

    m_cmdList->SetComputeRootSignature(m_computeRootSig.Get());
    ID3D12DescriptorHeap* heaps[] = { m_cbvSrvUavHeap.Get() };
    m_cmdList->SetDescriptorHeaps(1, heaps);
    m_cmdList->SetComputeRootDescriptorTable(0,
        m_cbvSrvUavHeap->GetGPUDescriptorHandleForHeapStart());

    // Dispatch 65535 groups of 256 threads = max GPU occupancy
    m_cmdList->Dispatch(65535, 1, 1);
    m_cmdList->Close();

    ID3D12CommandList* lists[] = { m_cmdList.Get() };
    m_cmdQueue->ExecuteCommandLists(1, lists);
}

void DX12Engine::RunVRAMBandwidth() {
    m_cmdAlloc->Reset();
    m_cmdList->Reset(m_cmdAlloc.Get(), nullptr);

    // Transition src to COPY_SOURCE, dst to COPY_DEST
    D3D12_RESOURCE_BARRIER barriers[2] = {};
    barriers[0] = CD3DX12_RESOURCE_BARRIER::Transition(m_vramSrc.Get(),
        D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
    barriers[1] = CD3DX12_RESOURCE_BARRIER::Transition(m_vramDst.Get(),
        D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_DEST);
    m_cmdList->ResourceBarrier(2, barriers);

    m_cmdList->CopyResource(m_vramDst.Get(), m_vramSrc.Get());

    // Transition back
    barriers[0] = CD3DX12_RESOURCE_BARRIER::Transition(m_vramSrc.Get(),
        D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    barriers[1] = CD3DX12_RESOURCE_BARRIER::Transition(m_vramDst.Get(),
        D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    m_cmdList->ResourceBarrier(2, barriers);

    m_cmdList->Close();
    ID3D12CommandList* lists[] = { m_cmdList.Get() };
    m_cmdQueue->ExecuteCommandLists(1, lists);
}

void DX12Engine::RunRasterizer() {
    m_cmdAlloc->Reset();
    m_cmdList->Reset(m_cmdAlloc.Get(), m_gfxPSO.Get());

    m_cmdList->SetGraphicsRootSignature(m_gfxRootSig.Get());

    D3D12_VIEWPORT vp = { 0, 0, 1920, 1080, 0.0f, 1.0f };
    D3D12_RECT scissor = { 0, 0, 1920, 1080 };
    m_cmdList->RSSetViewports(1, &vp);
    m_cmdList->RSSetScissorRects(1, &scissor);

    auto rtv = m_rtvHeap->GetCPUDescriptorHandleForHeapStart();
    m_cmdList->OMSetRenderTargets(1, &rtv, FALSE, nullptr);

    float clearColor[] = { 0.0f, 0.0f, 0.0f, 1.0f };
    m_cmdList->ClearRenderTargetView(rtv, clearColor, 0, nullptr);

    m_cmdList->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    // Draw 3000 triangles (no vertex buffer, generated in VS)
    m_cmdList->DrawInstanced(3, 3000, 0, 0);

    m_cmdList->Close();
    ID3D12CommandList* lists[] = { m_cmdList.Get() };
    m_cmdQueue->ExecuteCommandLists(1, lists);
}

void DX12Engine::WaitForGPU() {
    const UINT64 val = ++m_fenceValue;
    m_cmdQueue->Signal(m_fence.Get(), val);
    if (m_fence->GetCompletedValue() < val) {
        m_fence->SetEventOnCompletion(val, m_fenceEvent);
        WaitForSingleObject(m_fenceEvent, INFINITE);
    }
}

void DX12Engine::Stop() {
    m_running = false;
}

ComPtr<ID3DBlob> DX12Engine::CompileShader(const std::wstring& filename,
                                            const std::string& entrypoint,
                                            const std::string& target) {
    // Build path relative to the exe's own directory
    wchar_t exePath[MAX_PATH] = {};
    GetModuleFileNameW(nullptr, exePath, MAX_PATH);
    std::wstring exeDir(exePath);
    exeDir = exeDir.substr(0, exeDir.find_last_of(L"\\/") + 1);
    std::wstring fullPath = exeDir + filename;

    ComPtr<ID3DBlob> code, errors;
    UINT flags = D3DCOMPILE_OPTIMIZATION_LEVEL3;
    HRESULT hr = D3DCompileFromFile(fullPath.c_str(), nullptr,
                                     D3D_COMPILE_STANDARD_FILE_INCLUDE,
                                     entrypoint.c_str(), target.c_str(),
                                     flags, 0, &code, &errors);
    if (FAILED(hr)) {
        if (errors)
            std::cerr << "[Shader Error] "
                      << (char*)errors->GetBufferPointer() << "\n";
        std::wcerr << L"[Shader] Failed to load: " << fullPath << L"\n";
        return nullptr;
    }
    return code;
}

DX12Engine::~DX12Engine() {
    Stop();
    WaitForGPU();
    if (m_fenceEvent) CloseHandle(m_fenceEvent);
}