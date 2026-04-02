namespace LineBotWebhook.Services.Documents;

public static class MathUtilities
{
    public static float CosineSimilarity(float[] vectorA, float[] vectorB)
    {
        if (vectorA.Length != vectorB.Length)
            throw new ArgumentException("Vectors must have the same length.");

        float dotProduct = 0;
        float normA = 0;
        float normB = 0;

        for (int i = 0; i < vectorA.Length; i++)
        {
            dotProduct += vectorA[i] * vectorB[i];
            normA += vectorA[i] * vectorA[i];
            normB += vectorB[i] * vectorB[i];
        }

        if (normA == 0 || normB == 0) return 0;

        return dotProduct / (float)(Math.Sqrt(normA) * Math.Sqrt(normB));
    }
}
