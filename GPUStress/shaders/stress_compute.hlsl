// stress_compute.hlsl - v2.0.0 BRUTAL
RWStructuredBuffer<float> output : register(u0);

[numthreads(256, 1, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    float val = (float)id.x * 0.0001f + 1.0f;
    float acc = val;

    // 512 transcendental ops — sin/cos/sqrt/exp are 10-20x heavier than FMA
    // Dependency chain prevents GPU from parallelizing — forces serial execution
    [unroll(128)]
    for (int i = 0; i < 128; i++)
    {
        acc = sqrt(abs(acc)) + sin(acc * 1.3f);
        acc = cos(acc * 0.7f) * exp(acc * 0.001f);
        acc = log(abs(acc) + 1.0f) + acc * acc;
        acc = rsqrt(abs(acc) + 0.001f) * sin(acc);
    }

    output[id.x % 1024] = acc;
}
