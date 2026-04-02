// stress_pixel.hlsl - v2.0.0 BRUTAL
float4 PSMain(float4 pos : SV_Position) : SV_Target
{
    float2 uv = pos.xy * 0.001f;
    float val = uv.x + uv.y + 1.0f;
    float acc = val;

    // 256 heavy ops per pixel — transcendental dependency chain
    [unroll(64)]
    for (int i = 0; i < 64; i++)
    {
        acc = sin(acc * 1.7f) + cos(acc * 0.9f);
        acc = sqrt(abs(acc) + 0.001f) * tan(acc * 0.1f + 0.01f);
        acc = exp(acc * 0.01f) - log(abs(acc) + 1.0f);
        acc = acc * acc - sqrt(abs(acc * 2.3f));
    }

    float r = abs(sin(acc));
    float g = abs(cos(acc * 1.3f));
    float b = abs(sin(acc * 0.7f + 1.0f));
    return float4(r, g, b, 1.0f);
}
