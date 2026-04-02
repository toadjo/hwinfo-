// stress_compute.hlsl - v1.0.0
RWStructuredBuffer<float> output : register(u0);

[numthreads(256, 1, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    float val = (float)id.x;
    // Heavy FMA loop to max out FLOPS
    [unroll(128)]
    for (int i = 0; i < 128; i++)
    {
        val = val * 1.00001f + 0.00001f;
    }
    output[id.x % 1024] = val;
}