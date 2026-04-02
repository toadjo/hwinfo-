// stress_vertex.hlsl - v1.0.0
float4 VSMain(uint vertID : SV_VertexID,
              uint instID : SV_InstanceID) : SV_Position
{
    // Generate triangles procedurally across screen
    float angle = (float)(instID * 3 + vertID) * 0.001f;
    float x = sin(angle) * 0.9f;
    float y = cos(angle) * 0.9f;
    return float4(x, y, 0.5f, 1.0f);
}