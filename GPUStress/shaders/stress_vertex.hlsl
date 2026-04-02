// stress_vertex.hlsl - v2.0.0 BRUTAL
float4 VSMain(uint vertID : SV_VertexID,
              uint instID : SV_InstanceID) : SV_Position
{
    // Dense procedural geometry — forces vertex shader units hard
    float fi = (float)instID * 0.00314159f;
    float fv = (float)vertID * 2.09439f; // 2*pi/3

    float angle = fi + fv;
    float r = 0.8f + sin(fi * 7.3f) * 0.15f;

    // Complex position with multiple transcendentals
    float x = sin(angle) * r + cos(fi * 3.1f) * 0.05f;
    float y = cos(angle) * r + sin(fi * 5.7f) * 0.05f;
    float z = sin(fi * 2.3f + fv) * 0.3f + 0.5f;
    float w = cos(fi * 1.7f) * 0.1f + 1.0f;

    return float4(x, y, z, w);
}
