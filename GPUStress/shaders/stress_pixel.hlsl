// stress_pixel.hlsl - v1.0.0
float4 PSMain(float4 pos : SV_Position) : SV_Target
{
    // Heavy math per pixel to stress shader units
    float val = pos.x * 0.001f;
    [unroll(64)]
    for (int i = 0; i < 64; i++)
    {
        val = sin(val) * cos(val) + tan(val * 0.1f);
    }
    return float4(abs(val) % 1.0f, 0.2f, 0.5f, 1.0f);
}